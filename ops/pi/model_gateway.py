"""Trusted Anthropic forwarding. No SDK retries, redirects, or client pricing."""
from dataclasses import asdict, dataclass
import hashlib
import json
import time
from queue import Queue, Empty, Full
from threading import Event, Lock, Thread
from typing import Callable, Iterator

from .budget import BudgetDenied, reserve, settle
from .contracts import Record
from .ledger import Ledger, _json
from .policy import Policy


@dataclass(frozen=True)
class GatewayResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes | Iterator[bytes]
    attempt_id: str


def _validate(body, policy, tool_allowlist=()):
    allowed = {'model', 'max_tokens', 'messages', 'system', 'stream', 'temperature', 'top_p', 'top_k', 'stop_sequences', 'thinking'}
    definitions = []
    if tool_allowlist:
        from .tools import tool_definitions
        definitions = tool_definitions(tool_allowlist)
        allowed.add('tools')
    if not isinstance(body, dict) or set(body) - allowed:
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
    if 'thinking' in body and body['thinking'] != {'type': 'disabled'}:
        raise ValueError('unsupported thinking')
    messages = body.get('messages')
    if not isinstance(messages, list) or not messages:
        raise ValueError('messages required')
    if definitions and body.get('tools') != definitions:
        raise ValueError('untrusted tool declarations')
    by_name = {d['name']:d for d in definitions}
    pending, completed = {}, set()
    def content(value, role='system'):
        if isinstance(value, str):
            return
        if not isinstance(value, list) or not value:
            raise ValueError('unsupported content')
        for block in value:
            if not isinstance(block, dict):
                raise ValueError('unsupported content block')
            if set(block) == {'type','text'} and block['type'] == 'text' and isinstance(block['text'],str):
                continue
            if definitions and role == 'assistant' and set(block) == {'type','id','name','input'} and block['type'] == 'tool_use':
                from .tools import validate_schema
                call_id, name = block['id'], block['name']
                import re
                if (not isinstance(call_id,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}',call_id) is None
                        or not isinstance(name,str) or name not in by_name or call_id in pending or call_id in completed):
                    raise ValueError('untrusted tool use')
                validate_schema(block['input'],by_name[name]['input_schema'])
                pending[call_id]=name
                continue
            if definitions and role == 'user' and set(block) == {'type','tool_use_id','content','is_error'} and block['type'] == 'tool_result':
                call_id=block['tool_use_id']
                if not isinstance(call_id,str) or call_id not in pending or type(block['is_error']) is not bool:
                    raise ValueError('unpaired tool result')
                content(block['content'])
                del pending[call_id]; completed.add(call_id)
                continue
            raise ValueError('unsupported content block')
    for message in messages:
        if not isinstance(message, dict) or set(message) != {'role', 'content'} or message['role'] not in ('user', 'assistant'):
            raise ValueError('unsupported message')
        content(message['content'],message['role'])
    if pending:
        raise ValueError('pending tool at model request')
    if 'system' in body:
        content(body['system'])
    encoded = json.dumps(body, allow_nan=False, separators=(',', ':')).encode()
    if len(encoded) > policy.max_body_bytes:
        raise ValueError('request too large')


_BILLING_DIMENSIONS = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')
_USAGE_METADATA_KEYS = frozenset(('cache_creation', 'server_tool_use', 'service_tier', 'inference_geo',
                                 'speed', 'iterations', 'total_tokens', 'input_tokens_details', 'output_tokens_details'))


