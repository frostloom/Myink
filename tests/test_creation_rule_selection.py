"""Creation edits must reach the book without refreshing unrelated frozen resources."""
import uuid

from test_writing_resources import db  # noqa: F401 - shared SQLite service fixture
from myink import writing_resources as service
from myink.models import Project


def test_creation_edit_overrides_only_edited_rule_after_planning_capture(db):
    uid, pid = uuid.uuid4(), uuid.uuid4()
    db.add(Project(id=pid, user_id=uid, title='creation edit', genre='修仙', form='long', creation_status='draft'))
    resources = []
    for kind in ('writing_rule', 'expression_rule'):
        row = service.create_resource(db, dict(name=kind, kind=kind, source='platform', body={'roles': {'writer': 'PLATFORM'}}))
        service.publish(db, row.id, 0, '')
        resources.append(service.copy_platform(db, row.id, uid, 1, body={'roles': {'writer': 'OLD_PERSONAL'}}))
    old = service.capture_task_resources(db, pid)
    writer, expression = resources
    service.update_resource(db, writer.id, 1, {'body': {'roles': {'writer': 'EDITED_IN_CREATION'}}}, uid)
    service.update_resource(db, expression.id, 1, {'body': {'roles': {'writer': 'UNRELATED_LIBRARY_EDIT'}}}, uid)
    selected = service.set_selection(db, pid, uid, old['revision'], [
        dict(origin='personal', resource_id=writer.id, personal_override=True, body={'roles': {'writer': 'EDITED_IN_CREATION'}}),
        dict(origin='personal', resource_id=expression.id),
    ])
    current = service.capture_task_resources(db, pid)
    assert current['selections'] == selected['selections']
    assert next(item for item in current['selections'] if item['resource_id'] == writer.id)['body'] == {'roles': {'writer': 'EDITED_IN_CREATION'}}
    assert next(item for item in current['selections'] if item['resource_id'] == expression.id) == next(item for item in old['selections'] if item['resource_id'] == expression.id)
    assert next(item for item in old['selections'] if item['resource_id'] == writer.id)['body'] == {'roles': {'writer': 'OLD_PERSONAL'}}
