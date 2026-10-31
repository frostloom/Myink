"""Admission must not borrow a second connection while holding its project lock."""
from contextlib import contextmanager
from types import SimpleNamespace
import uuid

from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from myink import db as database
from myink.worker import enqueue as queue


def test_configuration_reads_finish_before_project_lock_with_single_connection(temp_project, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from myink.models import Project

    with database.new_session() as db:
        owner = str(db.get(Project, uuid.UUID(temp_project)).user_id)
    engine = create_engine(database.get_engine().url, poolclass=QueuePool,
                          pool_size=1, max_overflow=0, pool_timeout=0.1)
    def read_configuration(*args):
        with engine.connect() as connection:
            connection.exec_driver_sql('SELECT 1')
        return {}
    monkeypatch.setattr(database, '_engine', engine)
    monkeypatch.setattr(database, '_SessionLocal', sessionmaker(bind=engine, expire_on_commit=False, autoflush=False))
    monkeypatch.setattr('myink.platform_readiness.require_operation_ready', read_configuration)
    monkeypatch.setattr('myink.task_budget.snapshot_budget', read_configuration)
    monkeypatch.setattr('myink.writing_resources.capture_task_resources', lambda *args: {})
    monkeypatch.setattr(queue, '_run_gates', lambda *args, **kwargs: (1, 'ok'))
    monkeypatch.setattr(queue, '_seed_sse', lambda *args: None)
    monkeypatch.setattr(queue, 'get_redis', lambda: SimpleNamespace(set=lambda *args, **kwargs: None))
    monkeypatch.setattr(queue.amqp, 'publish', lambda *args, **kwargs: None)
    try:
        result = queue.enqueue(user_id=owner, project_id=temp_project, task_type='chapter_generate', payload={}, quota_n=1, cost_est=0, priority=0)
        assert result['status'] == 'queued'
    finally:
        engine.dispose()


def test_direct_task_reads_owner_budget_before_project_lock(monkeypatch):
    from myink.workflow import runner
    engine = create_engine('sqlite://', poolclass=QueuePool, pool_size=1, max_overflow=0, pool_timeout=0.01)
    owner_id = uuid.uuid4()
    stored = []
    @contextmanager
    def tenant(pid):
        with engine.connect():
            yield SimpleNamespace(get=lambda *args, **kwargs: SimpleNamespace(user_id=owner_id), add=stored.append, flush=lambda: None)
    def budget(uid):
        with engine.connect() as connection:
            connection.exec_driver_sql('SELECT 1')
        return {'owner':uid}
    monkeypatch.setattr(runner, 'tenant_session', tenant)
    monkeypatch.setattr('myink.task_budget.snapshot_budget', budget)
    monkeypatch.setattr('myink.task_budget.ensure_task_budget', lambda *args: None)
    monkeypatch.setattr('myink.writing_resources.capture_task_resources', lambda *args: {})
    try:
        runner.new_task(project_id=str(uuid.uuid4()),task_type='chapter_generate',payload={})
        assert stored[0].payload['_task_budget'] == {'owner':str(owner_id)}
    finally:
        engine.dispose()
