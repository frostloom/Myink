"""Host-policy authorization of the exact independently reviewed selection catalog."""
from pathlib import Path
import fcntl
from .audit import AuditStore,_path,_plain,digest,encoded,require
from .development_inputs import authorization_hash,file_hash,ledger_snapshot,read_json,validate_review
from .review_lease import _read,_directory,_new,_sync,load_policy,inspect_review
from .review_dossier import semantic_hash
from .task_package import _publish_new
from . import selection_launcher as selection


def issue(lease_path,lease_sha256,config_path,config_sha256,*,clock=None):
    record,pin=_read(lease_path);require(pin==lease_sha256 and record['schema']=='pi-review-lease-record-v1','original unbound review lease required')
    p,_=load_policy(record['policy_path'],record['policy_sha256'],clock);lockpath=_path(p['ledger_path']).with_suffix('.tools.lock');_plain(lockpath)
    with lockpath.open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        p,now,c,tc,material,fee,pins=inspect_review(record['policy_path'],record['policy_sha256'],record['review_config_path'],record['review_config_sha256'],clock=clock)
        scope=record['scope'];root=_directory(_path(lease_path).parent)
        require(_path(lease_path)==root/'lease.json' and root.parent==_path(p['root']) and root.name=='lease-'+digest(dict(review_config_sha256=record['review_config_sha256'],semantic_sha256=scope['semantic_sha256'])),'lease outside host custody')
        require(record['artifact_pins']==pins and scope['allowed_fee_operation_ids']==[] and scope['semantic_sha256']==semantic_hash(tc) and scope['fee_checkpoint']==fee,'unbound reviewed scope drift')
        cp=_path(config_path);require(cp.is_relative_to(_path(p['review_config_parent'])) and file_hash(cp)==config_sha256,'host selection config pin drift')
        sc,_,tasks,current,_=selection.prepare_template(cp)
        require(current==fee and sc['review_sha256']=='0'*64 and all(sc[k]==c[k] for k in ('runtime_path','runtime_sha256','ledger_path','policy_path','policy_sha256','credential_path','credential_sha256','docker','endpoint','daemon_id','image_id')) and sc['source_path']==tc['source_path'] and sc['source_sha256']==tc['source_sha256'],'selection host/source scope drift')
        require(digest(tasks)==digest(read_json(c['outcome_path'])['catalog']) and sc['ledger_sha256']==fee['sha256'],'selection catalog/checkpoint was not reviewed')
        target=_path(sc['review_path']);require(cp.name=='selection-config.json' and target==cp.parent/'selection-review.json' and not target.exists() and not target.is_symlink(),'fresh host selection review location required')
        review=dict(source='independent_review',verified=True,result='approved',reviewer='independent-sdk-selection-policy',authorization_sha256=authorization_hash(sc),plan_hash=digest(tasks),base=sc['source_sha256'],candidate_id=sc['run_id'],owner='local-development-controller',generation=1)
        validate_review(review,sc,digest(tasks),sc['source_sha256'])
        claim=root/'selection-review';require(not claim.exists(),'selection approval claim exists; no replay');claim.mkdir(mode=0o700);_sync(root)
        _new(claim/'intent.json',dict(schema='pi-selection-review-intent-v1',lease_sha256=lease_sha256,config_sha256=config_sha256,approval_sha256=digest(review)))
        require(file_hash(lease_path)==lease_sha256 and file_hash(cp)==config_sha256 and file_hash(record['policy_path'])==record['policy_sha256'] and ledger_snapshot(p['ledger_path'])==fee,'selection review revoked before publication')
        selection.prepare_template(cp);load_policy(record['policy_path'],record['policy_sha256'],clock)
        fcntl.flock(lock,fcntl.LOCK_UN)
        retained=_publish_new(target,encoded(review)+b'\n');_sync(target.parent);require(not retained,'selection review staging uncertain')
        result=dict(schema='pi-selection-review-result-v1',status='published',model_requests=0,lease_sha256=lease_sha256,approval_sha256=file_hash(target),authorization_sha256=authorization_hash(sc),occurred_at=now.isoformat())
        domain='real_provider_fixed_input' if p['mode']=='ACTUAL' else 'synthetic'
        event=dict(kind='review',status='passed',run_id=sc['run_id'],occurred_at=now.isoformat(),summary='Host authorized only the independently reviewed frozen selection catalog.',details=dict(reference='host.selection_review.v1',decision='issued_selection',next_action='one_original_gateway_selection'),version=dict(policy_sha256=c['policy_sha256'],sdk_version='1.1.0'),changes=[],evidence=[dict(kind=kind,sha256=pin,verified=True,evidence_domain=domain) for kind,pin in (('independent_review_dossier',c['dossier_sha256']),('host_review_lease',lease_sha256),('exact_selection_review',result['approval_sha256']))],followups=[],mode=p['mode'],evidence_domain=domain)
        audit=AuditStore(c['audit_path']);audit.append('host-selection-review:'+digest([lease_sha256,authorization_hash(sc)]),event);audit.export(c['export_root'])
        _new(claim/'receipt.json',result);return result
