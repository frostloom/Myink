"""Owned standalone PG16 proof; never uses the product or fixed myink-test DB."""
from datetime import datetime,timezone,timedelta
import json
import os
import shutil
from pathlib import Path
import subprocess
import time
import uuid
import pytest
from ops.pi.metrics_sql import metadata_bootstrap_sql,metadata_probe_sql
from ops.pi.psql_metrics import PsqlMetricsReader
from ops.pi.metrics import _PROJECTIONS

pytestmark=pytest.mark.pi_observer_pg
DOCKER=Path(shutil.which('docker') or '/Applications/Docker.app/Contents/Resources/bin/docker')
IMAGE='pgvector/pgvector@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a'


@pytest.fixture(scope='module')
def database():
    assert DOCKER.is_file(),'explicit native PG test requires its Docker client'
    socket=Path.home()/'.docker/run/docker.sock'
    endpoint=os.environ.get('MYINK_PI_TEST_DOCKER_ENDPOINT','unix://'+str(socket) if socket.exists() else 'unix:///var/run/docker.sock')
    assert endpoint.startswith('unix:///'),'native test accepts only a local Unix daemon'
    operation=uuid.uuid4().hex
    prefix=[str(DOCKER),'--host',endpoint]
    def call(*args,input=None,check=True):
        result=subprocess.run([*prefix,*args],input=input,text=True,capture_output=True,timeout=15)
        if check and result.returncode:raise RuntimeError(result.stderr[:1000])
        return result
    image_id=call('image','inspect',IMAGE,'--format','{{.Id}}').stdout.strip()
    daemon=call('info','--format','{{.ID}}').stdout.strip()
    container=None
    proof_root=Path.cwd()/'.local/pi-live-observer-20261028/pg-tests'/operation
    proof_root.mkdir(mode=0o700,parents=True)
    proof=proof_root/'ownership.json'
    proof.write_text(json.dumps(dict(operation=operation,daemon_id=daemon,image_id=image_id,status='intent')))
    proof.chmod(0o600)
    def sql(query,check=True):
        return call('exec','-i',container,'psql','-X','--no-psqlrc','-U','postgres','-d','pi_observer_test','-A','-t','-q','--set=ON_ERROR_STOP=1',input=query,check=check)
    try:
        container=call('run','-d','--network','none','--memory','512m','--cpus','1','--pids-limit','128','--tmpfs','/var/lib/postgresql/data:rw,size=256m','--label','myink.pi.test='+operation,'--env','POSTGRES_PASSWORD=synthetic-observer-test-only','--env','POSTGRES_DB=pi_observer_test',IMAGE).stdout.strip()
        assert len(container)==64
        proof.write_text(json.dumps(dict(operation=operation,daemon_id=daemon,image_id=image_id,container_id=container,status='created')))
        deadline=time.monotonic()+45
        while call('exec',container,'pg_isready','-h','127.0.0.1','-U','postgres','-d','pi_observer_test',check=False).returncode:
            if time.monotonic()>=deadline:raise RuntimeError('isolated PG startup deadline')
            time.sleep(.2)
        sql('''CREATE TABLE public.users(id int,private_body text);
CREATE TABLE public.tasks(id uuid PRIMARY KEY,status text,task_type text,batch_task_id uuid,chapter_seq int,created_at timestamptz,updated_at timestamptz);
CREATE TABLE public.agent_runs(id int,task_id text,node text,model_id text,input_tokens int,output_tokens int,cost_est double precision,duration_ms int,created_at timestamptz,detail json);
INSERT INTO public.users VALUES(1,'private-user-body-never-visible');''')
        metadata=json.loads(sql(metadata_bootstrap_sql()).stdout)
        config=dict(docker=str(DOCKER),endpoint=endpoint,daemon_id=daemon,container_id=container,image_id=image_id,database='pi_observer_test',database_user='postgres',view_sha256=metadata['view_sha256'])
        yield config,sql
    finally:
        assert call('info','--format','{{.ID}}').stdout.strip()==daemon,'test cleanup daemon drift'
        owned=call('ps','-aq','--no-trunc','--filter','label=myink.pi.test='+operation).stdout.split()
        for cid in owned:
            log=call('logs','--tail','2000',cid,check=False)
            target=proof_root/(cid+'-container.log');target.write_text(log.stdout+log.stderr);target.chmod(0o600)
            assert len(cid)==64
            label=call('inspect','--format','{{index .Config.Labels "myink.pi.test"}}',cid).stdout.strip()
            assert label==operation,'test cleanup ownership drift'
            call('rm','--force',cid)
        assert not call('ps','-aq','--filter','label=myink.pi.test='+operation).stdout.strip()
        proof.write_text(json.dumps(dict(operation=operation,daemon_id=daemon,image_id=image_id,container_ids=owned,status='removed',removed=True)))



