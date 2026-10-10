"""Maintenance closes intake before any Redis quota or task mutation."""
import importlib.util
import json
import uuid
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, select
from conftest import identity_headers
from myink.api.main import app
from myink.db import get_admin_engine, new_session
from myink.models import Project, User, Task
from myink.worker import enqueue as enq
from myink.worker.redis_client import get_redis, quota_key, inflight_key

pytestmark = pytest.mark.pi_lab

client = TestClient(app)

@pytest.fixture
def maintenance_control():
    from ops.pi.lab.verify import verify_test_environment
    verify_test_environment()
    if importlib.util.find_spec("myink.maintenance"):
        from myink.db import ensure_maintenance_schema
        ensure_maintenance_schema()
    else:
        # Baseline reproduction uses the real API with a closed persisted control.
        with get_admin_engine().begin() as c:
            c.execute(text("CREATE TABLE IF NOT EXISTS public.maintenance_control (id integer PRIMARY KEY CHECK(id=1), epoch varchar(64) NOT NULL, deployment_id varchar(128) NOT NULL, generation bigint NOT NULL, owner varchar(128) NOT NULL, deadline timestamptz, admission_closed boolean NOT NULL, consumer_blocked boolean NOT NULL)"))
            c.execute(text("INSERT INTO public.maintenance_control VALUES (1,'', 'initial',0,'bootstrap',NULL,false,false) ON CONFLICT DO NOTHING"))
    with get_admin_engine().begin() as c:
        c.execute(text("UPDATE public.maintenance_control SET epoch='b8-test', deployment_id='b8-synthetic', generation=8,owner='trusted-fixture',deadline='2026-10-12T06:00:00+08:00',admission_closed=true,consumer_blocked=true WHERE id=1"))
    try:
        yield
    finally:
        with get_admin_engine().begin() as c:
            c.execute(text("UPDATE public.maintenance_control SET admission_closed=false,consumer_blocked=false WHERE id=1"))

@pytest.fixture
def book(temp_project):
    with new_session() as db:
        project=db.get(Project,uuid.UUID(temp_project)); user=db.get(User,project.user_id)
    return temp_project,str(user.id),identity_headers(user)


def generate(book):
    pid,_,headers=book
    return client.post(f"/api/v1/projects/{pid}/chapters/{uuid.uuid4()}/generate",json={"seq":1},headers=headers)


def test_generate_and_resume_denied_during_maintenance(maintenance_control,book,monkeypatch):
    monkeypatch.setattr(enq.amqp,"publish",lambda *a,**k:None)
    tid=uuid.uuid4()
    with new_session() as db:
        db.add(Task(id=tid,project_id=uuid.UUID(book[0]),task_type="chapter_generate",status="paused",payload={"seq":1},error="user paused"));db.commit()
    responses=[generate(book),client.post(f"/api/v1/tasks/{tid}/resume",headers=book[2])]
    assert [r.status_code for r in responses]==[503,503]
    for response in responses:
        assert response.json()["code"]=="maintenance"
        assert response.json()["reopen_at"]=="2026-10-12T06:00:00+08:00"
        assert int(response.headers["Retry-After"])>=1
    with new_session() as db:
        task=db.get(Task,tid)
        assert (task.status,task.error)==("paused","user paused")


def test_no_quota_charge_before_admission(maintenance_control,book,monkeypatch):
    monkeypatch.setattr(enq.amqp,"publish",lambda *a,**k:None)
    r=get_redis();keys=[quota_key(book[1],date.today().isoformat()),inflight_key(book[1],book[0])]
    r.delete(*keys)
    try:
        response=generate(book)
        assert r.get(keys[0]) is None
        assert r.scard(keys[1])==0
        assert response.status_code==503
    finally:
        r.delete(*keys)


def test_db_unavailable_fails_closed(maintenance_control,book,monkeypatch):
    monkeypatch.setattr(enq.amqp,"publish",lambda *a,**k:None)
    with get_admin_engine().begin() as c:
        c.execute(text("ALTER TABLE public.maintenance_control RENAME TO maintenance_control_unavailable"))
    try:
        response=generate(book)
        assert response.status_code==503
        assert response.json()["code"]=="maintenance"
    finally:
        with get_admin_engine().begin() as c:
            c.execute(text("ALTER TABLE public.maintenance_control_unavailable RENAME TO maintenance_control"))