def _usage_snapshot(usage):
    """Finite key names and numeric evidence only; never copy provider strings."""
    values = usage if isinstance(usage, dict) else {}
    types = {type(None): 'null', bool: 'boolean', int: 'integer', float: 'number',
             str: 'string', dict: 'object', list: 'array'}
    dimensions = {}
    for key in _BILLING_DIMENSIONS:
        value = values.get(key)
        dimensions[key] = dict(present=key in values,
                               type=types.get(type(value), 'other') if key in values else 'missing',
                               value=value if type(value) is int and 0 <= value <= 2**63 - 1 else None)
    extra_count = sum(key not in _BILLING_DIMENSIONS for key in values)
    recognized = sorted(key for key in _USAGE_METADATA_KEYS if key in values)
    fingerprints = []
    inspected = 0
    for key in values:
        if key in _BILLING_DIMENSIONS or key in _USAGE_METADATA_KEYS:
            continue
        inspected += 1
        if inspected > 8 or not isinstance(key, str) or len(key) > 256:
            continue
        try:
            encoded = key.encode('utf-8')
        except UnicodeEncodeError:
            continue
        if len(encoded) <= 256:
            fingerprints.append(hashlib.sha256(b'myink-pi-usage-key-v1\0' + encoded).hexdigest())
    details = values.get('prompt_tokens_details')
    exact_shape = isinstance(details, dict) and set(details) == {'cached_tokens'}
    cached = details.get('cached_tokens') if isinstance(details, dict) else None
    cached_valid = type(cached) is int and 0 <= cached <= 2**63 - 1
    read = dimensions['cache_read_input_tokens']['value']
    cache_details = dict(present='prompt_tokens_details' in values, exact_shape_valid=exact_shape,
                         cached_tokens_valid=cached_valid, cached_tokens=cached if cached_valid else None,
                         cache_read_equal=cached == read if exact_shape and cached_valid and read is not None else None)
    unrecognized_count = extra_count - len(recognized)
    return dict(dimensions=dimensions, prompt_tokens_details=cache_details,
                recognized_extra_keys=recognized, extra_key_count=extra_count,
                unrecognized_extra_key_count=unrecognized_count,
                unrecognized_extra_key_sha256=sorted(fingerprints),
                unrecognized_extra_keys_unfingerprinted=unrecognized_count - len(fingerprints))


def _usage_updates(usage, previous, required):
    """Validate whole cumulative evidence before replacing any known counter."""
    if (not isinstance(usage, dict) or len(usage) > len(_BILLING_DIMENSIONS) + 2
            or any(key not in (*_BILLING_DIMENSIONS, 'prompt_tokens_details', 'service_tier') for key in usage)):
        raise ValueError('invalid usage')
    # Only the frozen standard-price tier is metadata. Other tiers must not
    # silently settle against this policy's prices; never retain its raw value.
    tier = usage.get('service_tier')
    if tier is not None and (type(tier) is not str or tier != 'standard'):
        raise ValueError('unsupported service tier')
    if 'prompt_tokens_details' in usage:
        details = usage['prompt_tokens_details']
        if (not isinstance(details, dict) or set(details) != {'cached_tokens'}
                or type(details['cached_tokens']) is not int or not 0 <= details['cached_tokens'] <= 2**63 - 1
                or type(usage.get('cache_read_input_tokens')) is not int
                or details['cached_tokens'] != usage['cache_read_input_tokens']):
            raise ValueError('unsupported cache breakdown')
    updates = {}
    for key in _BILLING_DIMENSIONS:
        value = usage.get(key)
        if value is None and key not in required:
            continue  # Null or absent optional counters supply no numeric evidence.
        if (type(value) is not int or not 0 <= value <= 2**63 - 1
                or key == 'output_tokens' and key in previous and value < previous[key]):
            raise ValueError('invalid cumulative usage')
        updates[key] = value
    return updates


_USAGE_OBSERVER_QUEUE = Queue(maxsize=6)
_USAGE_OBSERVER_LOCK = Lock()
_USAGE_OBSERVER_STARTED = False


def _usage_observer_worker():
    while True:
        observer, evidence = _USAGE_OBSERVER_QUEUE.get()
        try:
            observer(evidence)
        except Exception:
            pass  # Evidence storage cannot affect a settled model attempt.
        finally:
            _USAGE_OBSERVER_QUEUE.task_done()


