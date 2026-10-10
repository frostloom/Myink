"""Trusted Anthropic forwarding. No SDK retries, redirects, or client pricing."""
from dataclasses import dataclass
import json
import time
from queue import Queue, Empty, Full
from threading import Event, Thread
from typing import Callable, Iterator

from .budget import BudgetDenied, reserve, settle
from .contracts import Record
from .ledger import Ledger
from .policy import Policy


@dataclass(frozen=True)
class GatewayResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes | Iterator[bytes]
    attempt_id: str


def _validate(body, policy):
    if not isinstance(body, dict) or set(body) - {'model', 'max_tokens', 'messages', 'system', 'stream', 'temperature', 'top_p', 'top_k', 'stop_sequences'}:
        raise ValueError('unsupported request fields')
    if body.get('model') != policy.model or type(body.get('max_tokens')) is not int or not 0 < body['max_tokens'] <= policy.max_tokens:
        raise ValueError('invalid model or max_tokens')
    if 'stream' in body and type(body['stream']) is not bool:
        raise ValueError('invalid stream flag')
    for key in ('temperature', 'top_p'):
        if key in body and (type(body[key]) not in (int, float) or not 0 <= body[key] <= 1):
            raise ValueError('invalid sampling parameter')
    if 'top_k' in body and (type(body['top_k']) is not int or body['top_k'] < 0):
        raise ValueError('invalid top_k')
    if 'stop_sequences' in body and (not isinstance(body['stop_sequences'], list) or not all(isinstance(v, str) for v in body['stop_sequences'])):
        raise ValueError('invalid stop_sequences')
    messages = body.get('messages')
    if not isinstance(messages, list) or not messages:
        raise ValueError('messages required')
    def content(value):
        if isinstance(value, str):
            return
        if not isinstance(value, list) or not value:
            raise ValueError('unsupported content')
        for block in value:
            if not isinstance(block, dict) or set(block) != {'type', 'text'} or block['type'] != 'text' or not isinstance(block['text'], str):
                raise ValueError('unsupported content block')
    for message in messages:
        if not isinstance(message, dict) or set(message) != {'role', 'content'} or message['role'] not in ('user', 'assistant'):
            raise ValueError('unsupported message')
        content(message['content'])
    if 'system' in body:
        content(body['system'])
    encoded = json.dumps(body, allow_nan=False, separators=(',', ':')).encode()
    if len(encoded) > policy.max_body_bytes:
        raise ValueError('request too large')


class _UsageCollector:
    """Bounded evidence collection never delays the bytes being forwarded."""
    def __init__(self):
        self.buffer = b''
        self.usage = {}
        self.valid = True
        self.started = self.stopped = self.final_output_usage = False

    def feed(self, chunk):
        if not self.valid:
            return
        # Bound before concatenation, including a single oversized upstream chunk.
        if len(self.buffer) + len(chunk) > 65536:
            self.valid = False
            self.buffer = b''
            return
        self.buffer += chunk
        self.buffer = self.buffer.replace(b'\r\n', b'\n')
        while b'\n\n' in self.buffer:
            event, self.buffer = self.buffer.split(b'\n\n', 1)
            data = b'\n'.join(line[5:].lstrip() for line in event.split(b'\n') if line.startswith(b'data:'))
            if not data:
                continue
            try:
                item = json.loads(data)
                kind = item['type']
                if self.stopped and kind != 'ping':
                    raise ValueError('event after stop')
                if kind == 'message_start':
                    if self.started:
                        raise ValueError('duplicate start')
                    self.started = True
                    self.usage = item['message']['usage']
                    if not isinstance(self.usage, dict) or len(self.usage) > 8:
                        raise ValueError('invalid usage')
                elif kind == 'message_delta':
                    delta = item['usage']
                    if (not self.started or not isinstance(delta, dict) or set(delta) != {'output_tokens'}
                            or type(delta['output_tokens']) is not int
                            or delta['output_tokens'] < self.usage.get('output_tokens', 0)):
                        raise ValueError('invalid usage delta')
                    self.usage.update(delta)
                    self.final_output_usage = True
                elif kind == 'message_stop':
                    if not self.started:
                        raise ValueError('stop without start')
                    self.stopped = True
                elif kind in ('content_block_start', 'content_block_delta', 'content_block_stop'):
                    self.final_output_usage = False
                elif kind != 'ping':
                    raise ValueError('unrecognized event')
            except (ValueError, TypeError, KeyError, AttributeError):
                self.valid = False
                self.buffer = b''
                return

    def complete(self):
        return self.valid and self.started and self.final_output_usage and self.stopped and not self.buffer.strip()


