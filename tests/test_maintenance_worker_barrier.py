"""A restarted worker holds messages without executing during maintenance."""
import json
from types import SimpleNamespace
import uuid
from test_maintenance_admission import maintenance_control,book
from myink.worker import consumer
from myink.worker.redis_client import get_redis

class Channel:
    def __init__(self):self.acks=[];self.nacks=[];self.stopped=False
    def basic_ack(self,tag):self.acks.append(tag)
    def basic_nack(self,tag,**kwargs):self.nacks.append((tag,kwargs))
    def stop_consuming(self):self.stopped=True


def test_worker_restart_does_not_consume(maintenance_control,book,monkeypatch):
    executed=[]
    monkeypatch.setattr(consumer,"process",lambda *a,**k: executed.append(1) or "terminal")
    ch=Channel()
    message={"task_id":str(uuid.uuid4()),"project_id":book[0],"user_id":book[1],"task_type":"chapter_generate","payload":{"seq":1}}
    consumer._on_message(ch,SimpleNamespace(delivery_tag=1),None,json.dumps(message).encode(),get_redis(),"b8-restarted-worker")
    assert len(executed)==0
    assert ch.acks==[] and ch.nacks==[]
    assert ch.stopped


def test_actual_worker_restarts_leave_rabbit_message_unclaimed(maintenance_control,book):
    import os,subprocess,sys,time
    from sqlalchemy import select
    from myink.db import new_session
    from myink.models import Task
    from myink.worker import amqp
    tid=str(uuid.uuid4());r=get_redis()
    connection=amqp.connect();channel=connection.channel();amqp.declare_topology(channel)
    channel.queue_purge(amqp.main_queue())
    amqp.publish(json.dumps({"task_id":tid,"project_id":book[0],"user_id":book[1],"task_type":"chapter_generate","payload":{"seq":1}}),amqp.KEY_TASKS)
    try:
        for attempt in range(2):
            before=set(r.scan_iter('queue:heartbeat:*'))
            child=subprocess.Popen([sys.executable,'-m','myink.worker.consumer'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+12
                while not (set(r.scan_iter('queue:heartbeat:*'))-before) and time.monotonic()<deadline:
                    assert child.poll() is None
                    time.sleep(.1)
                assert set(r.scan_iter('queue:heartbeat:*'))-before
                time.sleep(.3)
                info=channel.queue_declare(amqp.main_queue(),passive=True).method
                assert info.message_count==1 and info.consumer_count==0
                with new_session() as db:assert db.get(Task,uuid.UUID(tid)) is None
            finally:
                child.terminate()
                try:child.wait(timeout=8)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
                stale=set(r.scan_iter('queue:heartbeat:*'))-before
                if stale:r.delete(*stale)
    finally:
        channel.queue_purge(amqp.main_queue());connection.close()


def test_claim_barrier_does_not_materialize_or_release_quota(maintenance_control,book):
    from myink.worker import processor
    from myink.worker.redis_client import inflight_key
    from myink.db import new_session
    from myink.models import Task
    from myink.maintenance import MaintenanceUnavailable
    import pytest
    tid=str(uuid.uuid4());r=get_redis();key=inflight_key(book[1],book[0]);r.sadd(key,tid)
    try:
        with pytest.raises(MaintenanceUnavailable):
            processor.process({"task_id":tid,"project_id":book[0],"user_id":book[1],"task_type":"chapter_generate","payload":{"seq":1}})
        with new_session() as db:assert db.get(Task,uuid.UUID(tid)) is None
        assert r.sismember(key,tid)
    finally:r.srem(key,tid)
