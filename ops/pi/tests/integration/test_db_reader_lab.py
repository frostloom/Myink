"""Actual fixed SQL projections and database-enforced SELECT/timeout bounds."""
from datetime import datetime, timezone, timedelta
import os
import uuid
import pytest
from sqlalchemy import create_engine, text
from ops.pi.contracts import Identity
from ops.pi.db_reader import SnapshotCollector

pytestmark = pytest.mark.pi_lab

@pytest.fixture
def metric_engine():
    from ops.pi.lab.verify import verify_test_environment
    _,environment=verify_test_environment()
    admin = create_engine(environment['ADMIN_DATABASE_URL'])
    with admin.begin() as c:
        c.execute(text('CREATE SCHEMA IF NOT EXISTS pi_metrics'))
        c.execute(text("DO $$ BEGIN CREATE ROLE pi_b7_metrics LOGIN PASSWORD 'synthetic-metrics-only' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$"))
        c.execute(text('CREATE OR REPLACE VIEW pi_metrics.tasks AS SELECT id, status, task_type, batch_task_id, chapter_seq, created_at, updated_at FROM public.tasks'))
        c.execute(text("CREATE OR REPLACE VIEW pi_metrics.agent_runs AS SELECT id, task_id, node, model_id, input_tokens, output_tokens, cost_est, duration_ms, created_at, jsonb_build_object('run_provenance', detail->'run_provenance', 'measurement', detail->'measurement', 'observation_collision',detail->'observation_collision') AS detail FROM public.agent_runs"))
        c.execute(text('GRANT USAGE ON SCHEMA pi_metrics TO pi_b7_metrics'))
        c.execute(text('GRANT SELECT ON pi_metrics.tasks, pi_metrics.agent_runs TO pi_b7_metrics'))
        c.execute(text("ALTER ROLE pi_b7_metrics SET default_transaction_read_only=on"))
        c.execute(text("ALTER ROLE pi_b7_metrics SET statement_timeout='5s'"))
        c.execute(text("ALTER ROLE pi_b7_metrics SET search_path=pi_metrics,pg_catalog"))
    from sqlalchemy.engine import make_url
    url = make_url(environment['ADMIN_DATABASE_URL']).set(username='pi_b7_metrics',password='synthetic-metrics-only')
    engine = create_engine(url)
    yield admin,engine
    engine.dispose(); admin.dispose()


def test_actual_collector_projection_sql_and_readonly_role(metric_engine):
    admin,engine = metric_engine
    now=datetime.now(timezone.utc)
    from sqlalchemy.orm import Session
    from myink.models import User,Project,Task,AgentRun
    with Session(admin) as db:
        user=User(username='pi-metrics-'+uuid.uuid4().hex[:8]);db.add(user);db.flush()
        project=Project(user_id=user.id,title='synthetic B7');db.add(project);db.flush()
        task=Task(project_id=project.id,task_type='chapter_generate',status='done',created_at=now-timedelta(seconds=5),updated_at=now-timedelta(seconds=1));db.add(task);db.flush()
        db.add(AgentRun(project_id=project.id,task_id=str(task.id),node='persist',role='deterministic',
                       input_tokens=0,output_tokens=0,cost_est=0,duration_ms=5,created_at=now-timedelta(seconds=2),
                       detail={'private_body':'NEVER-PROJECT-BODY','run_provenance':{'deployment_id':'b7','generation':1,'owner':'pi','schema_id':'s','config_id':'c','prompt_id':'p','rubric_id':'r','data_id':'d','image_ids':{'worker':'synthetic'}},
                               'measurement':{'kind':'deterministic','zero_cost':True,'cost':True,'latency':True}}))
        db.commit()
        owned_user=user.id; owned_project=project.id
    result=SnapshotCollector(engine).collect({'id':'b7-actual','start':now-timedelta(hours=1),'end':now+timedelta(hours=1),
                                            'evidence_domain':'synthetic'}, Identity('b7',1,'pi',{'worker':'synthetic'}))
    assert result['id']=='b7-actual' and result['evidence_domain']=='synthetic'
    assert result['completed']==1 and result['measurements']['cost']['value']==0
    assert result['measurements']['node_time']['value']==5
    assert 'NEVER-PROJECT-BODY' not in str(result)
    with admin.begin() as c:
        c.execute(text('DELETE FROM public.projects WHERE id=:id'),{'id':owned_project})
        c.execute(text('DELETE FROM public.users WHERE id=:id'),{'id':owned_user})
    # No arbitrary direct raw table or write rights, even outside the Python validator.
    with engine.connect() as c:
        assert c.execute(text('SHOW statement_timeout')).scalar() == '5s'
        assert c.execute(text('SHOW default_transaction_read_only')).scalar() == 'on'
    for sql in ('SELECT * FROM public.users', 'SELECT * FROM public.agent_runs', "CREATE TABLE forbidden(x int)", 'DELETE FROM pi_metrics.tasks'):
        with engine.connect() as c:
            with pytest.raises(Exception):
                c.execute(text(sql))
    with engine.connect() as c:
        with pytest.raises(Exception, match='statement timeout'):
            c.execute(text('SELECT pg_sleep(6)'))


def test_privileged_reader_role_rejected(metric_engine):
    admin,_=metric_engine
    now=datetime.now(timezone.utc)
    with pytest.raises(ValueError,match='privileged'):
        SnapshotCollector(admin).collect({'id':'blocked','start':now-timedelta(hours=1),'end':now+timedelta(hours=1)},Identity('b7',1,'pi',{}))
