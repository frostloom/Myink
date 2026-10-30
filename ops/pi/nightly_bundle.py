"""Freeze a reconciled original-manager candidate for human publication review.

Pre-development FileReview and the independent frozen checker are authenticated
by manager_completion.inspect. Human approval of the exact final package remains
mandatory; an extra paid post-development recommendation is not required merely
to prepare these private files. Nothing here publishes, deploys or runs a model.
"""
from pathlib import Path
from hashlib import file_digest
import stat
from .audit import _path,_plain,require,strict_json,encoded,digest,validate_record
from .development_inputs import tree_hash,file_hash
from .nightly_gate import BASE,_package
from .product_commands import _write
from .backup import durable_file
from . import manager_completion
from .nightly_image import LocalImage,image_id


def _json(path):
    path=_path(path);_plain(path);require(path.stat().st_size<=4194304 and stat.S_IMODE(path.stat().st_mode)==0o600,'private bounded bundle file required');return strict_json(path.read_bytes())


def _archive(path):
    path=_path(path);_plain(path);require(0<path.stat().st_size<=8*1024**3 and stat.S_IMODE(path.stat().st_mode)==0o600,'private bounded image archive required')
    with path.open('rb') as stream:return file_digest(stream,'sha256').hexdigest()


def _copy(source,target,pin):
    source=_path(source);require(tree_hash(source)==pin,'original source drift before copy');target.mkdir(mode=0o700)
    for p in sorted(source.rglob('*')):
        out=target/p.relative_to(source)
        if p.is_dir():out.mkdir(mode=0o700)
        else:durable_file(out,p.read_bytes())
    require(tree_hash(source)==pin==tree_hash(target),'frozen source copy drift')


def _audit(gate,cycle,task,view,image,original,comparison):
    domain='real_provider_fixed_input' if gate.mode=='ACTUAL' else 'synthetic'
    common=dict(run_id=task,occurred_at=gate.clock().isoformat(),version=dict(candidate_sha256=image['candidate_sha256'],image_ids=dict(python=image['image_id'])),changes=[],evidence=[dict(kind=kind,sha256=pin,verified=True,evidence_domain=domain) for kind,pin in (('original_manager_proof',digest(original)),('local_image_receipt',digest(image)),('comparison_parameters',digest(comparison)))],followups=[],mode=gate.mode,evidence_domain=domain)
    records=[]
    for key,kind,status,summary,reference,reason,next_action in (
        ('ready','version','no_release','Local candidate image and approval package prepared; product has not been deployed.','nightly.human_hold.v1','awaiting_human_approval','review_exact_package'),
        ('nextday','followup','blocked','Next-day parameters reserved relative to verified deployment; no calendar run has been scheduled.','nightly.nextday.relative.v1','awaiting_verified_deployment','schedule_after_verified_deployment')):
        event=dict(common,kind=kind,status=status,summary=summary,details=dict(reference=reference,decision=status,reason=reason,next_action=next_action,operation_id=cycle,model_requests=0,known_cost_microyuan=0),changes=view['changes'] if key=='ready' else [])
        validate_record(event);records.append(dict(record_key=task+':nightly:'+cycle+':'+key,event=event))
    return dict(schema='pi-nightly-audit-reservation-v1',cycle_id=cycle,records=records)


