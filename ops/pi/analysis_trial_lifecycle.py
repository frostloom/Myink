"""v2 host orchestration; cancellation is not evidence of provider refunds."""
from contextlib import nullcontext
from pathlib import Path

from .analysis_execution import _hash
from .analysis_lifecycle import signal_scope
from .analysis_run import AnalysisRun
from .analysis_trial_result import summarize_trial
from .container_probe import LABEL, _write
from .ledger import Ledger, LedgerBlocked


def _bound_host(host, lifecycle):
    call = host._call
    host.lifecycle = lifecycle
    def bounded(*args, **kwargs):
        remaining = lifecycle.cleanup_remaining() if lifecycle._cleanup_end is not None else lifecycle.check()
        kwargs['timeout'] = min(kwargs.get('timeout', 15), remaining)
        return call(*args, **kwargs)
    host._call = bounded


def _settled(run):
    with run.ledger.transaction() as db:
        for row in db.execute("SELECT * FROM operations WHERE kind='model-attempt'"):
            payload = Ledger._decode(row['payload'])
            if payload.get('analysis_run_id') == run._identity['run_id'] and row['status'] == 'pending':
                return False
    return True


def execute_trial(config, policy, credentials, inputs, slots, provenance, host, result, life, *, signals=False):
    from . import analysis_launcher as launcher
    ledger = Ledger(Path(config['ledger_path']), existing=True)
    run = AnalysisRun.create(ledger, config['run_id'], slots,
        source_sha256=_hash(provenance), config_sha256=_hash(config))
    run.bind_budget(policy, cap_microyuan=config['cap_microyuan'], deadline=config['deadline'])
    root = Path(config['root']); root.mkdir(mode=0o700)
    _bound_host(host, life)
    result.update(status='blocked', operation_id=host.operation_id, failure_class=None)
    progress = dict(slot_index=0, stage='lifecycle_start', reason='stage_failed', response_bytes=0, http_status=None)
    context = signal_scope(life) if signals else nullcontext()
    with context:
        try:
            _write(root/'lifecycle-private.json', dict(run_id=config['run_id'], config_sha256=_hash(config),
                provenance_sha256=_hash(provenance), operation_id=host.operation_id,
                execution_deadline=config['deadline'], time_policy=config['time_policy']))
            with launcher._provider(policy, credentials) as send:
                def transport(body, timeout):
                    life.check()
                    return send(body, min(timeout, life.check()))
                for index, slot in enumerate(slots):
                    progress = dict(slot_index=index, stage='slot_window', reason='stage_failed', response_bytes=0, http_status=None)
                    life.check()
                    if life.remaining() <= 120:
                        life.stop('insufficient_slot_window'); life.check()
                    row, cid = launcher._slot(run, policy, config, inputs, slot, index, host,
                        transport, root, provenance, progress, lifecycle=life)
                    progress['stage'] = 'session_unique'
                    if any(previous['session_id'] == row['session_id'] for previous in result['cases']):
                        raise ValueError('duplicate session')
                    result['cases'].append(row)
                    progress['stage'] = 'container_cleanup'
                    cleaned = host.cleanup(cid); result['cleanup'].append(cleaned)
                    if cleaned['exit_code'] != 0:
                        raise ValueError('container exit failed')
                    life.check()
                    progress['stage'] = 'slot_finish'
                    run.finish(index, status='done' if row['contract_valid'] else 'failed', check=life.check)
                result['status'] = 'completed'
        except BaseException as exc:
            life.stop('interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else
                'deadline_exceeded' if life.remaining() <= 0 else
                'cleanup_failed' if progress['stage'] in ('container_cleanup', 'slot_cleanup') else 'execution_failed')
            result.update(status='blocked', failure_class=type(exc).__name__, failure_detail=dict(progress))
            # Existing claim remains UNCERTAIN without manufacturing a final result.
            if not isinstance(exc, (Exception, KeyboardInterrupt)):
                raise
        finally:
            life.begin_cleanup()
            cleanup_ok = True
            deferred = []
            def cleanup_error(exc):
                nonlocal cleanup_ok
                cleanup_ok = False
                life.stop('interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'cleanup_failed')
                if result['failure_detail'] is None:
                    result.update(failure_class=type(exc).__name__,
                        failure_detail=dict(progress, stage='container_reconcile', reason='stage_failed'))
                if not isinstance(exc, (Exception, KeyboardInterrupt)):
                    deferred.append(exc)
            try:
                host.reconcile()
            except BaseException as exc:
                cleanup_error(exc)
            for cid in list(host.owned):
                try:
                    result['cleanup'].append(host.cleanup(cid))
                except BaseException as exc:
                    cleanup_error(exc)
                    result['cleanup'].append(dict(container_id=cid, removed=False, failure_class=type(exc).__name__))
            for name, mode in host.pending.items():
                result['cleanup'].append(dict(name=name, mode=mode, removed=False, operation_id=host.operation_id))
            try:
                host._daemon()
                found = host._call('ps', '-a', '--no-trunc', '--filter', 'label='+LABEL+'='+host.operation_id,
                    '--format', '{{.ID}}').stdout.split()
                cleanup_ok = cleanup_ok and not found and not host.pending and not host.owned
            except BaseException as exc:
                cleanup_error(exc)
            try:
                result['cleanup_complete'] = cleanup_ok and _settled(run)
                if not result['cleanup_complete']:
                    life.stop('cleanup_failed'); result['status'] = 'blocked'
                result['stop_reason'] = life.reason
                if life.reason is not None: result['status'] = 'blocked'
                result['slots'] = run.snapshot()
                result['summary'] = summarize_trial(slots, result['slots'])
                _write(root/'receipt.json', result)
            except Exception:
                raise LedgerBlocked('analysis final receipt unavailable') from None
            if deferred:
                raise deferred[0]
    return result
