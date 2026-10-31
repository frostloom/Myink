"""Product observation/preflight projection, never an executable release permit."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import os,sqlite3
from .audit import AuditStore,digest,encoded,hash_value,name,require,utc
from . import product_reality as reality

REQUIRED=set('schema mode authority release_allowed model_requests run_id observer_config_sha256 observed_at status containers excluded images metadata metadata_status command_proofs deployment_id generation owner source_commit source_sha256 config_sha256 maintenance_epoch cohort_sha256 completed_at observation_sha256'.split())
OPTIONAL={'observation_path','failure_class','failure_stage'}
IDENTITY=('deployment_id','generation','owner','source_commit','source_sha256','config_sha256','maintenance_epoch')
ROLES={'python','frontend','postgres','redis','rabbitmq'}


def _validate(value):
    require(isinstance(value,dict) and REQUIRED<=set(value)<=REQUIRED|OPTIONAL and len(encoded(value))<=1048576,'bounded product observation required')
    require(value['schema']=='pi-product-observation-v1' and value['mode'] in ('ACTUAL','SIMULATED') and value['authority']=='none' and value['release_allowed'] is False and type(value['model_requests']) is int and value['model_requests']==0,'observation confers no authority')
    require(value['status'] in ('observed','confounded','blocked') and name(value['run_id']) and hash_value(value['observer_config_sha256']) and hash_value(value['observation_sha256']),'typed product observation identity required')
    raw={k:v for k,v in value.items() if k not in ('observation_sha256','observation_path')};require(digest(raw)==value['observation_sha256'],'product observation digest drift')
    require(all(value[k] is None for k in IDENTITY),'observed unknown identity cannot be upgraded by caller')
    require(isinstance(value['containers'],list) and len(value['containers'])<=128 and isinstance(value['excluded'],list) and len(value['excluded'])<=128 and isinstance(value['command_proofs'],list) and len(value['command_proofs'])<=8,'bounded census required')
    require(isinstance(value['images'],dict) and set(value['images'])<=ROLES,'fixed product component roles required')
    for image in value['images'].values():
        require(isinstance(image,dict) and set(image)=={'image_id','revision_claim','source_attested'} and reality._image(image['image_id']) and image['source_attested'] is False,'image claims cannot become source attestations')
        claim=image['revision_claim'];require(claim is None or hash_value(claim,40),'bounded untrusted image claim required')
    require(value['metadata_status'] in ('observed','unknown'),'explicit metadata availability required')
    if value['metadata_status']=='observed':require(isinstance(value['metadata'],dict) and set(value['metadata'])==reality.META and all(type(v) is bool for v in value['metadata'].values()),'typed catalog availability required')
    else:require(value['metadata'] is None,'unknown catalog cannot assert absence')
    if value['status']=='observed':require(set(value['images'])==ROLES and hash_value(value['cohort_sha256']) and value['cohort_sha256']==digest(dict(containers=value['containers'],images=value['images'])),'coherent product cohort required')


def inspect_reality(observation,*,at=None):
    _validate(observation);now=utc(at or datetime.now(timezone.utc));started=utc(observation['observed_at']);ended=utc(observation['completed_at']);blockers=[]
    def block(code,evidence,next_action):blockers.append(dict(code=code,evidence_class=evidence,next_action=next_action))
    if observation['status']!='observed':block('product_inventory_unverified','live_product_census','reobserve_stable_container_and_image_census')
    if not started<=ended<=now:block('observation_clock_unverified','live_product_census','reobserve_with_trusted_clock')
    elif now-ended>timedelta(minutes=5):block('observation_stale','live_product_census','reobserve_before_adoption_review')
    meta=observation['metadata']
    if observation['metadata_status']=='unknown':block('maintenance_catalog_unknown','catalog_availability','verify_fixed_readonly_catalog_probe')
    else:
        if not all(meta[k] for k in ('maintenance_control','maintenance_executions','maintenance_lock_function')):block('maintenance_protocol_absent','catalog_availability','prepare_reviewed_main_maintenance_bootstrap')
        if not meta['task_provenance'] or not meta['agent_run_provenance']:block('run_provenance_absent','catalog_availability','prepare_reviewed_product_provenance_integration')
    public_health=[c.get('healthy') for c in observation['containers'] if c.get('service') in ('myink-api','myink-caddy')]
    if len(public_health)!=2 or any(v!='healthy' for v in public_health):block('runtime_health_unverified','container_health_only','verify_application_and_edge_readiness')
    # These require separate live host evidence, not extra fields in an observation.
    for code,evidence,action in (
        ('deployment_ownership_unknown','host_deployment_identity','establish_approved_owner_generation_epoch_and_image_binding'),
        ('source_attestation_missing','source_artifact_identity','attest_actual_product_source_and_preserve_component_history'),
        ('functional_pause_resume_unverified','maintenance_runtime','verify_real_admission_pause_checkpoint_and_queue_resume'),
        ('compatible_backup_restore_unverified','backup_recovery','verify_current_PRE_POST_and_restore_context'),
        ('main_adoption_and_ci_unverified','main_integration','prepare_exact_main_adoption_without_reverting_product_fixes'),
        ('explicit_product_release_authorization_required','human_release_authority','present_concrete_reviewed_product_release_for_approval'),
        ('business_validation_unverified','online_business','prepare_fixed_health_business_and_owned_rollback_probes')):block(code,evidence,action)
    return dict(schema='pi-product-release-preflight-v1',authority='none',mode=observation['mode'],run_id=observation['run_id'],status='blocked',release_allowed=False,observation_sha256=observation['observation_sha256'],checked_at=now.isoformat(),blockers=blockers,component_images={role:row['image_id'] for role,row in observation['images'].items()})


def records(observation,preflight,controller_sha256=None):
    _validate(observation);require(preflight==inspect_reality(observation,at=preflight['checked_at']),'derived product preflight required')
    require(controller_sha256 is None or hash_value(controller_sha256),'controller context digest required')
    domain='offline' if observation['mode']=='ACTUAL' else 'synthetic';verified=observation['status']=='observed'
    evidence=[dict(kind='product_observation',sha256=observation['observation_sha256'],verified=verified,evidence_domain=domain),dict(kind='derived_release_preflight',sha256=digest(preflight),verified=True,evidence_domain=domain)]
    common=dict(run_id=observation['run_id'],occurred_at=observation['completed_at'],version=dict(controller_sha256=controller_sha256),changes=[],evidence=evidence,followups=[],mode=observation['mode'],evidence_domain=domain);result=[]
    for role in ('python','frontend'):
        image=observation['images'].get(role)
        if image is None:continue
        event=dict(common,kind='version',status='no_change' if verified else 'uncertain',summary='Observed running '+role+' image; source attestation and deployment ownership remain unverified.',version=dict(controller_sha256=controller_sha256,image_ids={role:image['image_id']}),details=dict(reference='product.observed.'+role+'.v1',availability='observed_only',reason='image_label_is_not_source_attestation',result_summary='Image revision label: '+(image['revision_claim'] or 'unknown'),next_action='use_separate_live_release_preflight'))
        result.append(dict(record_key=observation['run_id']+':component:'+role,event=event))
    event=dict(common,kind='plan',status='blocked',summary='Product release preflight; observation/catalog availability grants no release or rollback authority.',details=dict(reference='product.release_preflight.v1',decision='blocked',reason=','.join(row['code'] for row in preflight['blockers']),next_action='prepare_exact_reviewed_main_and_product_adoption'))
    result.append(dict(record_key=observation['run_id']+':release-preflight',event=event));return result


def observe_and_publish(config_path,config_sha256,*,runner=None,clock=None):
    observation=reality.observe(config_path,config_sha256,runner=runner,clock=clock);c=__import__('json').loads(Path(config_path).read_bytes());root=Path(observation['observation_path']);preflight=inspect_reality(observation,at=(clock or (lambda:datetime.now(timezone.utc)))());reality._new(root/'preflight.json',preflight)
    controller=os.environ.get('PI_OBSERVER_RUNTIME_SHA256');events=records(observation,preflight,controller if hash_value(controller) else None);exported=False;failure=None
    try:
        require(reality.file_hash(config_path)==config_sha256,'product config revoked before audit');store=AuditStore(c['audit_path'])
        for item in events:store.append(item['record_key'],item['event'])
        store.export(c['export_root']);exported=True
    except (ValueError,OSError,sqlite3.Error) as error:
        failure=type(error).__name__;reality._new(root/'audit-failure.json',dict(failure_class=failure))
    result=dict(schema='pi-product-check-v1',mode=observation['mode'],status='recorded' if exported and observation['status']=='observed' else observation['status'] if exported else 'uncertain',run_id=observation['run_id'],release_allowed=False,model_requests=0,observation_status=observation['status'],observation_path=str(root),observation_sha256=observation['observation_sha256'],preflight_sha256=digest(preflight),audit_exported=exported,audit_failure_class=failure,record_count=len(events))
    reality._new(root/'audit-outcome.json',result);return result
