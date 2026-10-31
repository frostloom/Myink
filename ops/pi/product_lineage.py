"""Root-sealed previous-release lineage and stopped-backend retirement only.

This is a trusted host operation, never a model tool or permission to deploy.
"""
from collections import Counter
from copy import deepcopy
import uuid
from .audit import digest,encoded,hash_value,require,utc
from .contracts import Receipt
from .product_bootstrap import _plan

FIELDS=set('schema mode target authority approved_action next_plan_sha256 project_operation_id previous_plan previous_action previous_context_sha256 previous_control_sha256 current_cohort retired expires_at'.split())
SERVICES={'api':'myink-api','worker':'myink-worker','frontend':'myink-caddy','postgres':'myink-pg','redis':'myink-redis','rabbitmq':'myink-rabbitmq'}


def validate(value,plan,target,now):
    require(isinstance(value,dict) and set(value)==FIELDS and value['schema']=='pi-product-lineage-v1' and len(encoded(value))<=65536,'closed previous-release lineage required')
    plan=_plan(plan);old=_plan(value['previous_plan'])
    require(plan['schema']=='pi-product-upgrade-v2' and old['operation_id']!=plan['operation_id'] and value['next_plan_sha256']==digest(plan),'exact next upgrade required')
    require(value['mode']==old['mode']==plan['mode'] and value['target']==target and target in ('production','rehearsal') and (plan['mode']!='SIMULATED' or target=='rehearsal'),'lineage target mismatch')
    require(value['authority']==('human_product_release' if target=='production' else 'owned_rehearsal') and value['approved_action']=='retire_previous' and value['previous_action'] in ('activate','rollback'),'fixed retirement authority required')
    require(str(uuid.UUID(value['project_operation_id']))==value['project_operation_id'] and all(hash_value(value[k]) for k in ('previous_context_sha256','previous_control_sha256')),'sealed historical identities required')
    require(utc(now)<utc(value['expires_at'])<=utc(plan['expires_at']),'lineage authority expired')
    current=value['current_cohort'];retired=value['retired'];count=3 if value['previous_action']=='activate' else 6
    seen=set()
    for rows,total in ((current,3),(retired,count)):
        require(isinstance(rows,list) and len(rows)==total and Counter(v.get('service') for v in rows if isinstance(v,dict))==Counter(api=total//3,worker=2*total//3),'complete historical backend cohort required')
        for row in rows:
            require(isinstance(row,dict) and set(row)=={'id','service','image_id'} and hash_value(row['id']) and row['id'] not in seen and isinstance(row['image_id'],str) and row['image_id'].startswith('sha256:') and hash_value(row['image_id'][7:]),'unique historical backend identity required');seen.add(row['id'])
    infra=[v for v in old['legacy']['containers'] if v['service'] not in ('api','worker')]
    require(sorted(plan['legacy']['containers'],key=lambda v:v['id'])==sorted(infra+current,key=lambda v:v['id']),'next cohort differs from completed previous release')
    expected={v['id']:v for v in retired}
    require(all(expected.get(v['id'])==v for v in old['legacy']['containers'] if v['service'] in ('api','worker')) and not set(expected)&{v['id'] for v in plan['legacy']['containers']},'active or infrastructure retirement rejected')
    previous=plan['previous'];role=value['previous_action'];epoch=old['operation_id'] if role=='activate' else 'rollback-'+old['operation_id']
    require(previous['epoch']==epoch and utc(previous['deadline'])==utc(old['expires_at']),'previous epoch or deadline mismatch')
    require(plan['legacy']['source_commit']==(old['candidate']['commit_sha'] if role=='activate' else old['legacy']['source_commit']),'historical source commit mismatch')
    return deepcopy(value)


def _completed(ledger,op,kind,payload):
    row=ledger.get(op)
    require(row and row['kind']==kind and row['status']=='done' and row['payload']==payload,'completed original historical operation required')
    return row['evidence']


def history(host):
    p=validate(host.lineage,host.plan,host.config['target'],host.clock());old=p['previous_plan'];op=old['operation_id'];pin=digest(old);ledger=host.ledger
    require(p['project_operation_id']==host.config['project_operation_id'],'stable project lineage mismatch')
    _completed(ledger,op,'product_bootstrap',dict(plan_sha256=pin))
    action=p['previous_action'];control='product-control:'+op+':';payload=dict(plan_sha256=pin,config_sha256=p['previous_control_sha256'])
    adopted=_completed(ledger,control+'activate','product_control',dict(payload,action='activate'))
    require(adopted.get('verified') is True and adopted.get('phase')=='native_candidate_open' and adopted.get('identity')==old['candidate'],'completed original adoption identity required')
    if action=='activate':
        require(ledger.get(control+'rollback') is None,'previous return intent must be settled');identity=old['candidate']
    else:
        returned=_completed(ledger,control+'rollback','product_control',dict(payload,action='rollback'));identity=returned.get('identity')
        images={('python' if v['service'] in ('api','worker') else v['service']):v['image_id'] for v in old['legacy']['containers']}
        require(returned.get('verified') is True and returned.get('phase')=='native_legacy_return' and isinstance(identity,dict) and set(identity)==set(old['candidate']) and identity['deployment_id']=='rollback-'+op and identity['owner']=='pi-rollback-'+op and type(identity['generation']) is int and identity['generation']==old['candidate']['generation']+1 and identity['image_ids']==images and identity['commit_sha']==old['legacy']['source_commit'] and identity['schema_id']==old['candidate']['schema_id'] and identity['schema_version']==1 and hash_value(identity['config_hash']),'completed original return identity required')
    require(all(host.plan['previous'][k]==identity[k] for k in ('deployment_id','generation','owner','image_ids')),'current previous generation mismatch')
    def cohort(role):
        parent=('candidate:' if role=='candidate' else 'rollback-cohort:')+op;rows=[]
        image=old['candidate']['image_ids']['python'] if role=='candidate' else next(v['image_id'] for v in old['legacy']['containers'] if v['service']=='api')
        for source in sorted((v for v in old['legacy']['containers'] if v['service'] in ('api','worker')),key=lambda v:v['id']):
            child=_completed(ledger,parent+':'+source['id'],'product_cohort_container',dict(plan_sha256=pin,context_sha256=p['previous_context_sha256'],role=role,source_id=source['id']))
            require(hash_value(child.get('id')),'historical physical container receipt missing');rows.append(dict(id=child['id'],service=source['service'],image_id=image))
        saved=_completed(ledger,parent,'product_candidate' if role=='candidate' else 'product_rollback_cohort',dict(plan_sha256=pin))
        packet=dict(schema='pi-product-candidate-cohort-v1' if role=='candidate' else 'pi-product-rollback-cohort-v1',plan_sha256=pin,containers=rows)
        require(saved.get('cohort_sha256')==digest(packet),'historical cohort hash mismatch');return rows
    candidate=cohort('candidate');current=candidate if action=='activate' else cohort('rollback')
    retired=[v for v in old['legacy']['containers'] if v['service'] in ('api','worker')]+([] if action=='activate' else candidate)
    require(sorted(current,key=lambda v:v['id'])==sorted(p['current_cohort'],key=lambda v:v['id']) and sorted(retired,key=lambda v:v['id'])==sorted(p['retired'],key=lambda v:v['id']),'retirement roster lacks original receipt binding')
    return dict(identity=deepcopy(identity),current=deepcopy(current),retired=sorted(deepcopy(retired),key=lambda v:v['id']))


def census(host,removed=()):
    host.authorize(host.plan);proof=history(host);removed=set(removed)
    require(removed<={v['id'] for v in proof['retired']},'foreign retirement progress')
    require(host._json(['info','--format','{{json .}}']).get('ID')==host.config['daemon_id'],'retirement Docker daemon drift')
    raw=host._bytes(host._run(['ps','--all','--no-trunc','--filter','label=com.docker.compose.project='+host.config['project'],'--format','{{.ID}}']));ids=raw.decode().splitlines()
    expected={v['id']:v for v in host.plan['legacy']['containers']+proof['retired'] if v['id'] not in removed}
    require(len(ids)==len(set(ids)) and len(ids)<=16 and set(ids)==set(expected),'unknown or missing retirement container')
    rows=host._json(['inspect',*ids]);require(isinstance(rows,list) and len(rows)==len(ids) and {v.get('Id') for v in rows}==set(ids),'complete retirement inspect required')
    current={v['id'] for v in proof['current']};retired={v['id'] for v in proof['retired']}
    from .product_activation import environment
    from .audit import strict_json
    identity=proof['identity']
    for row in rows:
        old=expected[row['Id']];labels=row['Config']['Labels'];state=row['State']
        require(row['Image']==old['image_id'] and labels.get('com.docker.compose.project')==host.config['project'] and labels.get('com.docker.compose.service')==SERVICES[old['service']] and type(state['Running']) is bool and type(state['ExitCode']) is int and state['OOMKilled'] is False,'retirement container identity changed')
        require((not state['Running'] and state['ExitCode']==0) if row['Id'] in retired else state['Running'],'retirement requires naturally stopped old backends and running current product')
        if row['Id'] in current:
            env=environment(row['Config']['Env']);fields=dict(DEPLOYMENT_ID=identity['deployment_id'],DEPLOYMENT_GENERATION=str(identity['generation']),DEPLOYMENT_OWNER=identity['owner'],DEPLOYMENT_COMMIT_SHA=identity['commit_sha'],OBSERVATION_SCHEMA_ID=identity['schema_id'],OBSERVATION_CONFIG_ID=identity['config_hash'])
            require(all(env.get(k)==v for k,v in fields.items()) and strict_json(env.get('DEPLOYMENT_IMAGE_IDS','null'))==identity['image_ids'],'previous backend effective identity drift')
    actual=host._json(['exec',next(v['id'] for v in host.plan['legacy']['containers'] if v['service']=='postgres'),'psql','-X','-q','-A','-t','-w','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c','BEGIN READ ONLY;SET LOCAL statement_timeout=3000;SELECT row_to_json(m) FROM public.maintenance_control m WHERE id=1;ROLLBACK;'])
    previous=host.plan['previous'];require(isinstance(actual,dict) and set(actual)==set(previous) and all(type(actual[k]) is type(previous[k]) and actual[k]==previous[k] for k in previous if k!='deadline') and utc(actual['deadline'])==utc(previous['deadline']),'previous PostgreSQL owner or barrier drift')
    return proof


def retire(host):
    require(getattr(host,'rollback_lease',None) is None,'rollback lease cannot retire history')
    if host.config['mode']=='ACTUAL':
        from .product_runtime import LinuxProductHost
        require(type(host) is LinuxProductHost,'canonical retirement host required')
    host.authorize(host.plan);proof=history(host);op='retire-previous:'+host.plan['operation_id'];payload=dict(plan_sha256=digest(host.plan),lineage_sha256=host.lineage_pin)
    previous=host.ledger.get(op)
    if previous is not None:
        host.ledger.intent(op,'product_retirement',payload)
        return Receipt(op,'uncertain',dict(reason='unfinished_retirement_requires_reconciliation')) if previous['status']=='pending' else Receipt(op,previous['status'],previous['evidence'])
    census(host);host.ledger.intent(op,'product_retirement',payload);removed=[];child=None
    try:
        for row in proof['retired']:
            child=op+':'+row['id'];host.ledger.intent(child,'product_retirement_container',dict(payload,container=row))
            census(host,removed);host._run(['rm',row['id']]);removed.append(row['id']);census(host,removed)
            host.ledger.finish(Receipt(child,'done',dict(verified=True,removed_id=row['id'])));child=None
        result=Receipt(op,'done',dict(verified=True,phase='previous_backends_retired',removed_ids=removed,model_requests=0));host.ledger.finish(result);return result
    except Exception as error:
        evidence=dict(reason='retirement_outcome_unconfirmed',error_class=type(error).__name__,model_requests=0)
        if child is not None:host.ledger.finish(Receipt(child,'uncertain',evidence))
        result=Receipt(op,'uncertain',evidence);host.ledger.finish(result);return result
