"""The UI's task endpoint must finish accepted review, not regenerate its draft."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from conftest import identity_headers
from myink.api.main import app
from myink.db import tenant_session
from myink.models import Chapter, Fact, MemoryCandidate, Project, Task
from myink.workflow import nodes, runner
from myink.worker import processor
from myink.worker.redis_client import get_redis, sse_key
from test_review_finalization_resume import _completed_summary_graph

client = TestClient(app)


@pytest.mark.parametrize('task_type,payload,resume_type', [
    ('chapter_generate', {'seq': 1}, 'chapter_resume'),
    ('batch_generate', {'start': 1, 'size': 3}, 'batch_resume'),
])
def test_review_http_resume_routes_existing_task(temp_project, stub_provider, monkeypatch,
                                                task_type, payload, resume_type):
    stub_provider('金丹', '金丹')
    tid = uuid.uuid4()
    with tenant_session(temp_project) as db:
        uid = str(db.get(Project, uuid.UUID(temp_project)).user_id)
        db.add(Task(id=tid, project_id=temp_project, task_type=task_type,
                    status='awaiting_review', payload=payload))
    sent = []
    monkeypatch.setattr('myink.worker.amqp.publish', lambda body, *a, **kw: sent.append(json.loads(body)))
    response = client.post(f'/api/v1/tasks/{tid}/resume', headers=identity_headers(uid))
    assert response.status_code == 200, response.text
    assert sent[0]['task_type'] == resume_type
    assert sent[0]['task_id'] == str(tid)
    assert sent[0]['payload'] == {**payload, 'position': 0}
    with tenant_session(temp_project) as db:
        assert db.get(Task, tid).status == 'queued'


def test_accept_http_then_resume_worker_persists_chapter_and_memory(temp_project, stub_provider, fake_embedder, monkeypatch):
    stub_provider('金丹', '金丹')
    tid, draft = str(uuid.uuid4()), '作者已审核的正文，无需重新生成。'
    graph = _completed_summary_graph(temp_project, tid, draft, needs_review=True)
    with tenant_session(temp_project) as db:
        uid = str(db.get(Project, uuid.UUID(temp_project)).user_id)
        db.add(Task(id=uuid.UUID(tid), project_id=temp_project, task_type='chapter_generate',
                    status='awaiting_review', chapter_seq=1, payload={'seq': 1}))
        db.add(Chapter(project_id=temp_project, chapter_seq=1, status='awaiting_review', content=draft))
        candidate = MemoryCandidate(project_id=temp_project, source_chapter=1, kind='fact',
                                    payload={'content': '作者批准的设定'}, status='pending')
        db.add(candidate)
        db.flush()
        cid = str(candidate.id)
    for module in (runner, processor):
        monkeypatch.setattr(module, 'get_graphs', lambda: (graph, None))
    # Keep real persistence and worker completion; the summary model is irrelevant here.
    monkeypatch.setattr(nodes, 'node_summarize', lambda state: {})
    sent = []
    monkeypatch.setattr('myink.worker.amqp.publish', lambda body, *a, **kw: sent.append(json.loads(body)))
    headers = identity_headers(uid)
    response = client.post(f'/api/v1/projects/{temp_project}/candidates/{cid}/confirm', headers=headers)
    assert response.status_code == 200, response.text
    with tenant_session(temp_project) as db:
        assert db.query(Chapter).one().status == 'awaiting_review'
        assert db.query(Fact).one().content == '作者批准的设定'
    response = client.post(f'/api/v1/tasks/{tid}/resume', headers=headers)
    assert response.status_code == 200, response.text
    try:
        assert processor.process(sent[0]) == 'terminal'
        with tenant_session(temp_project) as db:
            chapter = db.query(Chapter).one()
            assert chapter.content == draft
            assert chapter.status == 'confirmed'
            assert db.get(Task, uuid.UUID(tid)).status == 'done'
            assert db.get(MemoryCandidate, uuid.UUID(cid)).status == 'confirmed'
            assert db.query(Fact).count() == 1
            version = chapter.version
        # A completed task is skipped on duplicate delivery, without changing data.
        assert processor.process(sent[0]) == 'skip'
        with tenant_session(temp_project) as db:
            assert db.query(Chapter).one().version == version
            assert db.query(Fact).count() == 1
    finally:
        get_redis().delete(sse_key(tid))