def query(source,start,end,**params):
    cohort='SELECT COALESCE(batch_task_id, id) FROM tasks WHERE created_at >= :start AND created_at < :end'
    where=f'id IN ({cohort}) OR batch_task_id IN ({cohort})' if source=='tasks' else 'created_at < :end AND task_id IN (:thread_0)'
    return dict(source=source,sql=f'SELECT {_PROJECTIONS[source]} FROM {source} WHERE {where} ORDER BY created_at, id LIMIT :limit OFFSET :offset',params=dict(start=start,end=end,limit=500,offset=0,**params),read_only=True,timeout_ms=5000)


def test_actual_views_filter_body_and_fixed_transport_reads_only_metadata(database):
    config,sql=database;now=datetime.now(timezone.utc);task=str(uuid.uuid4())
    detail=json.dumps(dict(private_body='private-run-body-never-visible',run_provenance=dict(deployment_id=dict(value='nested-private-never-visible')),measurement=dict(kind='deterministic',zero_cost=True,cost=True,latency=True))).replace("'","''")
    sql(f"INSERT INTO public.tasks VALUES('{task}','done','chapter_generate',NULL,NULL,now()-interval '2 minutes',now()-interval '1 minute'); INSERT INTO public.agent_runs VALUES(1,'{task}','persist',NULL,0,0,0,5,now()-interval '1 minute','{detail}'::json);")
    direct=json.loads(sql('BEGIN READ ONLY; SET LOCAL ROLE myink_pi_metrics; SET LOCAL search_path=pi_metrics,pg_catalog; '+metadata_probe_sql()+' ROLLBACK;').stdout)
    assert direct['view_sha256']==config['view_sha256'],'same view must have the same approved fingerprint'
    reader=PsqlMetricsReader(config)
    tasks=reader(query('tasks',now-timedelta(hours=1),now+timedelta(hours=1)))
    runs=reader(query('agent_runs',now-timedelta(hours=1),now+timedelta(hours=1),thread_0=task))
    assert len(tasks)==len(runs)==1 and isinstance(tasks[0]['created_at'],datetime)
    assert runs[0]['measurement']['zero_cost'] is True
    assert runs[0]['provenance']['deployment_id'] is None
    assert 'private-' not in json.dumps(runs,default=str)
    role=sql("SELECT rolcanlogin,rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls,rolinherit FROM pg_roles WHERE rolname='myink_pi_metrics';").stdout.strip()
    assert role=='f|f|f|f|f|f|f'


@pytest.mark.parametrize('statement',['SELECT private_body FROM public.users','SELECT detail FROM public.agent_runs',"UPDATE public.tasks SET status='failed'",'CREATE TABLE public.forbidden(x int)'])
def test_actual_role_denies_direct_product_reads_and_writes(database,statement):
    _,sql=database
    result=sql('BEGIN READ ONLY; SET LOCAL ROLE myink_pi_metrics; '+statement+'; ROLLBACK;',check=False)
    assert result.returncode!=0 and ('permission denied' in result.stderr or 'read-only transaction' in result.stderr)


def test_actual_query_timeout_and_widened_role_detection(database):
    config,sql=database
    result=sql('BEGIN READ ONLY; SET LOCAL ROLE myink_pi_metrics; SET LOCAL statement_timeout=100; SELECT pg_sleep(1); ROLLBACK;',check=False)
    assert result.returncode!=0 and 'statement timeout' in result.stderr
    now=datetime.now(timezone.utc)
    sql('GRANT SELECT ON public.users TO myink_pi_metrics;')
    try:
        with pytest.raises(ValueError,match='role/view'):PsqlMetricsReader(config)(query('tasks',now-timedelta(hours=1),now+timedelta(hours=1)))
    finally:sql('REVOKE SELECT ON public.users FROM myink_pi_metrics;')