def test_plan_and_budget_wait_reasons_preserved(maintenance_control,book):
    from myink.task_budget import ensure_task_budget
    from myink.models.task_budget import TaskBudget
    tid=uuid.uuid4()
    with new_session() as db:
        db.add(Task(id=tid,project_id=uuid.UUID(book[0]),task_type="chapter_generate",status="awaiting_plan",payload={"seq":1},error="plan wait"));db.commit()
    confirm=client.post(f"/api/v1/tasks/{tid}/plan/confirm",json={"plan":{},"expected_attempt":0},headers=book[2])
    assert confirm.status_code==503
    with new_session() as db:
        task=db.get(Task,tid);assert (task.status,task.error)==("awaiting_plan","plan wait")
        task.status="paused";task.error="budget wait";db.commit()
    ensure_task_budget(str(tid),book[0],book[1],{"max_requests":2,"max_cost_yuan":5,"max_runtime_seconds":100})
    with get_admin_engine().begin() as c:
        c.execute(text("UPDATE task_budgets SET pause_reason='request_limit' WHERE task_id=:id"),{"id":tid})
    resume=client.post(f"/api/v1/tasks/{tid}/resume",json={"operation_id":str(uuid.uuid4()),"add_requests":5},headers=book[2])
    assert resume.status_code==503
    with new_session() as db:
        budget=db.get(TaskBudget,tid);task=db.get(Task,tid)
        assert budget.limits["max_requests"]==2 and budget.pause_reason=="request_limit"
        assert (task.status,task.error)==("paused","budget wait")


def test_intent_precedes_quota_and_preserves_unknown_publish(maintenance_control,book,monkeypatch):
    with get_admin_engine().begin() as c:c.execute(text("UPDATE maintenance_control SET admission_closed=false WHERE id=1"))
    r=get_redis();keys=[quota_key(book[1],date.today().isoformat()),inflight_key(book[1],book[0])];r.delete(*keys)
    original=enq._run_gates
    observed=[]
    def gates(*args,**kwargs):
        with get_admin_engine().connect() as c:
            row=c.execute(text("SELECT task_id,payload_hash,gate_state,publication_state,rebuild_payload FROM public.admission_intents WHERE task_id=:id"),{"id":uuid.UUID(kwargs["task_id"])}).mappings().one()
        observed.append(row)
        return original(*args,**kwargs)
    def uncertain(*args,**kwargs):raise RuntimeError("synthetic confirm disconnect")
    monkeypatch.setattr(enq,"_run_gates",gates);monkeypatch.setattr(enq.amqp,"publish",uncertain)
    try:
        response=generate(book)
        assert response.status_code==503
        assert len(observed)==1 and observed[0]["gate_state"]=="unknown"
        assert observed[0]["publication_state"]=="pending"
        with get_admin_engine().connect() as c:
            row=c.execute(text("SELECT * FROM public.admission_intents WHERE task_id=:id"),{"id":observed[0]["task_id"]}).mappings().one()
        assert row["gate_state"]=="accepted" and row["publication_state"]=="unknown"
        assert row["rebuild_payload"]["task_id"]==str(row["task_id"])
        assert row["rebuild_payload"]["trace_id"]==str(row["task_id"])
        assert row["payload_hash"]==observed[0]["payload_hash"]
        assert int(r.get(keys[0]))==1
    finally:r.delete(*keys)


