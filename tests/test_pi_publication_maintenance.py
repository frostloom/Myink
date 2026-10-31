"""Publication SQL against a separate fresh PG database, never product tables."""
from datetime import datetime, timezone
import json
from threading import Event, Thread
import uuid
import pytest
import psycopg
from psycopg import sql
from sqlalchemy import create_engine
from myink.db import get_admin_engine
from myink.models import Base


@pytest.fixture
def pg_publication(tmp_path):
    from ops.pi.admin_maintenance import Maintenance
    from ops.pi.audit import encoded
    url=get_admin_engine().url
    assert url.host in ('localhost','127.0.0.1')
    name='pi_console_test_'+uuid.uuid4().hex
    admin_url=url.set(drivername='postgresql').render_as_string(hide_password=False)
    with psycopg.connect(admin_url,autocommit=True) as admin:admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    test_url=url.set(database=name)
    dsn=test_url.set(drivername='postgresql').render_as_string(hide_password=False)
    engine=create_engine(test_url)
    try:
        with engine.begin() as db:db.exec_driver_sql('CREATE EXTENSION IF NOT EXISTS vector')
        Base.metadata.create_all(engine)
        identity=dict(deployment_id='fixture-base',generation=1,owner='fixture-owner',image_ids={'python':'sha256:'+'a'*64})
        before=dict(id=1,epoch='fixture-epoch',deadline=None,admission_closed=False,consumer_blocked=False,**identity)
        with psycopg.connect(dsn,autocommit=True) as db:
            from psycopg.types.json import Json
            db.execute('INSERT INTO maintenance_control(id,epoch,deployment_id,generation,owner,image_ids,deadline,admission_closed,consumer_blocked) VALUES(1,%s,%s,1,%s,%s,NULL,false,false)',(before['epoch'],identity['deployment_id'],identity['owner'],Json(identity['image_ids'])))
        class Commands:
            root=tmp_path
            before_update=None
            def run(self,args,**kwargs):
                if args[0]=='ps':body=b'isolated-postgres'
                else:
                    assert args[:3]==['exec','isolated-postgres','psql']
                    if 'UPDATE public.maintenance_control' in args[-1] and self.before_update:self.before_update()
                    value=None
                    with psycopg.connect(dsn,autocommit=True) as db,db.cursor() as cur:
                        cur.execute(args[-1],prepare=False)
                        while True:
                            if cur.description is not None:
                                row=cur.fetchone()
                                if row is not None:value=row[0]
                            if not cur.nextset():break
                    body=encoded(value)
                operation=str(uuid.uuid4());folder=tmp_path/operation;folder.mkdir(mode=0o700);(folder/'stdout.bin').write_bytes(body)
                return dict(status='done',returncode=0,command_id=operation)
        commands=Commands();root=tmp_path/'publication';root.mkdir(mode=0o700)
        yield Maintenance(commands),commands,identity,before,root,dsn
    finally:
        engine.dispose()
        with psycopg.connect(admin_url,autocommit=True) as admin:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


@pytest.mark.parametrize("microsecond", [0, 100000, 123450, 123456])
def test_original_pg_cas_closes_adopts_and_reopens_exact_identity(pg_publication, microsecond):
    maintenance,commands,identity,before,root,dsn=pg_publication
    assert maintenance.opened(identity)==before
    closed=maintenance.close(before,str(uuid.uuid4()),datetime(2026,10,31,7,0,tzinfo=timezone.utc).replace(microsecond=microsecond),root)
    assert maintenance.read()==closed and closed['admission_closed'] and closed['consumer_blocked']
    candidate=dict(identity,deployment_id='fixture-candidate',generation=2,image_ids={'python':'sha256:'+'b'*64})
    closed=maintenance.adopt(closed,candidate,root)
    assert maintenance.read()['generation']==2
    opened=maintenance.reopen(closed,root)
    assert opened['deadline'] is None and not opened['admission_closed'] and maintenance.opened(candidate)==opened
    with pytest.raises(ValueError):maintenance.change(before,closed)


def test_admission_committing_before_exclusive_barrier_is_seen_after_closure(pg_publication):
    maintenance,commands,identity,before,root,dsn=pg_publication
    entered=Event();release=Event();failures=[]
    def hook():entered.set();assert release.wait(5)
    commands.before_update=hook
    with psycopg.connect(dsn) as admission:
        admission.execute('SELECT * FROM maintenance_control WHERE id=1 FOR SHARE')
        def close():
            try:maintenance.close(before,str(uuid.uuid4()),datetime.now(timezone.utc),root)
            except BaseException as error:failures.append(error)
        thread=Thread(target=close);thread.start();assert entered.wait(5)
        # This represents the durable intake committed by the already-admitted
        # request. It is not in RabbitMQ yet; zero queue messages is insufficient.
        admission.execute("INSERT INTO admission_intents(id,task_id,message_id,user_id,project_id,epoch,deployment_generation,deployment_id,owner,payload_hash,rebuild_payload,priority,gate_state,publication_state,quota_inputs) VALUES(%s,%s,'fixture',%s,%s,'fixture-epoch',1,'fixture-base','fixture-owner',%s,'{}',0,'accepted','pending','{}')",(uuid.uuid4(),uuid.uuid4(),uuid.uuid4(),uuid.uuid4(),'c'*64))
        release.set();admission.commit();thread.join(timeout=8)
    assert not thread.is_alive() and len(failures)==1 and isinstance(failures[0],ValueError)
    assert maintenance.read()['admission_closed'] is True
    assert not (root/'maintenance-open.json').exists()
