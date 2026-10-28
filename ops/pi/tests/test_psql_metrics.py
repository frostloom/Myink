"""Only fixed, bounded host SQL reaches the metadata role."""
from datetime import datetime,timezone,timedelta
import importlib
import json
import subprocess
import pytest
from ops.pi.metrics import _PROJECTIONS


def api():return importlib.import_module('ops.pi.psql_metrics')


@pytest.fixture
def config():
    return dict(docker='/usr/bin/docker',endpoint='unix:///var/run/docker.sock',daemon_id='daemon-test',container_id='a'*64,image_id='sha256:'+'b'*64,database='myink',database_user='myink',view_sha256='c'*64)


@pytest.fixture
def metric_request():
    start=datetime(2026,10,28,tzinfo=timezone.utc)
    cohort='SELECT COALESCE(batch_task_id, id) FROM tasks WHERE created_at >= :start AND created_at < :end'
    return dict(source='tasks',sql=f"SELECT {_PROJECTIONS['tasks']} FROM tasks WHERE id IN ({cohort}) OR batch_task_id IN ({cohort}) ORDER BY created_at, id LIMIT :limit OFFSET :offset",params=dict(start=start,end=start+timedelta(hours=1),limit=500,offset=0),read_only=True,timeout_ms=5000)


def metadata(config):
    return dict(role='myink_pi_metrics',superuser=False,create_db=False,create_role=False,replication=False,bypass_rls=False,inherit=False,login=False,readonly='on',raw_privileges=False,memberships=0,view_count=2,view_sha256=config['view_sha256'])


class Runner:
    def __init__(self,config,rows=None,meta=None):self.config=config;self.rows=rows or [];self.meta=meta or metadata(config);self.calls=[]
    def __call__(self,args,**kwargs):
        self.calls.append((args,kwargs));c=self.config
        if 'info' in args:out=c['daemon_id']+'\n'
        elif 'inspect' in args:out=json.dumps(dict(id=c['container_id'],image=c['image_id'],running=True))
        else:out=json.dumps(self.meta)+'\n'+json.dumps(self.rows)+'\n'
        return subprocess.CompletedProcess(args,0,out.encode(),b'')


def test_fixed_transport_pins_source_and_uses_readonly_role(config,metric_request):
    runner=Runner(config);reader=api().PsqlMetricsReader(config,run=runner)
    assert reader(metric_request)==[] and len(runner.calls)==3
    args,kwargs=runner.calls[-1];query=kwargs['input'].decode()
    assert 'SET LOCAL ROLE myink_pi_metrics' in query and 'READ ONLY' in query
    assert "SET LOCAL search_path" in query and '5000' in query
    assert "LIMIT :'limit'::integer" in query
    assert '--no-psqlrc' in args and kwargs['timeout']<=10
    assert kwargs['env']['HOME']=='/nonexistent' and 'SCOPED_GATEWAY_TOKEN' not in kwargs['env']
    assert 'Config.Env' not in str(runner.calls)


@pytest.mark.parametrize('change',['sql','unknown_param','bool_limit','timeout','naive','source'])
def test_bad_request_refused_before_any_docker_operation(config,metric_request,change):
    if change=='sql':metric_request['sql']='SELECT * FROM public.users'
    elif change=='unknown_param':metric_request['params']['password']='private'
    elif change=='bool_limit':metric_request['params']['limit']=True
    elif change=='timeout':metric_request['timeout_ms']=5001
    elif change=='naive':metric_request['params']['start']=datetime(2026,10,28)
    else:metric_request['source']='feedback'
    runner=Runner(config)
    with pytest.raises(ValueError):api().PsqlMetricsReader(config,run=runner)(metric_request)
    assert runner.calls==[]


@pytest.mark.parametrize('field',['superuser','create_db','create_role','replication','bypass_rls','inherit','login','raw_privileges'])
def test_privileged_or_login_source_is_not_accepted(config,metric_request,field):
    meta=metadata(config);meta[field]=True
    with pytest.raises(ValueError):api().PsqlMetricsReader(config,run=Runner(config,meta=meta))(metric_request)


def test_source_or_view_drift_is_rejected(config,metric_request):
    class Drift(Runner):
        def __call__(self,args,**kwargs):
            output=super().__call__(args,**kwargs)
            if 'inspect' in args:output.stdout=json.dumps(dict(id='d'*64,image=self.config['image_id'],running=True)).encode()
            return output
    with pytest.raises(ValueError):api().PsqlMetricsReader(config,run=Drift(config))(metric_request)
    m=metadata(config);m['view_sha256']='d'*64
    with pytest.raises(ValueError):api().PsqlMetricsReader(config,run=Runner(config,meta=m))(metric_request)


def test_row_projection_converts_aware_time_and_rejects_body(config,metric_request):
    row=dict(id='t',status='done',task_type='chapter_generate',batch_task_id=None,chapter_seq=None,created_at='2026-10-28T00:00:00+00:00',updated_at='2026-10-28T00:00:05+00:00')
    result=api().PsqlMetricsReader(config,run=Runner(config,[row]))(metric_request)
    assert isinstance(result[0]['created_at'],datetime)
    row['private_body']='NEVER-EXPORT'
    with pytest.raises(ValueError):api().PsqlMetricsReader(config,run=Runner(config,[row]))(metric_request)


def test_bootstrap_sql_has_no_raw_detail_or_product_write_grants():
    sql=importlib.import_module('ops.pi.metrics_sql').metadata_bootstrap_sql()
    assert 'NOLOGIN' in sql and 'NOBYPASSRLS' in sql and 'NOINHERIT' in sql
    assert 'security_barrier=true' in sql and 'GRANT SELECT ON pi_metrics.tasks, pi_metrics.agent_runs' in sql
    assert 'GRANT SELECT ON public.' not in sql and 'CREATE OR REPLACE' not in sql
    assert 'private_body' not in sql and 'SELECT *' not in sql and 'AS detail' in sql


def test_quoted_task_parameter_is_bound_as_data(config,metric_request):
    value="x'); DELETE FROM public.users; --"
    metric_request['source']='agent_runs'
    metric_request['sql']=f"SELECT {_PROJECTIONS['agent_runs']} FROM agent_runs WHERE created_at < :end AND task_id IN (:thread_0) ORDER BY created_at, id LIMIT :limit OFFSET :offset"
    metric_request['params']['thread_0']=value
    run=Runner(config);assert api().PsqlMetricsReader(config,run=run)(metric_request)==[]
    args,options=run.calls[-1]
    assert 'thread_0='+value in args and value not in options['input'].decode()
    assert ":'thread_0'" in options['input'].decode()


def test_timeout_and_oversized_output_are_rejected(config,metric_request):
    def timeout(*args,**kwargs):raise subprocess.TimeoutExpired(args[0],10)
    with pytest.raises(ValueError,match='unavailable'):api().PsqlMetricsReader(config,run=timeout)(metric_request)
    def oversized(args,**kwargs):return subprocess.CompletedProcess(args,0,b'x'*4194305,b'')
    with pytest.raises(ValueError,match='byte bound'):api().PsqlMetricsReader(config,run=oversized)(metric_request)


@pytest.mark.parametrize('field,value',[('memberships',False),('view_count',2.0),('readonly',False),('raw_body','private')])
def test_malformed_role_metadata_is_rejected(config,metric_request,field,value):
    meta=metadata(config);meta[field]=value
    with pytest.raises(ValueError):api().PsqlMetricsReader(config,run=Runner(config,meta=meta))(metric_request)
