"""Bind a stopped, authenticated selection and its actual paid UUID to a lease."""
from pathlib import Path
import fcntl
from .audit import AuditStore,_path,_plain,digest,require,strict_json,hash_value
from .development_inputs import authorization_hash,file_hash,read_json
from .review_issuer import _snapshot
from .review_lease import _read,_directory,_sync,_new,inspect_review
from .review_dossier import semantic_hash
from .diagnosis_launcher import _unknown
from .maintenance_handoff import _selection
from . import selection_launcher as selection

ARTIFACTS=('manifest-private.json','initial-private.json','worker-frame-private.json','request-private.json','verification.json','result.json','ledger-before-private.json','ledger-after-private.json')
BASE=set('schema policy_path policy_sha256 review_config_path review_config_sha256 artifact_pins scope'.split())


def inspect(parent_path,parent_sha256,config_path,config_sha256,*,clock=None,require_task=True):
    parent,pin=_read(parent_path);require(pin==parent_sha256 and set(parent)==BASE and parent['schema']=='pi-review-lease-record-v1','original authenticated review lease required')
    p,now,c,tc,material,fee,pins=inspect_review(parent['policy_path'],parent['policy_sha256'],parent['review_config_path'],parent['review_config_sha256'],clock=clock,allow_fee_append=True)
    original=parent['scope'];root=_directory(_path(parent_path).parent)
    require(root.parent==_path(p['root']) and root.name=='lease-'+digest(dict(review_config_sha256=parent['review_config_sha256'],semantic_sha256=original['semantic_sha256'])) and _path(parent_path)==root/'lease.json','original lease custody drift')
    require(parent['artifact_pins']==pins and original['allowed_fee_operation_ids']==[] and original['semantic_sha256']==semantic_hash(tc) and original['fee_checkpoint']==_read(Path(c['root'])/'ledger-after-private.json')[0],'original unbound review scope drift')
    cp=_path(config_path);require(cp.is_relative_to(_path(p['review_config_parent'])) and file_hash(cp)==config_sha256,'selection config outside host custody')
    sc,policy,tasks,current,provenance=selection.inspect_completed(cp,expected_current_fee_sha256=fee['sha256'])
    require(current==fee and all(sc[k]==c[k] for k in ('runtime_path','runtime_sha256','ledger_path','policy_path','policy_sha256','credential_path','credential_sha256','docker','endpoint','daemon_id','image_id')) and sc['source_path']==tc['source_path'] and sc['source_sha256']==tc['source_sha256'],'selection host/source identity drift')
    require(digest(tasks)==digest(read_json(c['outcome_path'])['catalog']) and sc['ledger_sha256']==original['fee_checkpoint']['sha256'],'selection did not use exact reviewed catalog/checkpoint')
    out=_directory(sc['root']);values={};artifact_pins={}
    for name in ARTIFACTS:values[name],artifact_pins[name]=_read(out/name)
    manifest=values['manifest-private.json'];context=manifest.get('context_hash');require(hash_value(context) and manifest==dict(config=sc,provenance=provenance,context_hash=context,mode=p['mode']),'selection manifest/mode drift')
    initial=values['initial-private.json'];require(initial['system']==selection.system_for(sc) and initial['prompt']==selection.selection_prompt(sc,tasks,context) and initial['context_hash']==context and initial['config_hash']==digest(dict(authorization=authorization_hash(sc),context=context)) and initial['model']==policy.model and initial['max_tokens']==policy.max_tokens,'selection initial input drift')
    proof=selection.verify_selection(values['worker-frame-private.json'],initial,values['request-private.json']);require(proof==values['verification.json'],'selection verification drift')
    proposal=strict_json(proof['text']);chosen=_selection(proposal,tasks);require(not require_task or chosen is not None,'selection abstained; no development permission')
    result=values['result.json'];require(all(result.get(k) is True for k in ('verified','execution_verified','contract_valid','closed_verified','policy_restored','original_history_unchanged','credential_unchanged')) and result['proposal']==proposal and result['run_id']==sc['run_id'] and result['authorization_sha256']==authorization_hash(sc) and type(result['new_attempts']) is int and result['new_attempts']==1 and type(result['new_unknown']) is int and result['new_unknown']==0 and not any(k.endswith('failure_class') for k in result),'closed verified selection required')
    require(isinstance(result['cleanup'],list) and bool(result['cleanup']) and all(r.get('removed') is True and hash_value(r.get('container_id')) for r in result['cleanup']),'selection cleanup uncertain')
    before=values['ledger-before-private.json'];after=values['ledger-after-private.json'];old=_snapshot(before);new=_snapshot(after)
    require(before==original['fee_checkpoint'] and after==fee and before['limits']==after['limits'] and after['events'][:len(before['events'])]==before['events'] and all(new.get(k)==v for k,v in old.items()) and _unknown(before)==_unknown(after)==set(p['legacy_unknown_ids']),'selection original fee history drift')
    added={k:r for k,r in new.items() if k not in old};posts=result['model_posts'];require(isinstance(posts,list) and len(posts)==1 and posts[0]['status']==200 and len(added)==1 and posts[0]['attempt_id'] in added,'selection paid UUID binding drift')
    operation=posts[0]['attempt_id'];row=added[operation];e=strict_json(row['evidence'] or '{}');require(row['kind']=='model-attempt' and row['status']=='done' and e.get('usage_known') is True and type(e.get('charged_microyuan')) is int and e['charged_microyuan']>=0 and type(result['known_cost_microyuan']) is int and result['known_cost_microyuan']==e['charged_microyuan'],'known selection fee required')
    require(file_hash(parent_path)==parent_sha256 and file_hash(cp)==config_sha256 and all(file_hash(out/name)==pin for name,pin in artifact_pins.items()),'selection changed during binding inspection')
    return parent,p,now,operation,artifact_pins


