"""Trusted first-bootstrap protocol. This is not a model tool or release permit.

The Linux host adapter owns authorization, locking and fixed native commands.
Preparing the protocol leaves ingress closed; activation is a separate operation.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import uuid

from .audit import digest, encoded, hash_value, name, require, utc
from .contracts import Receipt
from .ledger import OperationConflict

STEPS = ('close_ingress', 'drain_legacy', 'backup_pre', 'install_schema', 'bind_identity')
COUNTS = ('active_tasks', 'ready_messages', 'unacked_messages', 'consumers', 'task_locks', 'book_locks', 'unknown')
BASE = Path('/home/ubuntu/myink-pi-managed')
PROTECTED = (BASE/'state/ledger.sqlite', BASE/'state/actual-manager.sqlite', BASE/'audit/state/events.sqlite')


class BootstrapBlocked(ValueError):
    """A known unmet prerequisite; keep any established ingress fence closed."""


def _guard(condition, reason):
    if not condition:raise BootstrapBlocked(reason)


def _plan(value):
    require(isinstance(value,dict) and set(value)=={'schema','mode','operation_id','legacy','candidate','expires_at'}, 'closed bootstrap plan required')
    require(len(encoded(value))<=65536 and value['schema']=='pi-product-bootstrap-v1' and value['mode'] in ('ACTUAL','SIMULATED'))
    require(str(uuid.UUID(value['operation_id']))==value['operation_id'],'canonical operation identity required')
    utc(value['expires_at'])
    legacy=value['legacy'];candidate=value['candidate']
    require(isinstance(legacy,dict) and set(legacy)=={'source_commit','source_sha256','containers'} and hash_value(legacy['source_commit'],40) and hash_value(legacy['source_sha256']))
    rows=legacy['containers'];require(isinstance(rows,list) and len(rows)==7,'complete fixed product cohort required')
    roles=Counter();ids=set();images={}
    for row in rows:
        require(isinstance(row,dict) and set(row)=={'id','service','image_id'} and hash_value(row['id']) and isinstance(row['image_id'],str) and row['image_id'].startswith('sha256:') and hash_value(row['image_id'][7:]))
        require(row['id'] not in ids,'duplicate product container');ids.add(row['id']);roles[row['service']]+=1
        role='python' if row['service'] in ('api','worker') else row['service']
        require(role not in images or images[role]==row['image_id'],'mixed legacy component images');images[role]=row['image_id']
    require(roles==Counter(api=1,worker=2,frontend=1,postgres=1,redis=1,rabbitmq=1),'unexpected product service cohort')
    require(isinstance(candidate,dict) and set(candidate)=={'deployment_id','generation','owner','image_ids','commit_sha','schema_id','config_hash','schema_version'})
    require(name(candidate['deployment_id']) and name(candidate['owner']) and type(candidate['generation']) is int and candidate['generation']>0 and type(candidate['schema_version']) is int and candidate['schema_version']==1)
    require(hash_value(candidate['commit_sha'],40) and hash_value(candidate['config_hash']) and name(candidate['schema_id']))
    require(isinstance(candidate['image_ids'],dict) and set(candidate['image_ids'])==set(images))
    for role,image in candidate['image_ids'].items():
        require(isinstance(image,str) and image.startswith('sha256:') and hash_value(image[7:]))
        require(role=='python' or image==images[role],'bootstrap cannot upgrade unrelated infrastructure')
    return deepcopy(value)


def _facts(action, facts, plan, proofs):
    require(isinstance(facts,dict) and facts.get('verified') is True and facts.get('plan_sha256')==digest(plan),'unconfirmed bootstrap effect')
    common={'verified','plan_sha256'}
    if action=='close_ingress':
        require(set(facts)==common|{'fence_sha256'} and hash_value(facts['fence_sha256']),'confirmed ingress fence required')
    elif action=='drain_legacy':
        _guard(set(facts)==common|{'fence_sha256','worker_exit_codes',*COUNTS},'incomplete_drain')
        _guard(facts['fence_sha256']==proofs['close_ingress']['fence_sha256'],'ingress_fence_drift')
        codes=facts['worker_exit_codes']
        _guard(isinstance(codes,list) and len(codes)==2 and all(type(v) is int and v==0 for v in codes),'worker_exit_unconfirmed')
        _guard(all(type(facts[key]) is int and facts[key]==0 for key in COUNTS),'legacy_drain_unsettled')
    elif action=='backup_pre':
        _guard(set(facts)==common|{'release_pair_id','manifest_sha256','restore_operation_id','source_sha256'},'incomplete_PRE')
        _guard(facts['release_pair_id']==plan['operation_id'] and facts['source_sha256']==plan['legacy']['source_sha256'] and hash_value(facts['manifest_sha256']) and name(facts['restore_operation_id']),'PRE_restore_binding_mismatch')
    elif action=='install_schema':
        require(set(facts)==common|{'source_commit','historical_provenance_updated','protocol'} and facts['source_commit']==plan['candidate']['commit_sha'] and facts['historical_provenance_updated'] is False,'schema_effect_unconfirmed')
        protocol=facts['protocol'];versions={'protocol':1,'schema':1,'state':1,'effect_keys':1}
        require(isinstance(protocol,dict) and set(protocol)==set(versions)|{'serialization'} and all(type(protocol[k]) is int and protocol[k]==v for k,v in versions.items()) and protocol['serialization']=='jsonplus','incompatible_prepared_protocol')
    elif action=='bind_identity':
        require(set(facts)==common|{'identity'} and facts['identity']==plan['candidate'],'prepared_identity_unconfirmed')


def prepare_bootstrap(ledger, plan, host, *, now=None):
    """Persist every effect intent; an interrupted operation never redispatches.

    Trusted callers only. ACTUAL accepts only the canonical Linux adapter, whose
    independently issued approval and configuration are checked under its lock.
    A cached prepared receipt is historical evidence, never activation authority.
    """
    operation='bootstrap-invalid'
    try:
        plan=_plan(plan);operation=plan['operation_id']
        path=Path(ledger.path).resolve()
        require(all(path!=p and not (p.exists() and path.exists() and path.samefile(p)) for p in PROTECTED),'original financial/manager/audit state is not a product control ledger')
        if plan['mode']=='ACTUAL':
            require(now is None,'ACTUAL forbids an injected clock')
            from .product_runtime import LinuxProductHost
            require(type(host) is LinuxProductHost,'ACTUAL requires canonical Linux host')
        require(now is None or callable(now))
    except (ValueError,TypeError,KeyError,AttributeError,ImportError):
        return Receipt(operation,'blocked',dict(reason='bootstrap_configuration_rejected',release_allowed=False,model_requests=0))
    fingerprint=digest(plan);parent_payload=dict(plan_sha256=fingerprint)
    previous=ledger.get(operation)
    if previous is not None:
        ledger.intent(operation,'product_bootstrap',parent_payload)  # Reject identity reuse with changed bytes.
        if previous['status']=='pending':return Receipt(operation,'uncertain',dict(reason='unfinished_bootstrap_requires_reconciliation',release_allowed=False,model_requests=0))
        return Receipt(operation,previous['status'],previous['evidence'])
    proofs={};current=None;claimed=False
    def finish(status,evidence):
        receipt=Receipt(operation,status,dict(evidence,release_allowed=False,model_requests=0))
        if not claimed:return receipt
        try:ledger.finish(receipt)
        except Exception:return Receipt(operation,'uncertain',dict(reason='control_receipt_unconfirmed',release_allowed=False,model_requests=0))
        return receipt
    def check():
        _guard(utc((now or (lambda:datetime.now(timezone.utc)))())<utc(plan['expires_at']),'bootstrap_authority_expired')
        host.authorize(deepcopy(plan))
        _guard(host.inspect(deepcopy(plan))==plan['legacy'],'legacy_identity_drift')
    try:
        with host.lock(deepcopy(plan)):
            # Two callers can observe an absent intent before either obtains the
            # shared lock. Only its holder may claim or finish this operation.
            previous=ledger.get(operation)
            if previous is not None:
                ledger.intent(operation,'product_bootstrap',parent_payload)
                if previous['status']=='pending':return Receipt(operation,'uncertain',dict(reason='unfinished_bootstrap_requires_reconciliation',release_allowed=False,model_requests=0))
                return Receipt(operation,previous['status'],previous['evidence'])
            ledger.intent(operation,'product_bootstrap',parent_payload);claimed=True
            for action in STEPS:
                current=None;check()
                current=operation+':'+action
                require(ledger.get(current) is None,'step intent already exists')
                ledger.intent(current,'product_bootstrap_step',dict(plan_sha256=fingerprint,action=action))
                try:
                    facts=host.perform(action,deepcopy(plan),deepcopy(proofs))
                    _facts(action,facts,plan,proofs)
                    _guard(utc((now or (lambda:datetime.now(timezone.utc)))())<utc(plan['expires_at']),'bootstrap_authority_expired_after_effect')
                except BootstrapBlocked as error:
                    ledger.finish(Receipt(current,'blocked',dict(reason=str(error))))
                    return finish('blocked',dict(reason=str(error),stopped_at=action))
                except Exception as error:
                    ledger.finish(Receipt(current,'uncertain',dict(reason='effect_outcome_unconfirmed',error_class=type(error).__name__)))
                    return finish('uncertain',dict(reason='effect_outcome_unconfirmed',stopped_at=action))
                ledger.finish(Receipt(current,'done',facts));proofs[action]=facts
            return finish('done',dict(phase='protocol_prepared',admission_closed=True,workers_stopped=True,plan_sha256=fingerprint,proofs=proofs))
    except OperationConflict:
        raise
    except (BootstrapBlocked,PermissionError,BlockingIOError) as error:
        return finish('blocked',dict(reason=str(error) if isinstance(error,BootstrapBlocked) else type(error).__name__))
    except Exception as error:
        return finish('uncertain',dict(reason='bootstrap_control_unconfirmed',error_class=type(error).__name__))