def test_actual_pg_role_permissions_and_registration_close_race(maintenance_control,book):
    import threading,time
    from sqlalchemy.orm import Session
    from myink.maintenance import register_admission,require_admission_open,MaintenanceUnavailable
    from myink.db import ensure_maintenance_schema
    engine=get_admin_engine()
    with engine.begin() as c:
        for role in ("myink_app","myink_report"):
            c.execute(text(f"DO $$ BEGIN CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$"))
        c.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO myink_report"))
    ensure_maintenance_schema()
    for role in ("myink_app","myink_maintenance_control","myink_maintenance_stats"):
        with engine.connect() as c:
            flags=c.execute(text("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=:role"),{"role":role}).one()
            assert not any(flags)
    with engine.begin() as c:
        c.execute(text("SET LOCAL ROLE myink_app"))
        assert c.scalar(text("SELECT count(*) FROM public.myink_lock_maintenance()"))==1
        assert not c.scalar(text("SELECT has_table_privilege(current_user,'public.maintenance_control','UPDATE')"))
        assert not c.scalar(text("SELECT has_column_privilege(current_user,'public.maintenance_control','admission_closed','UPDATE')"))
    for role,sql in [("myink_app","UPDATE public.maintenance_control SET admission_closed=false"),
                     ("myink_maintenance_control","UPDATE public.tasks SET status='done'"),
                     ("myink_maintenance_control","CREATE TABLE public.b8_forbidden(x int)"),
                     ("myink_report","SELECT rebuild_payload FROM public.admission_intents"),
                     ("myink_maintenance_stats","SELECT rebuild_payload FROM public.admission_intents")]:
        with engine.connect() as c:
            c.execute(text(f"SET ROLE {role}"))
            with pytest.raises(Exception):c.execute(text(sql))
            c.rollback()
    with engine.begin() as c:
        c.execute(text("SET LOCAL ROLE myink_maintenance_stats"))
        assert c.scalar(text("SELECT count(*) FROM public.maintenance_admission_counts"))>=0
    with engine.begin() as c:c.execute(text("UPDATE public.maintenance_control SET admission_closed=false WHERE id=1"))
    started=threading.Event();closed=threading.Event();errors=[]
    def close():
        try:
            with engine.begin() as c:
                c.execute(text("SET LOCAL ROLE myink_maintenance_control"))
                started.set()
                c.execute(text("UPDATE public.maintenance_control SET admission_closed=true WHERE id=1"))
            closed.set()
        except BaseException as exc:errors.append(exc)
    with Session(engine) as db:
        db.execute(text("SET LOCAL ROLE myink_app"))
        db.execute(text("SELECT set_config('app.tenant_id', :pid, true)"),{"pid":book[0]})
        message={"task_id":str(uuid.uuid4()),"request_id":str(uuid.uuid4()),"project_id":book[0],"user_id":book[1],"payload":{"seq":1}}
        intent=register_admission(db,message,priority=0)
        thread=threading.Thread(target=close);thread.start();assert started.wait(2)
        until=time.monotonic()+2;waiting=False
        while time.monotonic()<until:
            with engine.connect() as c:waiting=bool(c.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE 'UPDATE public.maintenance_control SET admission_closed=true%'")))
            if waiting:break
            time.sleep(.02)
        assert waiting and not closed.is_set()
        db.commit()
    thread.join(3);assert closed.is_set() and not errors
    with Session(engine) as db:
        db.execute(text("SET LOCAL ROLE myink_app"))
        with pytest.raises(MaintenanceUnavailable):require_admission_open(db)
    with engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM public.admission_intents WHERE id=:id"),{"id":intent})==1


def test_missing_singleton_fails_closed(maintenance_control,book):
    with get_admin_engine().begin() as c:
        saved=dict(c.execute(text("SELECT * FROM public.maintenance_control WHERE id=1")).mappings().one())
        c.execute(text("DELETE FROM public.maintenance_control WHERE id=1"))
    try:
        response=generate(book)
        assert response.status_code==503 and response.json()["code"]=="maintenance"
    finally:
        with get_admin_engine().begin() as c:
            fields=','.join(saved);values=','.join(('CAST(:'+key+' AS JSON)') if key=='image_ids' else ':'+key for key in saved)
            if 'image_ids' in saved:saved['image_ids']=json.dumps(saved['image_ids'])
            c.execute(text(f"INSERT INTO public.maintenance_control({fields}) VALUES({values})"),saved)


def test_controller_epoch_is_durable_and_stale_identity_refused(maintenance_control,tmp_path):
    from datetime import datetime
    from ops.pi.contracts import Identity
    from ops.pi.ledger import Ledger
    from ops.pi.maintenance import enter_maintenance
    from myink.maintenance import maintenance_view
    expected=Identity('b8-synthetic',8,'trusted-fixture',{})
    ledger=Ledger(tmp_path/'maintenance.sqlite')
    with get_admin_engine().begin() as c:c.execute(text("UPDATE maintenance_control SET admission_closed=false,consumer_blocked=false WHERE id=1"))
    receipt=enter_maintenance(ledger,expected,datetime.fromisoformat('2026-10-12T02:00:00+08:00'))
    assert receipt.status=='done' and receipt.evidence['verified']
    with new_session() as db:state=maintenance_view(db)
    assert state['epoch']==receipt.evidence['maintenance_epoch'] and state['generation']==8
    assert state['admission_closed'] and state['consumer_blocked']
    stale=enter_maintenance(ledger,Identity('old',7,'old',{}),datetime.fromisoformat('2026-10-12T03:00:00+08:00'))
    assert stale.status=='blocked'
    with new_session() as db:assert maintenance_view(db)['epoch']==state['epoch']
    with get_admin_engine().begin() as c:c.execute(text('UPDATE maintenance_control SET generation=9 WHERE id=1'))
    repeat=enter_maintenance(ledger,expected,datetime.fromisoformat('2026-10-12T03:00:00+08:00'))
    assert repeat.status=='blocked' and not repeat.evidence['verified']


def test_maintenance_page_survives_candidate_failure(monkeypatch,tmp_path):
    from pathlib import Path
    import urllib.request,urllib.error,subprocess
    from ops.pi.lab.verify import verify_test_environment
    identity,_=verify_test_environment()
    assert len(identity.get('maintenance_containers',[]))==4
    names=identity['maintenance_containers']
    entry=identity['project']+'-maintenance-entry'
    before={name:json.loads(subprocess.check_output(['docker','inspect',name]))[0] for name in names}
    bindings=before[entry]['NetworkSettings']['Ports']['8080/tcp']
    assert len(bindings)==1 and bindings[0]['HostIp']=='127.0.0.1'
    url='http://127.0.0.1:'+bindings[0]['HostPort']
    try:urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=3)
    except urllib.error.HTTPError as response:
        from datetime import datetime
        from email.utils import parsedate_to_datetime
        deadline=datetime.fromisoformat(identity['maintenance_snapshot']['reopen_at'])
        assert response.code==503 and parsedate_to_datetime(response.headers['Retry-After'])==deadline
        body=response.read().decode()
        assert deadline.date().isoformat() in body and deadline.isoformat() in body
        assert '06:00' in body and '北京时间' in body
    else:raise AssertionError('maintenance entry did not return HTTP503')
    # The real durable control lives in independently owned infra as well.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import myink.db as database
    from ops.pi.contracts import Identity
    from ops.pi.ledger import Ledger
    from ops.pi.maintenance import enter_maintenance
    pg=before[identity['project']+'-maintenance-pg']
    binding=pg['NetworkSettings']['Ports']['5432/tcp'][0]
    assert binding['HostIp']=='127.0.0.1'
    persistent=create_engine('postgresql+psycopg://postgres:synthetic-lab-only@127.0.0.1:'+binding['HostPort']+'/myink')
    with monkeypatch.context() as scoped:
        scoped.setattr(database,'get_admin_engine',lambda:persistent)
        database.ensure_maintenance_schema()
        images={name:info['Image'] for name,info in before.items()}
        expected=Identity(identity['project'],8,'maintenance-infra',images)
        with persistent.begin() as c:
            control=c.execute(text('SELECT * FROM public.maintenance_control WHERE id=1 FOR UPDATE')).mappings().one()
            if control['deployment_id']=='initial' and control['generation']==0 and control['owner']=='bootstrap':
                c.execute(text("UPDATE public.maintenance_control SET deployment_id=:deployment,generation=8,owner='maintenance-infra',image_ids=CAST(:images AS JSON),admission_closed=false,consumer_blocked=false WHERE id=1"),{'deployment':expected.deployment_id,'images':json.dumps(images)})
            else:
                assert control['deployment_id']==expected.deployment_id and control['generation']==8
                assert control['owner']==expected.owner and control['image_ids']==images
                assert control['admission_closed'] and control['consumer_blocked'] and control['deadline']==deadline
        ledger=Ledger(Path('/opt/myink-pi-lab/maintenance-ledger.sqlite'))
        receipt=enter_maintenance(ledger,expected,deadline.replace(hour=2))
        assert receipt.status=='done' and receipt.evidence['verified']
        Path('/mnt/e/tools/myink-pi/evidence/b8-persistent-barrier.json').write_text(json.dumps({'status':receipt.status,'evidence':receipt.evidence,'infra_ids':{name:info['Id'] for name,info in before.items()}},indent=2))
    import socket,time,sys
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    children=[subprocess.Popen([sys.executable,'-m','uvicorn','myink.api.main:app','--host','127.0.0.1','--port',str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL),
              subprocess.Popen([sys.executable,'-m','myink.worker.consumer'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)]
    try:
        until=time.monotonic()+12;api_healthy=False
        while time.monotonic()<until:
            assert all(child.poll() is None for child in children)
            try:
                api_healthy=urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/healthz',timeout=1).status==200
                if api_healthy:break
            except OSError:time.sleep(.1)
        assert api_healthy
    finally:
        for child in children:
            if child.poll() is None:child.kill()
            assert child.wait(timeout=5)!=0
    for name in names:
        info=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
        assert info['Id']==before[name]['Id'] and info['State']['Running']
        assert info['HostConfig']['CgroupParent']=='myinkpi-infra.slice'
    for name,args in [(identity['project']+'-maintenance-pg',['pg_isready','-U','postgres']),
                      (identity['project']+'-maintenance-redis',['redis-cli','ping']),
                      (identity['project']+'-maintenance-rabbit',['rabbitmq-diagnostics','-q','ping'])]:
        assert subprocess.run(['docker','exec',name,*args],capture_output=True,timeout=15).returncode==0
    with persistent.connect() as c:
        state=c.execute(text('SELECT epoch,generation,owner,deadline,admission_closed,consumer_blocked FROM public.maintenance_control WHERE id=1')).mappings().one()
        assert state['epoch']==receipt.evidence['maintenance_epoch'] and state['deadline']==deadline
        assert state['admission_closed'] and state['consumer_blocked'] and state['generation']==8
    persistent.dispose()
    try:urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=3)
    except urllib.error.HTTPError as response:assert response.code==503


def test_report_bootstrap_preserves_private_intent_boundary(maintenance_control):
    from pathlib import Path
    import subprocess
    from ops.pi.lab.verify import verify_test_environment
    identity,_=verify_test_environment()
    script=(Path(__file__).parents[1]/'scripts/create-report-role.sh').read_text()
    sql=script.split("<<'SQL'\n",1)[1].split("\nSQL",1)[0]
    # Execute the bootstrap SQL verbatim against only the guarded synthetic PG.
    result=subprocess.run(['docker','exec','-i',identity['project']+'-pg','psql','-v','ON_ERROR_STOP=1','-U','postgres','-d','myink','-v','report_password=synthetic-b8-report'],input=sql,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    with get_admin_engine().begin() as c:
        c.execute(text('SET LOCAL ROLE myink_report'))
        assert c.scalar(text('SELECT count(*) FROM public.projects'))>=1
        assert c.scalar(text('SELECT count(*) FROM public.maintenance_admission_counts'))>=0
        assert not c.scalar(text("SELECT has_table_privilege(current_user,'public.admission_intents','SELECT')"))
    with get_admin_engine().connect() as c:
        c.execute(text('SET ROLE myink_report'))
        with pytest.raises(Exception):c.execute(text('SELECT rebuild_payload FROM public.admission_intents'))
        c.rollback()


def test_lab_collection_selectors():
    import subprocess,sys
    paths=['tests/test_maintenance_admission.py','tests/test_maintenance_worker_barrier.py']
    results={}
    for mode,selector in [('ordinary','not pi_lab and not pi_live'),('guarded','not pi_live')]:
        result=subprocess.run([sys.executable,'-m','pytest',*paths,'--collect-only','-q','-m',selector],capture_output=True,text=True,timeout=60)
        nodes=[line for line in result.stdout.splitlines() if line.startswith('tests/test_maintenance_') and '::' in line]
        results[mode]={'returncode':result.returncode,'nodes':nodes,'stdout':result.stdout,'stderr':result.stderr}
    from pathlib import Path
    Path('/mnt/e/tools/myink-pi/evidence/b8-fix1-collection-native.json').write_text(json.dumps(results,indent=2))
    assert not results['ordinary']['nodes']
    assert results['ordinary']['returncode']==5
    assert len(results['guarded']['nodes'])>=24 and results['guarded']['returncode']==0


@pytest.mark.parametrize('fault',['matching','epoch','generation','deployment','owner','images','deadline','admission_open','consumer_open','unreadable','precommit_open'])
def test_uncertain_receipt_fresh_readonly_reconciliation(maintenance_control,tmp_path,monkeypatch,fault):
    from datetime import datetime
    from pathlib import Path
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from ops.pi.contracts import Identity
    from ops.pi.ledger import Ledger
    import ops.pi.maintenance as controller
    engine=get_admin_engine()
    expected=Identity('b8-synthetic',8,'trusted-fixture',{})
    ledger=Ledger(tmp_path/'uncertain.sqlite')
    now=datetime.fromisoformat('2026-10-12T02:00:00+08:00')
    with engine.begin() as c:
        c.execute(text("UPDATE public.maintenance_control SET image_ids='{}',admission_closed=false,consumer_blocked=false WHERE id=1"))
    class AckLostSession(Session):
        def commit(self):
            if fault!='precommit_open':super().commit()
            raise ConnectionError('synthetic commit acknowledgement lost' if fault!='precommit_open' else 'synthetic precommit disconnect')
    with monkeypatch.context() as scoped:
        scoped.setattr(controller,'Session',AckLostSession)
        initial=controller.enter_maintenance(ledger,expected,now)
    assert initial.status=='uncertain' and not initial.evidence['verified']
    original=ledger.get(initial.operation_id)
    with engine.connect() as c:
        committed=dict(c.execute(text('SELECT * FROM public.maintenance_control WHERE id=1')).mappings().one())
    assert committed['admission_closed']==(fault!='precommit_open')
    if fault!='precommit_open':
        assert committed['consumer_blocked'] and committed['epoch']==initial.evidence['maintenance_epoch']
        assert committed['deadline']==datetime.fromisoformat(initial.evidence['deadline'])
    mutations={'epoch':"epoch='other'",'generation':'generation=9','deployment':"deployment_id='other'",'owner':"owner='other'",'images':"image_ids='{\"other\":\"image\"}'",'deadline':"deadline='2026-10-12T07:00:00+08:00'",'admission_open':'admission_closed=false','consumer_open':'consumer_blocked=false'}
    if fault in mutations:
        with engine.begin() as c:c.execute(text('UPDATE public.maintenance_control SET '+mutations[fault]+' WHERE id=1'))
    table='maintenance_control_unavailable' if fault=='unreadable' else 'maintenance_control'
    if fault=='unreadable':
        with engine.begin() as c:c.execute(text('ALTER TABLE public.maintenance_control RENAME TO maintenance_control_unavailable'))
    with engine.connect() as c:before=dict(c.execute(text('SELECT * FROM public.'+table+' WHERE id=1')).mappings().one())
    statements=[]
    def observe(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
    class NoCommitSession(Session):
        def commit(self):raise AssertionError('reconciliation must not commit')
    event.listen(engine,'before_cursor_execute',observe)
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(controller,'Session',NoCommitSession)
            reconciled=controller.enter_maintenance(ledger,expected,now.replace(hour=3))
    finally:
        event.remove(engine,'before_cursor_execute',observe)
        if fault=='unreadable':
            with engine.begin() as c:c.execute(text('ALTER TABLE public.maintenance_control_unavailable RENAME TO maintenance_control'))
    with engine.connect() as c:after=dict(c.execute(text('SELECT * FROM public.maintenance_control WHERE id=1')).mappings().one())
    assert after==before and ledger.get(initial.operation_id)==original
    proof={'fault':fault,'original':original,'committed':committed,'before':before,'after':after,'sql':statements,'status':reconciled.status,'evidence':reconciled.evidence}
    Path('/mnt/e/tools/myink-pi/evidence/b8-fix1-pg-reconcile-'+fault+'.json').write_text(json.dumps(proof,indent=2,default=str))
    assert reconciled.status==('done' if fault=='matching' else 'uncertain' if fault=='unreadable' else 'blocked')
    assert reconciled.evidence['verified']==(fault=='matching')
    assert any('SELECT' in sql.upper() for sql in statements)
    assert any('TRANSACTION_READ_ONLY' in sql.upper() for sql in statements)
    assert not any(sql.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) or 'FOR UPDATE' in sql.upper() or 'FOR SHARE' in sql.upper() for sql in statements)
    reconciliation_id=reconciled.evidence['reconciliation_id']
    uuid.UUID(reconciliation_id)
    with ledger.transaction() as c:
        rows=c.execute("SELECT payload FROM events WHERE kind='maintenance_reconciliation'").fetchall()
    assert len(rows)==1
    recorded=json.loads(rows[0][0])
    assert recorded['reconciliation_id']==reconciliation_id and recorded['operation_id']==initial.operation_id
    assert recorded['source_status']=='uncertain' and recorded['status']==reconciled.status