def _dispatch_usage_observer(observer, evidence):
    """One daemon, six queued snapshots; busy/startup/saturated evidence may drop."""
    global _USAGE_OBSERVER_STARTED
    if not _USAGE_OBSERVER_STARTED:
        if not _USAGE_OBSERVER_LOCK.acquire(blocking=False):
            return
        try:
            if not _USAGE_OBSERVER_STARTED:
                Thread(target=_usage_observer_worker, name='pi-usage-observer', daemon=True).start()
                _USAGE_OBSERVER_STARTED = True
        finally:
            _USAGE_OBSERVER_LOCK.release()
    try:
        _USAGE_OBSERVER_QUEUE.put_nowait((observer, evidence))
    except Full:
        pass  # No joining, storage wait, retry, or coverage guarantee.


class _UsageCollector:
    """Bounded evidence collection never delays the bytes being forwarded."""
    def __init__(self, capture=False):
        self.capture = capture
        self.raw_usage = {}
        self.failure = None
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
            self.failure = 'event_too_large'
            self.buffer = b''
            return
        self.buffer += chunk
        self.buffer = self.buffer.replace(b'\r\n', b'\n')
        while b'\n\n' in self.buffer:
            event, self.buffer = self.buffer.split(b'\n\n', 1)
            data = b'\n'.join(line[5:].lstrip() for line in event.split(b'\n') if line.startswith(b'data:'))
            if not data:
                continue
            reason = 'malformed_event'
            try:
                item = json.loads(data)
                kind = item['type']
                if self.stopped and kind != 'ping':
                    reason = 'event_after_stop'
                    raise ValueError('event after stop')
                if kind == 'message_start':
                    if self.started:
                        reason = 'duplicate_start'
                        raise ValueError('duplicate start')
                    self.started = True
                    usage = item['message']['usage']
                    if self.capture:
                        self.raw_usage['message_start'] = _usage_snapshot(usage)
                    reason = 'invalid_start_usage'
                    self.usage = _usage_updates(usage, {}, ('input_tokens', 'output_tokens'))
                elif kind == 'message_delta':
                    delta = item['usage']
                    if self.capture:
                        self.raw_usage['message_delta'] = _usage_snapshot(delta)
                    reason = 'invalid_usage_delta'
                    if not self.started:
                        raise ValueError('invalid usage delta')
                    updates = _usage_updates(delta, self.usage, ('output_tokens',))
                    self.usage.update(updates)
                    self.final_output_usage = True
                elif kind == 'message_stop':
                    if not self.started:
                        reason = 'stop_without_start'
                        raise ValueError('stop without start')
                    self.stopped = True
                elif kind in ('content_block_start', 'content_block_delta', 'content_block_stop'):
                    self.final_output_usage = False
                elif kind != 'ping':
                    reason = 'unrecognized_event'
                    raise ValueError('unrecognized event')
            except (ValueError, TypeError, KeyError, AttributeError):
                self.failure = reason
                self.valid = False
                self.buffer = b''
                return

    def reason(self):
        if self.failure:
            return self.failure
        if not self.started:
            return 'missing_start'
        if not self.final_output_usage:
            return 'missing_final_output_usage'
        if not self.stopped:
            return 'missing_stop'
        return 'trailing_data' if self.buffer.strip() else 'complete'

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
            response = transport(body, min(timeout, self.remaining()))
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


