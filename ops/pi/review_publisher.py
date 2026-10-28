"""External exact FileReview publisher. Never acquires maintenance.lock or pays."""
from pathlib import Path
import fcntl
from .audit import AuditStore,_path,_plain,digest,encoded,require
from .development_inputs import file_hash,ledger_snapshot,prepare_template
from .review_issuer import development_review
from .review_dossier import semantic_hash
from .review_lease import _read,_directory,_sync,_new,load_policy,inspect_review
from .task_package import _publish_new

RECORD=set('schema policy_path policy_sha256 review_config_path review_config_sha256 artifact_pins scope'.split())


def publish(lease_path,lease_sha256,config_path,*,clock=None):
    record,pin=_read(lease_path);require(pin==lease_sha256 and isinstance(record,dict),'authenticated lease record required')
    bound=record.get('schema')=='pi-review-lease-record-v2'
    require(set(record)==(RECORD|{'binding'} if bound else RECORD) and record['schema'] in ('pi-review-lease-record-v1','pi-review-lease-record-v2'),'closed lease schema required')
    p,now=load_policy(record['policy_path'],record['policy_sha256'],clock);lease=record['scope'];root=_directory(_path(lease_path).parent)
    expected='lease-'+digest(dict(review_config_sha256=record['review_config_sha256'],semantic_sha256=lease['semantic_sha256']))
    base=root.parent if bound else root
    require(base.parent==_path(p['root']) and base.name==expected and (not bound or root.name=='binding') and _path(lease_path)==root/'lease.json','host lease custody drift')
    require(p['mode']!='ACTUAL' or bound,'ACTUAL publication requires authenticated selection binding')
    publication_lock=_path(p['root'])/'.publication.lock'
    if not publication_lock.exists():
        try:_new(publication_lock,dict(schema='pi-review-publication-lock-v1'))
        except FileExistsError:pass
    _plain(publication_lock)
    tools=_path(p['ledger_path']).with_suffix('.tools.lock');_plain(tools)
    with publication_lock.open('rb') as own_lock,tools.open('rb') as fee_lock:
        fcntl.flock(own_lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(fee_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        require(file_hash(lease_path)==lease_sha256,'lease revoked')
        if bound:
            from .selection_binding import inspect as inspect_selection
            binding=record['binding'];require(isinstance(binding,dict) and set(binding)=={'parent_path','parent_sha256','selection_config_path','selection_config_sha256','artifact_pins'} and _path(binding['parent_path'])==base/'lease.json','selection binding custody drift')
            parent,_,_,operation,selection_pins=inspect_selection(binding['parent_path'],binding['parent_sha256'],binding['selection_config_path'],binding['selection_config_sha256'],clock=clock)
            receipt=_read(root/'receipt.json')[0]
            require(receipt.get('schema')=='pi-selection-binding-result-v1' and receipt.get('status')=='bound' and receipt.get('lease_sha256')==lease_sha256 and receipt.get('selection_config_sha256')==binding['selection_config_sha256'] and receipt.get('selection_attempt_id')==operation,'selection binding is incomplete')
            require(binding['artifact_pins']==selection_pins and record['scope']==dict(parent['scope'],allowed_fee_operation_ids=[operation]) and all(record[k]==parent[k] for k in RECORD-{'schema','scope'}),'derived lease scope drift')
        p,now,c,tc,material,fee,pins=inspect_review(record['policy_path'],record['policy_sha256'],record['review_config_path'],record['review_config_sha256'],clock=clock,allow_fee_append=True)
        require(pins==record['artifact_pins'] and lease['semantic_sha256']==semantic_hash(tc) and lease['plan_hash']==material['dossier']['model_view']['plan_hash'] and lease['deadline_ceiling']==tc['deadline_seconds'] and lease['prepared_parent']==p['prepared_parent'] and lease['mode']==p['mode'] and lease['legacy_unknown_ids']==p['legacy_unknown_ids'],'lease reviewed scope drift')
        require(lease['fee_checkpoint']==_read(Path(c['root'])/'ledger-after-private.json')[0],'lease paid checkpoint drift')
        cp=_path(config_path);config,config_pin=_read(cp,65536);request,request_pin=_read(cp.parent/'review-request.json',65536)
        require(request.get('config_path')==str(cp),'request names another prepared config')
        require(prepare_template(cp)[0]==config,'prepared execution contract drift')
        approval=development_review(lease,config,request,fee,now=now);target=_path(config['review_path'])
        require(not target.exists() and not target.is_symlink(),'FileReview already exists; never overwrite')
        claim=root/'publication';require(not claim.exists(),'publication claim exists; no replay');claim.mkdir(mode=0o700);_sync(root)
        _new(claim/'intent.json',dict(schema='pi-review-publication-intent-v1',lease_sha256=lease_sha256,config_sha256=config_pin,request_sha256=request_pin,approval_sha256=digest(approval)))
        # Last authority transition: all private inputs stay exact, no paid call here.
        require(file_hash(lease_path)==lease_sha256 and file_hash(cp)==config_pin and file_hash(cp.parent/'review-request.json')==request_pin and file_hash(record['policy_path'])==record['policy_sha256'] and ledger_snapshot(p['ledger_path'])==fee,'publication revoked before approval')
        prepare_template(cp);load_policy(record['policy_path'],record['policy_sha256'],clock)
        # FileReview may immediately start development. Do not expose permission
        # while still holding its fee lock. Execution rechecks the exact fee pin.
        fcntl.flock(fee_lock,fcntl.LOCK_UN)
        retained=_publish_new(target,encoded(approval)+b'\n');_sync(target.parent)
        require(not retained,'approval staging alias retained; publication uncertain')
        result=dict(schema='pi-review-publication-result-v1',status='published',model_requests=0,lease_sha256=lease_sha256,approval_sha256=file_hash(target),authorization_sha256=request['authorization_sha256'],occurred_at=now.isoformat())
        domain='real_provider_fixed_input' if c['mode']=='ACTUAL' else 'synthetic'
        event=dict(kind='review',status='passed',run_id=tc['run_id'],occurred_at=now.isoformat(),summary='Host issued exact FileReview under independently verified SDK scope. Product release is not authorized.',details=dict(reference='host.file_review.v1',decision='issued',reason='closed_sdk_and_host_policy',next_action='original_manager_development_gate'),version=dict(policy_sha256=c['policy_sha256'],sdk_version='1.1.0'),changes=[],evidence=[dict(kind=kind,sha256=pin,verified=True,evidence_domain=domain) for kind,pin in (('independent_review_dossier',c['dossier_sha256']),('host_review_lease',lease_sha256),('exact_file_review',result['approval_sha256']))],followups=[],mode=c['mode'],evidence_domain=domain)
        audit=AuditStore(c['audit_path']);audit.append('host-file-review:'+digest([lease_sha256,request['authorization_sha256']]),event);audit.export(c['export_root'])
        _new(claim/'receipt.json',result);return result