def bind(parent_path,parent_sha256,config_path,config_sha256,*,clock=None):
    parent,pin=_read(parent_path);require(pin==parent_sha256)
    # The immutable parent pins the canonical ledger; no model or source executes.
    ledger=parent['scope']['fee_checkpoint'];require(isinstance(ledger,dict))
    from .review_lease import load_policy
    p,_=load_policy(parent['policy_path'],parent['policy_sha256'],clock);lockpath=_path(p['ledger_path']).with_suffix('.tools.lock');_plain(lockpath)
    with lockpath.open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        parent,p,now,operation,pins=inspect(parent_path,parent_sha256,config_path,config_sha256,clock=clock)
        root=_path(parent_path).parent/'binding';require(not root.exists(),'selection binding claim exists; no replay');root.mkdir(mode=0o700);_sync(root.parent)
        _new(root/'intent.json',dict(schema='pi-selection-binding-intent-v1',parent_sha256=parent_sha256,selection_config_sha256=config_sha256,selection_attempt_id=operation))
        binding=dict(parent_path=str(parent_path),parent_sha256=parent_sha256,selection_config_path=str(config_path),selection_config_sha256=config_sha256,artifact_pins=pins)
        record=dict(parent,schema='pi-review-lease-record-v2',scope=dict(parent['scope'],allowed_fee_operation_ids=[operation]),binding=binding)
        _new(root/'lease.json',record);lease_sha=file_hash(root/'lease.json')
        sc,sc_pin=_read(config_path);result,result_pin=_read(Path(sc['root'])/'result.json')
        require(sc_pin==config_sha256 and result_pin==pins['result.json'],'selection changed before binding audit')
        review_config=_read(parent['review_config_path'])[0];domain='real_provider_fixed_input' if p['mode']=='ACTUAL' else 'synthetic'
        event=dict(kind='analysis',status='passed',run_id=sc['run_id'],occurred_at=now.isoformat(),summary='Authenticated stopped selection chose the reviewed frozen task; exact development authorization remains a separate gate.',details=dict(reference='host.selection_binding.v1',decision='selected',model_requests=1,known_cost_microyuan=result['known_cost_microyuan'],next_action='exact_development_review'),version=dict(policy_sha256=sc['policy_sha256'],sdk_version='1.1.0'),changes=[],evidence=[dict(kind=kind,sha256=pin,verified=True,evidence_domain=domain) for kind,pin in (('selection_verification',pins['verification.json']),('original_review_lease',parent_sha256),('bound_development_lease',lease_sha))],followups=[],mode=p['mode'],evidence_domain=domain)
        audit=AuditStore(review_config['audit_path']);audit.append('host-selection-binding:'+lease_sha,event);audit.export(review_config['export_root'])
        _new(root/'receipt.json',dict(schema='pi-selection-binding-result-v1',status='bound',lease_sha256=lease_sha,selection_config_sha256=config_sha256,selection_attempt_id=operation,model_requests=0))
        return dict(authority='lease_only',lease_path=str(root/'lease.json'),lease_sha256=lease_sha)


def abstain(parent_path,parent_sha256,config_path,config_sha256,*,clock=None):
    """Attest a verified paid no-task result; never produce a development lease."""
    from .review_lease import load_policy
    parent,pin=_read(parent_path);require(pin==parent_sha256)
    p,_=load_policy(parent['policy_path'],parent['policy_sha256'],clock)
    tools=_path(p['ledger_path']).with_suffix('.tools.lock');_plain(tools)
    with tools.open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        parent,p,now,operation,pins=inspect(parent_path,parent_sha256,config_path,config_sha256,clock=clock,require_task=False)
        sc=_read(config_path)[0];result=_read(Path(sc['root'])/'result.json')[0]
        require(result['proposal']['task_id'] is None,'selected task cannot be recorded as abstention')
        root=_path(parent_path).parent/'abstention';require(not root.exists(),'abstention claim exists; no replay');root.mkdir(mode=0o700);_sync(root.parent)
        _new(root/'intent.json',dict(parent_sha256=parent_sha256,selection_config_sha256=config_sha256))
        c=_read(parent['review_config_path'])[0];domain='real_provider_fixed_input' if p['mode']=='ACTUAL' else 'synthetic'
        event=dict(kind='analysis',status='no_change',run_id=sc['run_id'],occurred_at=now.isoformat(),summary='Authenticated stopped selection declined development; its known charge is retained.',details=dict(reference='host.selection_abstention.v1',decision='no_action',model_requests=1,known_cost_microyuan=result['known_cost_microyuan'],next_action='none'),version=dict(policy_sha256=sc['policy_sha256'],sdk_version='1.1.0'),changes=[],evidence=[dict(kind=k,sha256=h,verified=True,evidence_domain=domain) for k,h in (('selection_verification',pins['verification.json']),('original_review_lease',parent_sha256))],followups=[],mode=p['mode'],evidence_domain=domain)
        audit=AuditStore(c['audit_path']);audit.append('host-selection-abstention:'+parent_sha256,event);audit.export(c['export_root'])
        receipt=dict(schema='pi-selection-abstention-result-v1',status='no_action',parent_sha256=parent_sha256,selection_config_sha256=config_sha256,selection_attempt_id=operation,artifact_pins=pins,model_requests=0)
        _new(root/'receipt.json',receipt);return receipt
