"""Live database acceptance: pending until isolated B7 services are provisioned."""
from dataclasses import replace
import uuid
from sqlalchemy import delete, select
from myink.config import settings
from myink.db import new_session
from myink.models import AgentRun, User
from myink.providers.base import ModelResponse
from myink.workflow import nodes


def test_record_run_appends_versions_preserves_accounting_and_later_detail(monkeypatch):
    monkeypatch.setattr(nodes, 'settings', replace(settings, deployment_id='a4-test', deployment_generation=1,
                                                  deployment_owner='pi', observation_prompt_id='prompt-a4',
                                                  observation_rubric_id='rubric-a4', observation_data_id='data-a4',
                                                  observation_schema_id='schema-a4', observation_config_id='b' * 64))
    task_id = str(uuid.uuid4())
    original = dict(plan={'text': 'original'}, custom='retain')
    resp = ModelResponse(content='{}', model_id='actual-fallback', input_tokens=7, output_tokens=9,
                         duration_ms=11, prices={'input': 10000, 'input_cache_hit': 10000, 'output': 0})
    with new_session() as db:
        user = User(username='a4-' + uuid.uuid4().hex[:8])
        db.add(user)
        db.commit()
        uid = user.id
    try:
        with new_session() as db:
            nodes.record_run(db, user_id=uid, task_id=task_id, node='write', role='Writer',
                             resp=resp, detail=original)
            nodes.record_run_detail(db, task_id=task_id, node='write',
                                    detail={'audit_verdict': {'ok': True}, 'run_provenance': {'deployment_id': 'forged'}})
            db.commit()
        with new_session() as db:
            row = db.scalar(select(AgentRun).where(AgentRun.task_id == task_id))
            assert row.user_id == uid and row.project_id is None
            assert (row.input_tokens, row.output_tokens, row.cost_est) == (7, 9, .07)
            assert row.model_id == 'actual-fallback' and row.error is None
            assert row.detail['plan'] == original['plan'] and row.detail['custom'] == 'retain'
            assert row.detail['run_provenance']['deployment_id'] == 'a4-test'
            assert row.detail['run_provenance']['config_id']
            assert row.detail['measurement']['model_id'] == 'actual-fallback'
            assert row.detail['audit_verdict'] == {'ok': True}
        assert original == dict(plan={'text': 'original'}, custom='retain')
    finally:
        with new_session() as db:
            db.execute(delete(AgentRun).where(AgentRun.user_id == uid))
            db.execute(delete(User).where(User.id == uid))
            db.commit()
