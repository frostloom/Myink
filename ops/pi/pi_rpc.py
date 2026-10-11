"""Binary LF Pi RPC adapter. Acceptance is pending; owned exit precedes handoff."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from queue import Empty, Full, Queue
import subprocess
from threading import Lock, Thread
import time
import uuid
from .contracts import Receipt
from .engine import AdministratorContext, EngineSession


class PiAdapter:
    def __init__(self, command, *, cwd, env, config_hash):
        self.command = list(command)
        self.cwd = Path(cwd)
        self.env = dict(env)
        self.config_hash = config_hash
        self._lock = Lock()
        self._process = None

    def _redact(self, value):
        text = str(value)
        token = self.env.get('SCOPED_GATEWAY_TOKEN')
        return text.replace(token, '[scoped-token]') if token else text

    def _read_stdout(self):
        try:
            while True:
                line = self._process.stdout.readline(1048577)
                if not line:
                    self._records.put(('eof', None), timeout=1)
                    return
                if len(line) > 1048576 or not line.endswith(b'\n'):
                    raise ValueError('invalid binary LF frame')
                record = json.loads(line.rstrip(b'\n').rstrip(b'\r'))
                if not isinstance(record, dict) or not isinstance(record.get('type'), str) or not record['type']:
                    raise ValueError('invalid RPC frame type')
                self._records.put(('record', record), timeout=1)
        except (ValueError, OSError, Full):
            self._reader_error = True
            try:
                self._records.put_nowait(('failure', None))
            except Full:
                pass

    def _read_stderr(self):
        while True:
            chunk = self._process.stderr.read(4096)
            if not chunk:
                return
            self._stderr_bytes += len(chunk)
            self._stderr_prefix.extend(chunk[:max(0, 8192-len(self._stderr_prefix))])

    def _write_stdin(self):
        while True:
            line = self._writes.get()
            if line is None:
                return
            try:
                self._process.stdin.write(line)
                self._process.stdin.flush()
            except (OSError, ValueError):
                self._writer_error = True
                return

    def _log(self, direction, record):
        try:
            if self._transcript is None:
                raise OSError('transcript unavailable')
            value = json.dumps({'direction': direction, 'record': record}, ensure_ascii=False)
            self._transcript.write(self._redact(value) + '\n')
            self._transcript.flush()
        except (OSError, ValueError):
            self._transcript_error = True

    def _valid_session(self, path, initial):
        try:
            if path.stat().st_size > 16 * 1024**2:
                return False
            raw = path.read_bytes()
            if not raw.endswith(b'\n') or (initial and not raw.startswith(initial)):
                return False
            records = [json.loads(line) for line in raw.split(b'\n') if line]
            header = records[0]
            if (header.get('type') != 'session' or header.get('cwd') != str(self.cwd)
                    or not isinstance(header.get('id'), str)):
                return False
            new_records = [json.loads(line) for line in raw[len(initial):].split(b'\n') if line]
            assistants = [r.get('message') for r in new_records if r.get('type') == 'message'
                          and isinstance(r.get('message'), dict) and r['message'].get('role') == 'assistant']
            if not assistants:
                return False
            message = assistants[-1]
            blocks = message.get('content', [])
            return (message.get('stopReason') == 'stop' and not message.get('errorMessage')
                    and all(isinstance(b, dict) and b.get('type') == 'text' for b in blocks)
                    and ''.join(b.get('text', '') for b in blocks) == self._text and bool(self._text.strip()))
        except (OSError, ValueError, KeyError, IndexError, AttributeError, TypeError):
            return False

    def _send(self, kind, **fields):
        command = {'id': str(uuid.uuid4()), 'type': kind, **fields}
        self._log('in', command)
        self._writes.put(json.dumps(command, ensure_ascii=False).encode() + b'\n', timeout=0.2)
        return command['id']

    def _next(self, until):
        if self._reader_error or self._writer_error:
            raise ValueError('RPC pipe failed')
        timeout = max(0, until - time.monotonic())
        if timeout == 0:
            raise Empty
        kind, record = self._records.get(timeout=timeout)
        if kind == 'eof':
            raise EOFError
        if kind == 'failure':
            raise ValueError('invalid RPC frame')
        self._log('out', record)
        self._observe(record)
        return record

    def _observe(self, record):
        if record.get('type') in ('extension_error', 'auto_retry_start', 'auto_compaction_start'):
            self._errors = True
        if record.get('type') == 'agent_settled':
            self._settled = True
            self._aborted |= record.get('aborted') is not False
        message = record.get('message', {})
        if isinstance(message, dict) and message.get('role') == 'assistant':
            if message.get('errorMessage') or message.get('stopReason') in ('error', 'aborted'):
                self._errors = True
            if record.get('type') == 'message_end':
                self._text = ''.join(b.get('text', '') for b in message.get('content', []) if isinstance(b, dict) and b.get('type') == 'text')
        if record.get('type', '').startswith('tool_'):
            self._unexpected_tool = True
        if record.get('type') == 'response' and record.get('success') is False:
            self._errors = True

    def _response(self, command_id, until):
        while True:
            record = self._next(until)
            if record.get('type') == 'response' and record.get('id') == command_id:
                return record

    def run_phase(self, *, phase: str, prompt: str, context: AdministratorContext,
                  session: EngineSession, deadline: datetime, tools: list[str]) -> Receipt:
        if (context.role != 'myink-administrator' or context.experiment_id != 'local-trial-1'
                or context.budget_scope_id != 'local-trial-1' or not context.plan_id
                or session.engine != 'pi' or session.config_hash != self.config_hash
                or session.phase != phase or tools or deadline.tzinfo is None):
            raise ValueError('untrusted engine/session/context or tool grant')
        path = Path(session.session_path)
        if not path.is_absolute() or path.is_symlink() or '..' in path.parts:
            raise ValueError('absolute owned session required')
        if session.resume:
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != session.verified_session_sha256:
                raise ValueError('verified explicit resume required')
        elif path.exists():
            raise ValueError('fresh session must not exist')
        initial = path.read_bytes() if session.resume else b''
        until = time.monotonic() + (deadline - datetime.now(timezone.utc)).total_seconds()
        if until <= time.monotonic() or not self._lock.acquire(blocking=False):
            raise ValueError('expired or active phase')
        operation = str(uuid.uuid4())
        self._process = None
        self._transcript = None
        self._transcript_error = False
        self._session = session
        self._operation = operation
        self._records, self._writes = Queue(maxsize=256), Queue(maxsize=4)
        self._reader_error = self._writer_error = self._errors = self._aborted = self._settled = self._unexpected_tool = False
        self._text = ''
        self._stderr_bytes = 0
        self._stderr_prefix = bytearray()
        self._threads = []
        accepted, disposition, reason = False, None, 'deadline'
        transcript = path.parent / (operation + '.rpc.jsonl')
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with transcript.open('x', encoding='utf-8', newline='\n') as self._transcript:
                self._process = subprocess.Popen(self.command + ['--session-dir', str(path.parent), '--session', str(path)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=self.cwd, env=self.env, bufsize=0)
                self._threads = [Thread(target=fn, daemon=True) for fn in (self._read_stdout, self._read_stderr, self._write_stdin)]
                for thread in self._threads:
                    thread.start()
                # Reader subscription is active before any prompt can race its events.
                response = self._response(self._send('prompt', message=prompt), until)
                accepted = response.get('success') is True
                disposition = response.get('data', {}).get('disposition')
                if not accepted:
                    reason = 'prompt_rejected'
                elif disposition == 'handled':
                    reason = 'handled_without_run'
                elif disposition != 'started':
                    reason = 'unexpected_prompt_disposition'
                else:
                    while not self._settled:
                        self._next(until)
                    reason = 'settled'
        except (Empty, EOFError, ValueError, OSError, Full):
            reason = 'deadline_or_protocol_failure'
        finally:
            # Transcript remains open during cancellation/drain, so reopen append after the block.
            try:
                try:
                    self._transcript = transcript.open('a', encoding='utf-8', newline='\n')
                except OSError:
                    self._transcript = None
                    self._transcript_error = True
                stopped = self.stop_phase(session=session, reason=reason)
            finally:
                try:
                    if self._transcript is not None:
                        self._transcript.close()
                finally:
                    self._lock.release()
        exited = stopped.evidence['process_exited']
        artifacts = self._valid_session(path, initial)
        protocol_failed = self._reader_error or self._writer_error
        io_failed = protocol_failed or self._transcript_error
        status = 'failed' if self._errors or stopped.evidence.get('returncode') not in (0, None) else 'pending'
        if (accepted and disposition == 'started' and self._settled and not self._aborted
                and not self._errors and not self._unexpected_tool and exited
                and stopped.evidence.get('returncode') == 0 and artifacts and not io_failed
                and stopped.evidence['clear_abort_acknowledged'] and self._text.strip()):
            status = 'done'
        return Receipt(operation, status, {'engine': 'pi', 'administrator_role': context.role,
            'experiment_id': context.experiment_id, 'plan_id': context.plan_id,
            'budget_scope_id': context.budget_scope_id, 'config_hash': self.config_hash,
            'accepted': accepted, 'disposition': disposition, 'settled': self._settled,
            'aborted': self._aborted, 'errors': self._errors, 'protocol_failed': protocol_failed,
            'transcript_failed': self._transcript_error, 'session_valid': artifacts, 'unexpected_tool': self._unexpected_tool,
            'reason': reason, 'text': self._redact(self._text), 'transcript_path': str(transcript),
            'session_path': str(path), 'session_sha256': hashlib.sha256(path.read_bytes()).hexdigest() if artifacts else None,
            'stderr_bytes': self._stderr_bytes,
            'stderr': self._redact(self._stderr_prefix.decode('utf-8', errors='replace')), **stopped.evidence})

    def stop_phase(self, *, session: EngineSession, reason: str) -> Receipt:
        if session != self._session:
            raise ValueError('foreign session stop')
        process = self._process
        clean = False
        if process is not None:
            try:
                until = time.monotonic() + 1
                cleared = self._response(self._send('clear_queue'), until)
                if cleared.get('success') is not True:
                    raise ValueError('queue clear rejected')
                aborted = self._response(self._send('abort'), until)
                clean = aborted.get('success') is True
            except Exception:
                # Deadline/EOF remains pending; every ordinary protocol error still exits ownership.
                self._reader_error = True
            finally:
                try:
                    self._writes.put_nowait(None)
                except Full:
                    self._writer_error = True
                try:
                    process.stdin.close()
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1)
                for thread in self._threads:
                    thread.join(timeout=0.2)
                try:
                    while True:
                        self._next(time.monotonic() + 0.05)
                except (Empty, EOFError):
                    pass
                except Exception:
                    self._reader_error = True
        return Receipt(self._operation, 'done' if clean and process is not None and process.poll() is not None else 'uncertain',
            {'stop_reason': reason, 'clear_abort_acknowledged': clean,
             'process_exited': process is not None and process.poll() is not None,
             'owned_pid': process.pid if process is not None else None,
             'returncode': process.returncode if process is not None else None})