class _DeadlineUpstream:
    """One bounded worker per reserved attempt; only the caller can settle.

    A transport blocked inside its own I/O may finish later. Its response is
    closed then, and can never refund an attempt that timed out at this boundary.
    """
    def __init__(self, transport, body, timeout, deadline):
        self.deadline = deadline
        self.monotonic_deadline = time.monotonic() + max(0, deadline - time.time())
        self.commands = Queue(maxsize=1)
        self.results = Queue(maxsize=1)
        self.cancelled = Event()
        self.worker = Thread(target=self._run, args=(transport, body, timeout), daemon=True)
        self.worker.start()

    def remaining(self):
        return min(self.deadline - time.time(), self.monotonic_deadline - time.monotonic())

    def _run(self, transport, body, timeout):
        response = None
        try:
            if self.cancelled.is_set() or self.remaining() <= 0:
                return  # A durable reservation may have exhausted its deadline.
            response = transport(body, timeout)
            if self.cancelled.is_set():
                return
            self.results.put(('response', response))
            source = iter(response.iter_bytes() if response.is_stream_consumed else response.iter_raw())
            while not self.cancelled.is_set():
                remaining = self.remaining()
                if remaining <= 0:
                    return
                try:
                    command = self.commands.get(timeout=remaining)
                except Empty:
                    return
                if command != 'next' or self.cancelled.is_set():
                    return
                try:
                    chunk = next(source)
                except StopIteration:
                    self.results.put(('eof', None))
                    return
                if self.cancelled.is_set():
                    return
                self.results.put(('chunk', chunk))
        except Exception as exc:
            if not self.cancelled.is_set():
                self.results.put(('error', exc))
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass  # Cleanup must not print transport exception context.

    def receive(self):
        remaining = self.remaining()
        if remaining <= 0:
            self.close()
            raise TimeoutError('model deadline exceeded')
        try:
            kind, value = self.results.get(timeout=remaining)
        except Empty:
            self.close()
            raise TimeoutError('model deadline exceeded') from None
        if self.remaining() <= 0:
            self.close()
            raise TimeoutError('model deadline exceeded')
        if kind == 'error':
            raise value
        return kind, value

    def response(self):
        kind, value = self.receive()
        if kind != 'response':
            raise ValueError('invalid transport response')
        return value

    def __iter__(self):
        return self

    def __next__(self):
        if self.cancelled.is_set():
            raise StopIteration
        self.commands.put_nowait('next')
        kind, value = self.receive()
        if kind == 'eof':
            raise StopIteration
        if kind != 'chunk':
            raise ValueError('invalid transport stream')
        return value

    def close(self):
        self.cancelled.set()
        try:
            self.commands.put_nowait(None)
        except Full:
            pass


class _StreamBody:
    """Closing an unstarted stream still closes transport and records uncertainty."""
    def __init__(self, source, cleanup):
        self.source = source
        self.cleanup = cleanup

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.source)

    def close(self):
        try:
            self.source.close()
        finally:
            self.cleanup()


def _error(code):
    return GatewayResponse(code, {'content-type':'application/json'}, b'{"error":"request blocked"}', '')


def forward_messages(body: Record, scope_id: str, *, ledger: Ledger, policy: Policy, transport: Callable) -> GatewayResponse:
    try:
        _validate(body, policy)
    except (ValueError, TypeError, OverflowError):
        return _error(400)
    if policy.live_enabled and (not policy.input_bound_calibrated or not policy.input_bound_source.strip() or not policy.price_source.strip() or any(v is None for v in policy.prices.values())):
        return _error(403)
    try:
        permit = reserve(ledger, scope_id, body, policy)
    except BudgetDenied:
        return _error(429)
    upstream = _DeadlineUpstream(transport, body, policy.timeout_seconds, permit.deadline)
    try:
        response = upstream.response()
    except Exception:
        upstream.close()
        settle(ledger, permit, None)
        return GatewayResponse(502, {'content-type':'application/json'}, b'{"error":"upstream unavailable"}', permit.attempt_id)
    headers = {k:v for k,v in response.headers.items() if k.lower() in ('content-type', 'request-id', 'x-request-id')}
    request_id = response.headers.get('request-id', response.headers.get('x-request-id', ''))
    unknown = {'provider_request_id': request_id}
    status = response.status_code
    if 300 <= status < 400:
        upstream.close()
        settle(ledger, permit, unknown)
        return GatewayResponse(502, headers, b'{"error":"redirect refused"}', permit.attempt_id)

    def finish_unknown():
        upstream.close()
        settle(ledger, permit, unknown)

    def chunks():
        buffer = bytearray()
        collector = _UsageCollector()
        try:
            for chunk in upstream:
                if time.time() > permit.deadline:
                    raise TimeoutError('model deadline exceeded')
                if body.get('stream'):
                    yield chunk
                    collector.feed(chunk)
                else:
                    if len(buffer) + len(chunk) > 1048576:
                        raise ValueError('response too large')
                    buffer.extend(chunk)
                    yield chunk
            if status == 200 and time.time() <= permit.deadline:
                if body.get('stream'):
                    if not collector.complete():
                        return
                    usage = collector.usage
                else:
                    try:
                        item = json.loads(buffer)
                        usage = item['usage']
                        if isinstance(usage, dict):
                            usage['provider_request_id'] = item.get('id', request_id)
                    except (ValueError, KeyError, TypeError):
                        return
                if isinstance(usage, dict):
                    usage['provider_request_id'] = usage.get('provider_request_id', request_id)
                    settle(ledger, permit, usage)
        finally:
            finish_unknown()
    iterator = chunks()
    if body.get('stream'):
        return GatewayResponse(status, headers, _StreamBody(iterator, finish_unknown), permit.attempt_id)
    try:
        result = b''.join(iterator)
    except Exception:
        return GatewayResponse(502, headers, b'{"error":"upstream unavailable"}', permit.attempt_id)
    return GatewayResponse(status, headers, result, permit.attempt_id)