def test_duplicate_install_refuses_without_overwriting_known_views(database):
    config,sql=database
    result=sql(metadata_bootstrap_sql(),check=False)
    assert result.returncode!=0 and 'already exists' in result.stderr
    now=datetime.now(timezone.utc)
    assert isinstance(PsqlMetricsReader(config)(query('tasks',now-timedelta(hours=1),now+timedelta(hours=1))),list)


def test_view_fingerprint_detects_column_type_drift(database):
    config,sql=database
    original=sql("SELECT pg_get_viewdef('pi_metrics.tasks'::regclass,true);").stdout.strip()
    def change(kind):
        sql('DROP VIEW pi_metrics.tasks; ALTER TABLE public.tasks ALTER COLUMN chapter_seq TYPE '+kind+'; CREATE VIEW pi_metrics.tasks WITH (security_barrier=true) AS '+original+' GRANT SELECT ON pi_metrics.tasks TO myink_pi_metrics;')
    change('bigint')
    try:
        now=datetime.now(timezone.utc)
        with pytest.raises(ValueError,match='role/view'):PsqlMetricsReader(config)(query('tasks',now-timedelta(hours=1),now+timedelta(hours=1)))
    finally:change('integer')


def test_unknown_schema_conflict_rolls_back_role_and_preserves_existing_objects(database):
    config,sql=database
    sql('DROP VIEW pi_metrics.tasks; DROP VIEW pi_metrics.agent_runs; DROP SCHEMA pi_metrics; DROP ROLE myink_pi_metrics; CREATE SCHEMA pi_metrics; CREATE TABLE pi_metrics.keep_marker(value int); INSERT INTO pi_metrics.keep_marker VALUES(42);')
    try:
        result=sql(metadata_bootstrap_sql(),check=False)
        assert result.returncode!=0 and 'already exists' in result.stderr
        assert sql("SELECT count(*) FROM pg_roles WHERE rolname='myink_pi_metrics';").stdout.strip()=='0'
        assert sql('SELECT value FROM pi_metrics.keep_marker;').stdout.strip()=='42'
    finally:
        sql('DROP TABLE pi_metrics.keep_marker; DROP SCHEMA pi_metrics;')
        restored=json.loads(sql(metadata_bootstrap_sql()).stdout)
        assert restored['view_sha256']==config['view_sha256']


def test_actual_psql_parameter_quoting_cannot_inject_sql(database):
    config,sql=database;now=datetime.now(timezone.utc)
    value="x'); DELETE FROM public.users; --"
    assert PsqlMetricsReader(config)(query('agent_runs',now-timedelta(hours=1),now+timedelta(hours=1),thread_0=value))==[]
    assert sql('SELECT count(*) FROM public.users;').stdout.strip()=='1'


def test_credential_like_metadata_and_encoded_body_are_not_projected(database):
    config,sql=database;task=str(uuid.uuid4());now=datetime.now(timezone.utc)
    credential='sk-synthetic-secret-value-123456'
    detail=json.dumps(dict(run_provenance=dict(deployment_id=credential,schema_id=json.dumps(dict(password=dict(value='encoded-private-body')))),measurement=dict(kind='model',cost=True,latency=True))).replace("'","''")
    sql(f"INSERT INTO public.agent_runs VALUES(91,'{task}','write','{credential}',1,1,1,5,now()-interval '1 minute','{detail}'::json);")
    rows=PsqlMetricsReader(config)(query('agent_runs',now-timedelta(hours=1),now+timedelta(hours=1),thread_0=task))
    assert len(rows)==1
    assert credential not in json.dumps(rows,default=str) and 'encoded-private-body' not in json.dumps(rows,default=str)
    assert rows[0]['model_id'] is None and rows[0]['provenance']['deployment_id'] is None
