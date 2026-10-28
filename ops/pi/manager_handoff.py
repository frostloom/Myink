"""Reviewed reproduction to original finite manager inbox; no paid calls here."""
from pathlib import Path
import re
from threading import Event
from .audit import AuditStore,_path,_plain,digest,require
from .development_inputs import file_hash,ledger_snapshot,read_json,prepare_template
from .review_lease import _read,_directory,_new,_sync,load_policy,inspect_review,create as create_lease
from .review_dossier import semantic_hash
from .selection_review_issuer import issue as issue_selection
from .cycle_bundle import freeze as freeze_bundle,seal as seal_bundle
from .task_package import _publish_new
from .audit import encoded
from .manager import _package
from .local_cycle import _disjoint

FIELDS=set('schema mode root issuer_policy_path issuer_policy_sha256 review_config_path review_config_sha256 reproduction_receipt_path reproduction_receipt_sha256 cycle_id selection_run_id task_id manager_state inbox deadline_seconds review_wait_seconds priority'.split())
RECEIPT=set('schema status eligible_for_review model_requests template_path dossier_path baseline_outcome_path'.split())
BASE=Path('/home/ubuntu/myink-pi-managed')


def publish(request_path,request_sha256,*,clock=None,cancel=None):
    cancel=cancel if cancel is not None else Event();require(not cancel.is_set(),'handoff cancelled before claim')
    request,pin=_read(request_path,65536);require(pin==request_sha256 and isinstance(request,dict) and set(request)==FIELDS and request['schema']=='pi-reviewed-manager-handoff-v1','strict reviewed handoff request required');q=request
    require(q['mode'] in ('ACTUAL','SIMULATED'))
    if q['mode']=='ACTUAL':require(clock is None and _path(q['manager_state'])==BASE/'state/actual-manager.sqlite' and _path(q['inbox'])==BASE/'inbox','original actual manager and inbox required')
    for key in ('cycle_id','selection_run_id','task_id'):require(isinstance(q[key],str) and re.fullmatch('[a-z0-9-]{1,60}',q[key]),'bounded fresh handoff identity required')
    require(type(q['deadline_seconds']) is int and 1<=q['deadline_seconds']<=2100 and type(q['review_wait_seconds']) is int and 1<=q['review_wait_seconds']<=600 and type(q['priority']) is int and 0<=q['priority']<=9,'bounded handoff limits required')
    p,now,c,tc,material,fee,pins=inspect_review(q['issuer_policy_path'],q['issuer_policy_sha256'],q['review_config_path'],q['review_config_sha256'],clock=clock)
    require(p['mode']==q['mode'],'handoff authority mode drift');receipt,rpin=_read(q['reproduction_receipt_path'])
    require(rpin==q['reproduction_receipt_sha256'] and isinstance(receipt,dict) and set(receipt)==RECEIPT and receipt['schema']=='pi-reproduction-result-v1' and receipt['status']=='reproduced' and receipt['eligible_for_review'] is True and type(receipt['model_requests']) is int and receipt['model_requests']==0,'completed isolated reproduction required')
    require(all(receipt[a]==c[b] for a,b in (('template_path','template_path'),('dossier_path','dossier_path'),('baseline_outcome_path','outcome_path'))),'reviewed reproduction receipt drift')
    root=_path(q['root']);inbox=_directory(q['inbox']);state=_path(q['manager_state']);_plain(state)
    require(not root.exists() and root.parent.is_dir() and root.parent.stat().st_mode&0o777==0o700,'fresh private handoff claim required')
    require(_path(p['prepared_parent'])==root/'bundle/cycle-output/prepared','original cycle prepared root must match host issuer policy')
    protected=[_path(request_path),_path(q['issuer_policy_path']),_path(q['review_config_path']),_path(q['reproduction_receipt_path']),_path(c['root']),*[_path(c[k]) for k in c if k.endswith('_path')],*[_path(tc[k]) for k in tc if k.endswith('_path')],_path(tc['root']),_path(p['root']),_path(c['ledger_path']).parent,state.parent]
    protected.extend([_path(c['audit_path']).parent,_path(c['export_root']),*[_path(c['audit_path']+suffix) for suffix in ('-journal','-wal','-shm')]])
    _disjoint(root,inbox)
    for out in (root,inbox):
        for item in protected:_disjoint(out,item)
    require(not cancel.is_set() and file_hash(request_path)==request_sha256,'handoff request revoked or cancelled')
    root.mkdir(mode=0o700);_sync(root.parent);_new(root/'intent.json',dict(schema='pi-manager-handoff-intent-v1',request_sha256=request_sha256,reproduction_receipt_sha256=rpin,review_config_sha256=q['review_config_sha256']))
    lease=create_lease(q['issuer_policy_path'],q['issuer_policy_sha256'],q['review_config_path'],q['review_config_sha256'],clock=clock)
    refreshed=dict(tc,ledger_sha256=fee['sha256']);require(semantic_hash(refreshed)==material['dossier']['semantic_sha256'],'fee-only template refresh changed semantics')
    target=root/'development-template.json';_new(target,refreshed);prepare_template(target)
    bundle_request=dict(schema='pi-cycle-bundle-v1',root=str(root/'bundle'),cycle_id=q['cycle_id'],selection_run_id=q['selection_run_id'],template_path=str(target),template_sha256=file_hash(target),outcome_path=c['outcome_path'],outcome_sha256=c['outcome_sha256'],deadline_seconds=q['deadline_seconds'],review_wait_seconds=q['review_wait_seconds']);_new(root/'bundle-request.json',bundle_request)
    frozen=freeze_bundle(root/'bundle-request.json');bundle=Path(frozen['bundle_path']);selection_config=bundle.parent/'selection-config.json'
    issue_selection(lease['lease_path'],lease['lease_sha256'],selection_config,file_hash(selection_config),clock=clock)
    sealed=seal_bundle(bundle);require(sealed['ready'] is True and not sealed['staging_retained'],'cycle publication uncertain');cycle=Path(sealed['cycle_path']);cycle_sha=file_hash(cycle)
    _,resources=_package(state,_path(c['ledger_path']),cycle,cycle_sha)
    for item in resources['inputs']+resources['outputs']:_disjoint(inbox,Path(item))
    require(not cancel.is_set() and file_hash(request_path)==request_sha256 and file_hash(q['reproduction_receipt_path'])==rpin and ledger_snapshot(c['ledger_path'])==fee,'handoff changed before admission')
    load_policy(q['issuer_policy_path'],q['issuer_policy_sha256'],clock)
    require(not cancel.is_set(),'handoff cancelled before admission')
    manifest=dict(schema='pi-manager-admission-v1',task_id=q['task_id'],request_path=str(cycle),request_sha256=cycle_sha,priority=q['priority'],mode=q['mode']);destination=inbox/(q['task_id']+'.task.json')
    retained=_publish_new(destination,encoded(manifest)+b'\n');_sync(inbox);require(not retained,'manager admission staging uncertain')
    result=dict(schema='pi-reviewed-manager-handoff-result-v1',status='published',model_requests=0,request_sha256=request_sha256,manifest_sha256=file_hash(destination),manifest_path=str(destination),cycle_sha256=cycle_sha,cycle_path=str(cycle),bundle_path=str(bundle),template_path=str(target),lease_path=lease['lease_path'],lease_sha256=lease['lease_sha256'])
    domain='real_provider_fixed_input' if q['mode']=='ACTUAL' else 'synthetic'
    event=dict(kind='plan',status='planned',run_id=q['task_id'],occurred_at=now.isoformat(),summary='Reviewed frozen regression admitted to original manager; selection and development remain separate bounded operations.',details=dict(reference='manager.reviewed_handoff.v1',decision='admitted',next_action='original_manager_selection'),version=dict(policy_sha256=q['issuer_policy_sha256']),changes=[],evidence=[dict(kind=k,sha256=h,verified=True,evidence_domain=domain) for k,h in (('completed_reproduction',rpin),('independent_review_config',q['review_config_sha256']),('sealed_cycle',cycle_sha))],followups=[],mode=q['mode'],evidence_domain=domain)
    audit=AuditStore(c['audit_path']);audit.append(q['task_id']+':handoff',event);audit.export(c['export_root']);_new(root/'receipt.json',result);return result