def prepare(gate,cycle,root,task_id,base_image,docker,endpoint,daemon_id,*,image_factory=None):
    state=gate.status();require(state['phase']=='preparing' and state['cycle_id']==cycle,'active single preparation required');root=_path(root);image_id(base_image)
    require(not root.exists() and root.parent.is_dir(),'exclusive bundle preparation root required')
    if gate.mode=='ACTUAL':require(image_factory is None and root==BASE/'nightly'/cycle/'bundle','fixed ACTUAL bundle root required')
    else:require(not root.is_relative_to(BASE),'isolated bundle root required')
    pending=manager_completion.request(gate.state,gate.billing,task_id,mode=gate.mode);require(pending['status']=='candidate_ready','original manager has no completed candidate')
    gate.bind_task(cycle,task_id)
    root.mkdir(mode=0o700);_write(root/'request.json',pending['request'])
    proof=manager_completion.inspect(gate.state,gate.billing,task_id,root/'request.json',file_hash(root/'request.json'),mode=gate.mode)
    development=proof['development'];config=development['config'];view=development['dossier']['model_view'];candidate_pin=development['candidate_sha256']
    _copy(config['source_path'],root/'baseline',config['source_sha256']);_copy(Path(config['root'])/'candidate',root/'candidate',candidate_pin)
    original=dict(schema='pi-nightly-original-proof-v1',task_id=task_id,manager_binding=proof['manager_binding'],artifact_pins=proof['artifact_pins'],tools_sha256=development['tools_sha256'],model_requests=development['model_requests'],known_cost_microyuan=development['known_cost_microyuan'])
    _write(root/'original-proof.json',original);_write(root/'changes.json',view['changes']);durable_file(root/'patch.diff',view['diff'].encode())
    evaluation=dict(schema='pi-nightly-evaluation-v1',sdk_verified=True,original_proof_sha256=digest(original),checker=view['final_check'],baseline_report_sha256=config['baseline_sha256'],independent_review=dict(kind='pre_development_file_review',sha256=config['review_sha256']),model_requests=development['model_requests'],known_cost_microyuan=development['known_cost_microyuan'],tool_count=len(development['tools']),evidence_domain=view['evidence_domain'],online_improvement_proven=False)
    durable_file(root/'regression.py',Path(config['test_path']).read_bytes());require(file_hash(root/'regression.py')==config['test_sha256'],'frozen regression source drift')
    factory=image_factory or LocalImage
    image=factory(gate,cycle,root.parent/'image',docker,endpoint,daemon_id).build(root/'baseline',root/'candidate',base_image)
    require(image['schema']=='pi-nightly-local-image-v1' and image['status']=='ready' and image['cycle_id']==cycle and image['base_image_id']==base_image and image['source_sha256']==config['source_sha256'] and image['candidate_sha256']==candidate_pin and image['published'] is image['deployed'] is False,'image is not this local candidate')
    image_id(image['image_id']);archive=_path(image['archive_path']);require(archive==root.parent/'image/image.tar' and _archive(archive)==image['archive_sha256'],'matching actual local image archive required')
    require(_json(root.parent/'image/receipt.json')==image,'image receipt drift');_write(root/'image.json',image)
    comparison=dict(schema='pi-nightly-nextday-v1',mode=gate.mode,cycle_id=cycle,anchor='verified_deployment',day_offset=1,hour=3,timezone='Asia/Shanghai',status='planned',baseline_sha256=config['source_sha256'],baseline_report_sha256=config['baseline_sha256'],source_sha256=candidate_pin,image_id=image['image_id'],test_sha256=config['test_sha256'],test_artifact='regression.py',test_cases=config['test_cases'],guard_metrics=view['plan']['guard_metrics'],evidence_domain=view['evidence_domain'],online_improvement_proven=False)
    _write(root/'comparison.json',comparison)
    flow=[]
    for index,row in enumerate(development['tools'],1):
        feedback=row['evidence'].get('check_feedback',{});counts={k:feedback[k] for k in ('tests','failures','errors','skipped','passed') if isinstance(feedback,dict) and k in feedback and type(feedback[k]) in (int,bool)}
        flow.append(dict(sequence=index,tool=row['payload']['tool'],operation_id=row['operation_id'],status=row['status'],receipt_sha256=digest(row),checker=counts))
    _write(root/'tool-flow.json',flow);audit=_audit(gate,cycle,task_id,view,image,original,comparison);_write(root/'audit.json',audit)
    evaluation.update(base_image_id=base_image,image_receipt_sha256=digest(image),tool_flow_sha256=file_hash(root/'tool-flow.json'),audit_sha256=file_hash(root/'audit.json'));_write(root/'evaluation.json',evaluation)
    manifest=dict(schema='pi-nightly-artifact-v1',baseline_sha256=config['source_sha256'],source_sha256=candidate_pin,patch_sha256=file_hash(root/'patch.diff'),evaluation_sha256=file_hash(root/'evaluation.json'),image_id=image['image_id'],image_artifact_sha256=image['archive_sha256'],comparison_sha256=file_hash(root/'comparison.json'),changes_sha256=file_hash(root/'changes.json'))
    _package(manifest);_write(root/'manifest.json',manifest)
    require(tree_hash(root/'candidate')==candidate_pin and tree_hash(root/'baseline')==config['source_sha256'],'prepared source changed before seal')
    return gate.ready(cycle,manifest)


def verify(gate,root):
    """Read-only artifact check, never action permission; call require_action too."""
    root=_path(root);manifest=_package(_json(root/'manifest.json'));comparison=_json(root/'comparison.json');evaluation=_json(root/'evaluation.json');image=_json(root/'image.json');changes=_json(root/'changes.json')
    cycle=root.parent.name
    with gate._connection() as connection:
        row=gate._row(connection,cycle);require(row['package'] is not None and strict_json(row['package'])==manifest,'bundle differs from original sealed approval package')
    require(tree_hash(root/'baseline')==manifest['baseline_sha256'] and tree_hash(root/'candidate')==manifest['source_sha256'],'sealed source drift')
    for name,key in (('patch.diff','patch_sha256'),('evaluation.json','evaluation_sha256'),('comparison.json','comparison_sha256'),('changes.json','changes_sha256')):
        _plain(root/name);require(file_hash(root/name)==manifest[key],'sealed bundle file drift')
    require(digest(_json(root/'original-proof.json'))==evaluation['original_proof_sha256'],'original completion proof drift')
    require(digest(image)==evaluation['image_receipt_sha256'] and image['base_image_id']==evaluation['base_image_id'],'sealed image metadata drift')
    _plain(root/'regression.py');require(file_hash(root/'regression.py')==comparison['test_sha256'] and comparison['test_artifact']=='regression.py','sealed regression source drift')
    require(image==_json(root.parent/'image/receipt.json') and image['cycle_id']==cycle and image['image_id']==manifest['image_id'] and image['candidate_sha256']==manifest['source_sha256'] and image['source_sha256']==manifest['baseline_sha256'] and image['archive_sha256']==manifest['image_artifact_sha256'] and image['published'] is image['deployed'] is False,'sealed local image identity drift')
    require(_path(image['archive_path'])==root.parent/'image/image.tar' and _archive(image['archive_path'])==manifest['image_artifact_sha256'],'sealed image archive drift')
    require(comparison['cycle_id']==cycle,'comparison belongs to another cycle')
    require(all(comparison[k]==manifest[k] for k in ('image_id','source_sha256','baseline_sha256')) and comparison['anchor']=='verified_deployment' and comparison['status']=='planned','sealed comparison identity drift')
    for name,key in (('tool-flow.json','tool_flow_sha256'),('audit.json','audit_sha256')):
        _plain(root/name);require(file_hash(root/name)==evaluation[key],'sealed audit output drift')
    return dict(audit=_json(root/'audit.json'),tool_flow=_json(root/'tool-flow.json'),manifest=manifest,comparison=comparison,evaluation=evaluation,image=image,changes=changes)
