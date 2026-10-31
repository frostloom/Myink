"""Bounded audit-derived context. No freeform model text or execution authority."""
from datetime import datetime,timedelta,timezone
from .audit import digest,encoded,hash_value,require,utc

SCOPE=set('evidence_domain source_commit candidate_sha256 observer_controller_sha256 observer_policy_sha256 cohort_sha256'.split())
DOMAINS={'online_business','real_provider_fixed_input','offline','synthetic','unknown'}
COUNTS=set('observed_samples minimum_samples test_total test_failures test_errors test_skipped model_requests tool_calls known_cost_microyuan'.split())


def build_memory(export_root,scope,*,now=None,limit=8,max_bytes=8192):
    from importlib.util import spec_from_file_location,module_from_spec
    from pathlib import Path
    require(isinstance(scope,dict) and set(scope)==SCOPE and scope['evidence_domain'] in DOMAINS,'strict memory scope required')
    for key in SCOPE-{'evidence_domain'}:require(scope[key] is None or hash_value(scope[key],40 if key=='source_commit' else 64),'memory scope digest required')
    require(type(limit) is int and 1<=limit<=8 and type(max_bytes) is int and 512<=max_bytes<=8192,'bounded memory required')
    now=utc(now or datetime.now(timezone.utc));cutoff=now-timedelta(hours=24)
    # Load exactly the reader covered by the controller's closed manifest.
    path=Path(__file__).parents[2]/'src/myink/pi_audit.py'
    from .audit import _path,_plain
    _plain(_path(path));require(path.stat().st_size<=1048576,'bounded frozen audit reader required')
    spec=spec_from_file_location('pi_diagnostic_audit_reader',path);module=module_from_spec(spec);spec.loader.exec_module(module);AuditReader=module.AuditReader
    reader=AuditReader(export_root);facts=[]
    for event in reader._events():
        if event['mode']!='ACTUAL' or event['evidence_domain']!=scope['evidence_domain'] or event['occurred_at'] is None:continue
        at=utc(datetime.fromisoformat(event['occurred_at']))
        if not cutoff<=at<=now:continue
        if event['kind'] not in ('observation','analysis','test','development','memory'):continue
        version=event['version']
        if version['source_commit']!=scope['source_commit'] or version['candidate_sha256']!=scope['candidate_sha256']:continue
        binding=any(p['kind']=='diagnostic_source_binding' and p['verified'] and p['evidence_domain']==scope['evidence_domain'] and p['sha256']==digest(scope) for p in event['evidence'])
        if not binding:
            if event['kind']!='observation' or version['controller_sha256']!=scope['observer_controller_sha256'] or version['policy_sha256']!=scope['observer_policy_sha256']:continue
            if scope['cohort_sha256'] is None or not any(p['kind']=='observation_cohort' and p['verified'] and p['evidence_domain']==scope['evidence_domain'] and p['sha256']==scope['cohort_sha256'] for p in event['evidence']):continue
        counts={k:event['details'][k] for k in sorted(COUNTS) if k in event['details']}
        fact=dict(event_sha256=event['event_sha256'],run_id=event['run_id'],kind=event['kind'],status=event['status'],occurred_at=event['occurred_at'],evidence_domain=event['evidence_domain'],counts=counts,diagnostic_only=True)
        facts.append((at,event['sequence'],fact));facts.sort(key=lambda x:(x[0],x[1]),reverse=True);del facts[limit:]
    value=dict(schema='pi-bounded-memory-v1',authority='context_only',scope=dict(scope),diagnostic_only=True,unique_samples=None,generated_at=now.isoformat(),expires_at=(now+timedelta(hours=24)).isoformat(),facts=[f[2] for f in facts])
    while len(encoded(value))>max_bytes and value['facts']:value['facts'].pop()
    require(len(encoded(value))<=max_bytes,'memory metadata exceeds byte bound')
    return value
