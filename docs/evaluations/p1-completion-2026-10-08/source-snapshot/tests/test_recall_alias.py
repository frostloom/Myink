"""Alias retrieval regression against real PostgreSQL, model not called."""
import uuid
from myink.db import tenant_session
from myink.models import Alias, Character, Event
from myink.memory.recall import _keyword_event_leg


def test_canonical_participant_recalls_event_written_with_alias(temp_project):
    pid=uuid.UUID(temp_project)
    with tenant_session(pid) as db:
        char=Character(project_id=pid,name='林川',realm_cap='普通人')
        db.add(char);db.flush()
        db.add(Alias(project_id=pid,alias='老林',entity_id=char.id))
        event=Event(project_id=pid,summary='老林将损坏仪器封存',source_chapter=1,participants=[])
        db.add(event);db.flush();eid=event.id
    with tenant_session(pid) as db:
        assert eid in _keyword_event_leg(db,pid,['林川'])
