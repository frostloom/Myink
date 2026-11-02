"""Publish original nightly skip/recovery facts before the final Gate transition."""
from pathlib import Path
from .audit import AuditStore,utc
from .nightly_gate import BASE


def publish(gate,cycle,root,reason,*,recovered=False,model_requests=0):
    root=Path(root)
    if gate.mode=='ACTUAL':
        audit=BASE/'audit/state/events.sqlite';export=BASE/'audit/export'
    else:
        parent=root/'outcome-audit';parent.mkdir(mode=0o700,exist_ok=True)
        audit=parent/'events.sqlite';export=parent/'export'
    event=dict(kind='deployment',status='no_release',run_id=cycle,occurred_at=utc(gate.clock()).isoformat(),summary='No writing data: skipped analysis, model calls and candidate development.' if reason=='no_writing_data' else 'Operator reconciled a failed preparation without replay or publication.' if recovered else 'Night finished without a candidate or publication.',details=dict(reference='nightly.no_release.v1',decision='skip',reason=reason,next_action='wait_for_new_writing_data' if reason=='no_writing_data' else 'next_nightly_check',model_requests=model_requests,known_cost_microyuan=0 if model_requests==0 else None),version={},changes=[],evidence=[],followups=[],mode=gate.mode,evidence_domain='online_business' if gate.mode=='ACTUAL' else 'synthetic')
    from .product_commands import _write
    from .audit import _plain,require,strict_json
    path=root/('recovery-audit.json' if recovered else 'no-release-audit.json')
    if path.exists():
        _plain(path);saved=strict_json(path.read_bytes())
        require(saved['kind']=='deployment' and saved['status']=='no_release' and saved['run_id']==cycle and saved['mode']==gate.mode and saved['details']==event['details'],'original no-release audit drift')
        event=saved
    else:_write(path,event)
    store=AuditStore(audit);store.append(cycle+':'+('recovery' if recovered else 'no-release'),event);store.export(export)
    if gate.mode=='ACTUAL':
        from .nightly_binding import _audit_outputs,_ordinary
        for path in _audit_outputs(dict(audit_path=str(audit),export_root=str(export))):_ordinary(path,gate.mode)