def forward_messages(body: Record, scope_id: str, *, ledger: Ledger, policy: Policy, transport: Callable,
                     usage_observer: Callable[[Record], None] | None = None, tool_allowlist=(), analysis_slot=None) -> GatewayResponse:
    try:
        if analysis_slot is not None:
            # The metered body and the actual transport must see the same input.
            body = json.loads(_json(body))
            policy = Policy(**asdict(policy))
        _validate(body, policy, tool_allowlist)
    except (ValueError, TypeError, OverflowError):
        return _error(400)
    if policy.live_enabled and (not policy.input_bound_calibrated or not policy.input_bound_source.strip() or not policy.price_source.strip() or any(v is None for v in policy.prices.values())):
        return _error(403)
    try:
        permit = reserve(ledger, scope_id, body, policy, analysis_slot=analysis_slot)
    except BudgetDenied:
        return _error(429)
    collector = _UsageCollector(capture=usage_observer is not None)
    outcome = 'stream_closed'
    observed = False
    upstream_evidence = dict(status_code=None, content_encoding='unavailable')

    def observe(reason):
        nonlocal observed
        if usage_observer is None or observed:
            return
        observed = True
        try:
            _dispatch_usage_observer(usage_observer, dict(attempt_id=permit.attempt_id, stream=bool(body.get('stream')),
                                stream_started=collector.started, stream_stopped=collector.stopped,
                                final_output_usage=collector.final_output_usage, parser_valid=collector.valid,
                                parser_reason=collector.failure or reason, raw_usage=collector.raw_usage,
                                upstream_response=upstream_evidence))
        except Exception:
            pass  # Optional evidence failure never changes the immutable settlement.

    upstream = _DeadlineUpstream(transport, body, policy.timeout_seconds, permit.deadline)
    try:
        response = upstream.response()
    except Exception:
        upstream.close()
        settle(ledger, permit, None)
        observe('upstream_error')
        return GatewayResponse(502, {'content-type':'application/json'}, b'{"error":"upstream unavailable"}', permit.attempt_id)
    headers = {k:v for k,v in response.headers.items() if k.lower() in ('content-type', 'request-id', 'x-request-id')}
    request_id = response.headers.get('request-id', response.headers.get('x-request-id', ''))
    unknown = {'provider_request_id': request_id}
    status = response.status_code
    # Forward only identity bytes. Raw streaming deliberately bypasses HTTPX's
    # decompressor to avoid unbounded expansion before our existing size checks.
    encoding = response.headers.get('content-encoding')
    encoding = encoding.strip().lower() if encoding is not None and len(encoding) <= 32 else encoding
    encoding_class = ('absent' if encoding is None else encoding
                      if encoding in ('identity', 'gzip', 'deflate', 'br', 'zstd') else 'other')
    upstream_evidence.update(status_code=status if type(status) is int and 100 <= status <= 599 else None,
                             content_encoding=encoding_class)
    if 300 <= status < 400:
        upstream.close()
        settle(ledger, permit, unknown)
        observe('redirect_refused')
        return GatewayResponse(502, headers, b'{"error":"redirect refused"}', permit.attempt_id)

    if encoding_class not in ('absent', 'identity'):
        upstream.close()
        settle(ledger, permit, unknown)
        observe('unsupported_content_encoding')
        return GatewayResponse(502, {'content-type': 'application/json'},
                               b'{"error":"upstream encoding unsupported"}', permit.attempt_id)

    def finish_unknown():
        upstream.close()
        settle(ledger, permit, unknown)
        observe(outcome)

    def chunks():
        nonlocal outcome
        buffer = bytearray()
        try:
            for chunk in upstream:
                if time.time() > permit.deadline:
                    raise TimeoutError('model deadline exceeded')
                if body.get('stream'):
                    if collector.capture:
                        collector.feed(chunk)
                    yield chunk
                    if not collector.capture:
                        collector.feed(chunk)
                else:
                    if len(buffer) + len(chunk) > 1048576:
                        raise ValueError('response too large')
                    buffer.extend(chunk)
                    yield chunk
            outcome = collector.reason() if body.get('stream') else 'invalid_response_usage'
            if status != 200:
                outcome = 'non_success_status'
            if status == 200 and time.time() <= permit.deadline:
                if body.get('stream'):
                    if not collector.complete():
                        return
                    usage = collector.usage
                else:
                    try:
                        item = json.loads(buffer)
                        usage = item['usage']
                        if collector.capture:
                            collector.raw_usage['response'] = _usage_snapshot(usage)
                        outcome = 'complete' if isinstance(usage, dict) else 'invalid_response_usage'
                        if isinstance(usage, dict):
                            usage['provider_request_id'] = item.get('id', request_id)
                    except (ValueError, KeyError, TypeError):
                        collector.valid = False
                        outcome = 'invalid_response_json'
                        return
                if isinstance(usage, dict):
                    usage['provider_request_id'] = usage.get('provider_request_id', request_id)
                    settle(ledger, permit, usage)
        except Exception:
            outcome = 'upstream_error'
            raise
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
