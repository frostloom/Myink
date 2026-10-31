"""Historical ownership must prove every retired container; use real SQLite."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
import importlib.util,uuid
import pytest
from ops.pi.audit import digest
from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger
from test_product_bootstrap import case as bootstrap_case,NOW


def api():
    assert importlib.util.find_spec('ops.pi.product_lineage'),'missing historical cohort authority'
    from ops.pi import product_lineage
    return product_lineage


@pytest.fixture
def lineage_case(bootstrap_case,tmp_path):
    _,original,_=bootstrap_case
    def build(fault=None,ledger=None):
        old=deepcopy(original);new=deepcopy(old);new.update(schema='pi-product-upgrade-v2',operation_id=str(uuid.uuid4()))
        current=[dict(id=hex(i)[2:]*64,service=s,image_id=old['candidate']['image_ids']['python']) for i,s in zip((8,9,10),('api','worker','worker'))]
        previous=dict(id=1,epoch=old['operation_id'],deployment_id=old['candidate']['deployment_id'],generation=1,owner=old['candidate']['owner'],image_ids=deepcopy(old['candidate']['image_ids']),deadline=old['expires_at'],admission_closed=False,consumer_blocked=False)
        new['previous']=previous;new['legacy'].update(source_commit=old['candidate']['commit_sha'],containers=[deepcopy(v) for v in old['legacy']['containers'] if v['service'] not in ('api','worker')]+deepcopy(current));new['candidate'].update(generation=2,deployment_id='next-generation')
        retired=sorted([deepcopy(v) for v in old['legacy']['containers'] if v['service'] in ('api','worker')],key=lambda v:v['id'])
        packet=dict(schema='pi-product-lineage-v1',mode='SIMULATED',target='rehearsal',authority='owned_rehearsal',approved_action='retire_previous',next_plan_sha256=digest(new),project_operation_id=old['operation_id'],previous_plan=old,previous_action='activate',previous_context_sha256='e'*64,previous_control_sha256='d'*64,current_cohort=current,retired=retired,expires_at=new['expires_at'])
        folder=tmp_path/str(uuid.uuid4());folder.mkdir();ledger=ledger or Ledger(folder/'control.sqlite')
        def done(op,kind,payload,evidence,status='done'):
            ledger.intent(op,kind,payload)
            if status!='pending':ledger.finish(Receipt(op,status,evidence))
        op=old['operation_id'];pin=digest(old)
        done(op,'product_bootstrap',dict(plan_sha256=pin),dict(phase='protocol_prepared'))
        control='product-control:'+op+':activate'
        done(control,'product_control',dict(plan_sha256=pin,config_sha256=packet['previous_control_sha256'],action='activate'),dict(verified=True,phase='native_candidate_open',identity=old['candidate']),status='pending' if fault=='pending-adoption' else 'done')
        if fault=='pending-return':ledger.intent('product-control:'+op+':rollback','product_control',dict(plan_sha256=pin,config_sha256=packet['previous_control_sha256'],action='rollback'))
        cohort=dict(schema='pi-product-candidate-cohort-v1',plan_sha256=pin,containers=current)
        done('candidate:'+op,'product_candidate',dict(plan_sha256=pin),dict(cohort_sha256=digest(cohort)))
        sources=[v for v in old['legacy']['containers'] if v['service'] in ('api','worker')]
        for source,row in zip(sources,current):
            done('candidate:'+op+':'+source['id'],'product_cohort_container',dict(plan_sha256=pin,context_sha256='f'*64 if fault=='context-drift' else packet['previous_context_sha256'],role='candidate',source_id=source['id']),dict(id=row['id']),status='pending' if fault=='pending-container' else 'done')
        project='myink-pi-rehearsal-'+old['operation_id'];effects=[];rows={}
        identity=old['candidate'];environment=dict(DEPLOYMENT_ID=identity['deployment_id'],DEPLOYMENT_GENERATION=str(identity['generation']),DEPLOYMENT_OWNER=identity['owner'],DEPLOYMENT_IMAGE_IDS=__import__('json').dumps(identity['image_ids'],separators=(',',':'),sort_keys=True),DEPLOYMENT_COMMIT_SHA=identity['commit_sha'],OBSERVATION_SCHEMA_ID=identity['schema_id'],OBSERVATION_CONFIG_ID=identity['config_hash'])
        aliases=dict(api='myink-api',worker='myink-worker',frontend='myink-caddy',postgres='myink-pg',redis='myink-redis',rabbitmq='myink-rabbitmq')
        for row in new['legacy']['containers']+retired:
            rows[row['id']]=dict(Id=row['id'],Image=row['image_id'],Config=dict(Labels={'com.docker.compose.project':project,'com.docker.compose.service':aliases[row['service']]},Env=[k+'='+v for k,v in environment.items()]),State=dict(Running=row not in retired,ExitCode=0,OOMKilled=False))
        host=SimpleNamespace(plan=new,config=dict(mode='SIMULATED',target='rehearsal',project=project,project_operation_id=old['operation_id'],daemon_id='owned-daemon'),lineage=packet,lineage_pin=digest(packet),ledger=ledger,clock=lambda:NOW,rollback_lease=None,held=False)
        @contextmanager
        def lock(plan):
            assert not host.held;host.held=True
            try:yield
            finally:host.held=False
        def authorize(plan):assert host.held and plan==new
        def run(args,**kw):
            authorize(new)
            if args[0]=='ps':return ('\n'.join(rows)).encode()
            assert args[0]=='rm' and len(args)==2 and not rows[args[1]]['State']['Running']
            effects.append(list(args));del rows[args[1]];return b''
        def native(args):
            authorize(new)
            if args[0]=='info':return dict(ID='owned-daemon')
            if args[0]=='inspect':return [deepcopy(rows[c]) for c in args[1:]]
            assert args[0]=='exec' and 'row_to_json' in args[-1];return deepcopy(previous)
        host.authorize=authorize;host.lock=lock;host._run=run;host._bytes=lambda v:v;host._json=native
        return host,rows,effects,previous
    return build


def test_completed_adoption_proves_exact_retired_cohort_and_shared_history(lineage_case):
    h,rows,effects,_=lineage_case();m=api()
    assert m.validate(h.lineage,h.plan,h.config['target'],h.clock())==h.lineage
    proof=m.history(h);assert proof['retired']==h.lineage['retired']
    with h.lock(h.plan):
        result=m.retire(h);assert result.status=='done'
        assert m.retire(h)==result
    assert effects==[['rm',v['id']] for v in h.lineage['retired']]
    assert set(rows)=={v['id'] for v in h.plan['legacy']['containers']}
    assert h.ledger.get('product-control:'+h.lineage['previous_plan']['operation_id']+':activate')['status']=='done'


@pytest.mark.parametrize('field,value',[('approved_action','activate'),('next_plan_sha256','0'*64),('previous_action','shell'),('authority','model'),('expires_at','2020-01-01T00:00:00+00:00'),('current_cohort',[]),('retired',[])])
def test_closed_lineage_packet_rejects_wrong_scope(lineage_case,field,value):
    h,*_=lineage_case();h.lineage[field]=value
    with pytest.raises(ValueError):api().validate(h.lineage,h.plan,h.config['target'],h.clock())


@pytest.mark.parametrize('fault',['pending-adoption','pending-return','context-drift','pending-container'])
def test_unsettled_or_unbound_history_never_deletes(lineage_case,fault):
    h,rows,effects,_=lineage_case(fault)
    with h.lock(h.plan):
        with pytest.raises(ValueError):api().retire(h)
    assert not effects and h.ledger.get('retire-previous:'+h.plan['operation_id']) is None


@pytest.mark.parametrize('fault',['running-retired','bad-exit','oom','unknown-container','owner-drift','environment-drift'])
def test_current_census_or_owner_drift_prevents_retirement_intent(lineage_case,fault):
    h,rows,effects,previous=lineage_case();cid=h.lineage['retired'][0]['id']
    if fault=='running-retired':rows[cid]['State']['Running']=True
    elif fault=='bad-exit':rows[cid]['State']['ExitCode']=137
    elif fault=='oom':rows[cid]['State']['OOMKilled']=True
    elif fault=='unknown-container':rows['f'*64]=deepcopy(rows[cid]);rows['f'*64]['Id']='f'*64
    elif fault=='owner-drift':previous['owner']='manual-release'
    else:rows[h.lineage['current_cohort'][0]['id']]['Config']['Env']=['DEPLOYMENT_OWNER=manual']
    with h.lock(h.plan):
        with pytest.raises(ValueError):api().retire(h)
    assert not effects and h.ledger.get('retire-previous:'+h.plan['operation_id']) is None


def test_uncertain_removal_is_not_replayed(lineage_case):
    h,_,effects,_=lineage_case();run=h._run
    def fail(args,**kw):
        if args[0]=='rm':raise TimeoutError('unknown removal result')
        return run(args,**kw)
    h._run=fail
    with h.lock(h.plan):
        first=api().retire(h);assert first.status=='uncertain'
        assert api().retire(h)==first
    assert not effects
