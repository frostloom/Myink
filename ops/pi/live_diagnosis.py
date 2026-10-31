"""Verified bounded observations for diagnosis; no approval, model or fee action."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import math
from .audit import _path,digest,hash_value,name,require,strict_json,utc
from .live_observer import _load,_cached,_read,_private_directory,_controller,MAX_SNAPSHOT

COUNTS=set('planned completed failed paused queued human_waiting status_unknown complete_tasks tail_samples paired_groups'.split())
FIELDS=set('id metric evidence_domain identity window measurements paired_group_ids config_hash prompt_hash rubric_hash data_hash schema_id model_ids version_range confounders pricing_id pricing_range pricing_availability availability task_type_range'.split())|COUNTS
METRICS=set('cost latency node_time quality queue_time human_wait errors latency_p95'.split())
VERSION_FIELDS=set('deployment_id generation owner schema_id config_id prompt_id rubric_id data_id image_ids commit_sha'.split())


def _snapshot(value):
    require(isinstance(value,dict) and FIELDS<=set(value)<=FIELDS|{'cohort_sha256'},'strict diagnostic snapshot required')
    require(all(type(value[k]) is int and 0<=value[k]<=1000 for k in COUNTS),'bounded diagnostic counts required')
    require(value['complete_tasks']==value['completed'] and value['completed']<=value['planned'],'inconsistent diagnostic counts')
    if 'cohort_sha256' in value:require(value['cohort_sha256'] is None or hash_value(value['cohort_sha256']))
    require(value['availability'] in ('measured','unknown') and value['pricing_availability'] in ('measured','unknown'))
    require(isinstance(value['measurements'],dict) and set(value['measurements'])==METRICS,'fixed diagnostic metrics required')
    for metric in value['measurements'].values():
        require(isinstance(metric,dict) and set(metric)=={'value','availability','samples','direction'})
        number=metric['value'];require(number is None or type(number) in (int,float) and math.isfinite(number) and number>=0)
        require(metric['availability'] in ('measured','unknown') and metric['direction'] in ('lower','higher') and type(metric['samples']) is int and 0<=metric['samples']<=1000)
        require(metric['availability']!='measured' or number is not None and metric['samples']>0)
    versions=value['version_range'];require(isinstance(versions,dict) and set(versions)==VERSION_FIELDS)
    for values in versions.values():require(isinstance(values,list) and len(values)<=1000 and all(type(v) in (str,int) and (not isinstance(v,str) or len(v)<=2048) for v in values))
    for key in ('confounders','model_ids','pricing_range','task_type_range','paired_group_ids'):
        require(isinstance(value[key],list) and len(value[key])<=1000 and all(isinstance(v,str) and 0<len(v)<=256 for v in value[key]))
    for key in ('config_hash','prompt_hash','rubric_hash','data_hash','schema_id','pricing_id'):
        require(value[key] is None or isinstance(value[key],str) and 0<len(value[key])<=256,'scalar metric provenance required')
    require(value['metric'] is None or value['metric'] in METRICS)
    require(isinstance(value['identity'],dict) and isinstance(value['window'],dict) and set(value['window'])=={'start','end'})


def inspect_observation(observer_config_path,expected_config_sha256,receipt_path,*,expected_controller_sha256=None,clock=None):
    config,c,raw_sha,base,audit,export=_load(observer_config_path)
    require(hash_value(expected_config_sha256) and raw_sha==expected_config_sha256,'observer config changed')
    if c['mode']=='ACTUAL':require(expected_controller_sha256 is not None,'ACTUAL observer controller pin required')
    controller=expected_controller_sha256 or _controller();require(hash_value(controller))
    receipt_path=_path(receipt_path);root=_private_directory(receipt_path.parent)
    require(receipt_path.name=='receipt.json' and root.parent==base,'fixed completed observer receipt required')
    receipt=_cached(root,root.name,digest(c),controller)
    require(receipt['mode']==c['mode'] and receipt['status'] in ('passed','insufficient_evidence') and receipt['export_published'] and receipt['snapshot_sha256'] is not None,'completed observation required')
    snapshot=strict_json(_read(root/'metrics.json',MAX_SNAPSHOT));_snapshot(snapshot)
    require(snapshot['id']==receipt['run_id'] and snapshot['window']==receipt['window'] and snapshot['availability']==receipt['availability']
        and snapshot['complete_tasks']==receipt['observed_samples'] and snapshot['confounders']==receipt['confounders'],'observer snapshot/receipt mismatch')
    require(snapshot['evidence_domain']==('online' if c['mode']=='ACTUAL' else 'synthetic')
        and receipt['evidence_domain']==('online_business' if c['mode']=='ACTUAL' else 'synthetic')
        and type(receipt['minimum_samples']) is int and receipt['minimum_samples']==c['minimum_samples'],'observation domain/threshold mismatch')
    now=utc((clock or (lambda:datetime.now(timezone.utc)))());start=utc(datetime.fromisoformat(snapshot['window']['start']));end=utc(datetime.fromisoformat(snapshot['window']['end']))
    require(start<end<=now and now-end<=timedelta(minutes=45),'stale or future observation')
    versions=snapshot['version_range'];commit=versions['commit_sha'];source=commit[0] if len(commit)==1 and hash_value(commit[0],40) else None
    gaps=[]
    if snapshot['complete_tasks']<c['minimum_samples']:gaps.append('insufficient_samples')
    if snapshot['availability']!='measured':gaps.append('unmeasured_metrics')
    if snapshot['confounders']:gaps.append('confounded_evidence')
    if len(snapshot['task_type_range'])!=1:gaps.append('task_type_not_comparable')
    if source is None or any(len(v)!=1 for k,v in versions.items() if k!='commit_sha'):gaps.append('unknown_identity')
    if snapshot['tail_samples']<100:gaps.append('insufficient_tail_samples')
    if snapshot.get('cohort_sha256') is None:gaps.append('unknown_cohort')
    facts=dict(counts={k:snapshot[k] for k in sorted(COUNTS)},measurements=snapshot['measurements'],version_range=versions,availability=snapshot['availability'],confounders=snapshot['confounders'],task_types=snapshot['task_type_range'],model_ids=snapshot['model_ids'],pricing_id=snapshot['pricing_id'],pricing_range=snapshot['pricing_range'],pricing_availability=snapshot['pricing_availability'],cohort_sha256=snapshot.get('cohort_sha256'),minimum_samples=c['minimum_samples'])
    fingerprint=digest(dict(source=digest(c['source']),mode=c['mode'],facts=facts))
    return dict(schema='pi-live-evidence-v1',authority='observation_only',mode=c['mode'],evidence_domain=receipt['evidence_domain'],observation_run_id=receipt['run_id'],receipt_sha256=receipt['receipt_sha256'],snapshot_sha256=receipt['snapshot_sha256'],evidence_fingerprint=fingerprint,source_binding_sha256=digest(c['source']),observer_controller_sha256=controller,observer_policy_sha256=digest(c),cohort_sha256=snapshot.get('cohort_sha256'),source_commit=source,candidate_sha256=None,window=snapshot['window'],expires_at=(end+timedelta(minutes=45)).isoformat(),observed_samples=snapshot['complete_tasks'],minimum_samples=c['minimum_samples'],availability=snapshot['availability'],gaps=sorted(gaps),facts=facts,repair_eligible=False,requires=['source_bound_reproducer','independent_review'],model_requests=0)
