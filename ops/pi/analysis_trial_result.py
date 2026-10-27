"""Host-only trial verdicts. A rejected output is not failed execution evidence."""
from hashlib import sha256
import re

from .analysis_execution import _hash
from .analysis_trial import score_contract_output
from .container_runtime import strict_json
from .runtime_platform import verify_runtime
from .writing_analysis import parse_writing_analysis


def verify_trial_result(frame, slot, view, report, *, expected_machine='aarch64'):
    """Return a body-free verdict only after independent execution checks.

    Invalid output may be FAILED by the caller only after its separate known
    billing, session uniqueness, HTTP and container cleanup checks also pass.
    Worker flags never turn an unverifiable session into a known failure.
    """
    try:
        return _verify(frame, slot, view, expected_machine)
    except (KeyError, TypeError, AttributeError, RecursionError) as exc:
        raise ValueError('invalid trial execution evidence') from exc


def _verify(frame, slot, view, expected_machine):
    result = frame['result']; evidence = result['evidence']
    if (result.get('engine_status') != 'done'
            or any(result.get(k) != slot[k] for k in (
                'slot_id', 'request_sha256', 'system_sha256', 'prompt_sha256', 'view_sha256', 'report_sha256'))
            or any(evidence.get(k) is not True for k in (
                'session_valid', 'process_exited', 'clear_abort_acknowledged', 'accepted', 'settled'))
            or any(evidence.get(k) is not False for k in (
                'unexpected_tool', 'aborted', 'errors', 'protocol_failed', 'transcript_failed'))
            or evidence.get('disposition') != 'started'
            or not isinstance(evidence.get('config_hash'), str)
            or not re.fullmatch('[0-9a-f]{64}', evidence['config_hash'])
            or type(evidence.get('returncode')) is not int or evidence['returncode'] != 0
            or evidence.get('verified_tool_calls') != [] or evidence.get('pending_tool_calls') != []):
        raise ValueError('invalid trial engine evidence')
    raw = frame['session'].encode('utf-8')
    if (not 0 < len(raw) <= 65536 or not raw.endswith(b'\n')
            or sha256(raw).hexdigest() != evidence.get('session_sha256')):
        raise ValueError('session fingerprint mismatch')
    rows = [strict_json(line) for line in raw.splitlines()]
    if (any(not isinstance(row, dict) for row in rows)
            or rows[0].get('type') != 'session' or rows[0].get('cwd') != '/work/candidate'
            or not isinstance(rows[0].get('id'), str) or not 0 < len(rows[0]['id']) <= 256
            or any(row.get('type') == 'session' for row in rows[1:])):
        raise ValueError('fresh session identity required')
    assistants = []
    for row in rows:
        message = row.get('message', {})
        if message.get('role') == 'toolResult':
            raise ValueError('tools forbidden')
        if message.get('role') == 'assistant':
            if row.get('type') != 'message' or message.get('errorMessage'):
                raise ValueError('invalid assistant session record')
            content = message.get('content')
            if (not isinstance(content, list) or not content
                    or any(not isinstance(b, dict) or b.get('type') != 'text'
                           or not isinstance(b.get('text'), str) for b in content)):
                raise ValueError('pure text required')
            assistants.append(message)
    if len(assistants) != 1 or assistants[0].get('stopReason') != 'stop':
        raise ValueError('one complete assistant output required')
    text = ''.join(b['text'] for b in assistants[0]['content'])
    if not text.strip() or evidence.get('text') != text:
        raise ValueError('output/session mismatch')
    runtime = frame['runtime']
    verify_runtime(runtime, expected_machine)
    analysis = None
    failure = 'output_invalid'
    worker_failure = 'engine_or_output_invalid'
    try:
        analysis = parse_writing_analysis(text, view)
    except ValueError:
        pass  # Original bytes remain untouched in the private frame/session.
    if analysis is not None:
        try:
            score_contract_output(analysis, view, slot['domain'])
            failure = worker_failure = None
        except ValueError:
            failure = worker_failure = 'target_scope_invalid'
    valid = failure is None
    if (result.get('contract_valid') is not valid or result.get('failure') != worker_failure
            or _hash(result.get('analysis')) != _hash(analysis)):
        raise ValueError('worker verdict disagrees with host')
    return dict(slot_id=slot['slot_id'], contract_valid=valid, failure=failure,
        session_sha256=evidence['session_sha256'], session_id=rows[0]['id'], process_exited=True,
        returncode=0, request_sha256=slot['request_sha256'], runtime=runtime)


def summarize_trial(slots, states):
    """Keep full denominators; verdicts in cases never override durable outcomes."""
    def counts(indices):
        rows = [states[i] for i in indices]
        return dict(planned_slots=len(rows), **{
            status.lower(): sum(row['status'] == status for row in rows)
            for status in ('DONE', 'FAILED', 'UNCERTAIN', 'BLOCKED', 'NOT_RUN')})
    return counts(range(30)) | dict(
        by_arm={arm: counts([i for i, slot in enumerate(slots) if slot['arm'] == arm])
                for arm in ('baseline', 'candidate')},
        by_domain={domain: counts([i for i, slot in enumerate(slots) if slot['domain'] == domain])
                   for domain in dict.fromkeys(slot['domain'] for slot in slots)})
