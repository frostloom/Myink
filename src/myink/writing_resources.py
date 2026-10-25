"""Transactional writing resources. Callers own commits and tenant context."""
from copy import deepcopy
from datetime import datetime, timezone
import uuid
from fastapi import HTTPException
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from myink.models.writing_resource import WritingResource, WritingResourceRevision, PersonalWritingResource, ProjectWritingResources, WritingResourcePublication

def fail(code, detail):
    raise HTTPException(code, detail)

def resource(db, rid, user_id=None):
    model = PersonalWritingResource if user_id is not None else WritingResource
    query = select(model).where(model.id == rid)
    if user_id is not None:
        query = query.where(model.user_id == uuid.UUID(str(user_id)))
    row = db.scalar(query)
    if row is None:
        fail(404, 'RESOURCE_NOT_FOUND')
    return row

def out(row, public=False):
    data = {k: deepcopy(getattr(row, k)) for k in ('id', 'name', 'kind', 'source', 'body', 'status', 'generation', 'current_version')}
    if public:
        data.update({k: deepcopy(row.publication[k]) for k in ('name', 'source', 'kind', 'body', 'generation')})
    return data

def create_resource(db, data, user_id=None, rid=None):
    if data.get('kind') == 'role_prompt':
        if user_id is not None or rid != 'role-prompt:' + data['body']['role']:
            fail(422, 'ROLE_PROMPT_IS_AUTOMATIC')
    model = PersonalWritingResource if user_id is not None else WritingResource
    row = model(**data, **{'id': rid} if rid else {})
    if user_id is not None:
        row.user_id = uuid.UUID(str(user_id))
        row.status = 'published'
        row.generation = 1
        row.current_version = 1
    db.add(row)
    db.flush()
    return row

def cas(db, row, expected, values):
    result = db.execute(update(type(row)).where(type(row).id == row.id, type(row).generation == expected).values(**values, generation=expected + 1).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        fail(409, 'RESOURCE_GENERATION_CHANGED')
    db.expire(row)
    db.refresh(row)

def update_resource(db, rid, expected, data, user_id=None):
    row = resource(db, rid, user_id)
    if row.kind == 'role_prompt' and data.get('body', row.body).get('role') != row.body['role']:
        fail(422, 'ROLE_PROMPT_ROLE_IMMUTABLE')
    values = {k: v for k, v in data.items() if k in ('name', 'source', 'body', 'status') and v is not None}
    if user_id is not None:
        values['current_version'] = (row.current_version or 0) + 1
    cas(db, row, expected, values)
    return row

def revisions(db, rid):
    resource(db, rid)
    return [deepcopy(r.document) for r in db.scalars(select(WritingResourceRevision).where(WritingResourceRevision.resource_id == rid).order_by(WritingResourceRevision.version))]

def publish(db, rid, expected, note, version=None):
    row = resource(db, rid)
    if row.generation != expected:
        fail(409, 'RESOURCE_GENERATION_CHANGED')
    action = 'rollback' if version is not None else 'publish'
    if version is not None:
        rev = db.get(WritingResourceRevision, (rid, version))
        if rev is None:
            fail(404, 'REVISION_NOT_FOUND')
        document = deepcopy(rev.document)
    else:
        version = (db.scalar(select(func.max(WritingResourceRevision.version)).where(WritingResourceRevision.resource_id == rid)) or 0) + 1
        document = {k: deepcopy(getattr(row, k)) for k in ('name', 'source', 'kind', 'body')}
        document.update(version=version, created_at=datetime.now(timezone.utc).isoformat(), action='publish', note=note)
    publication = dict(document, action=action, note=note, generation=expected + 1)
    cas(db, row, expected, dict(status='published', current_version=version, publication=publication))
    db.add(WritingResourcePublication(resource_id=rid, generation=expected + 1, version=version, document=dict(publication, published_at=datetime.now(timezone.utc).isoformat())))
    if action == 'publish':
        db.add(WritingResourceRevision(resource_id=rid, version=version, document=document))
        db.flush()
    return row

def catalog(db):
    return [out(row, True) for row in db.scalars(select(WritingResource).where(WritingResource.kind.notin_(['role_prompt', 'reference']), WritingResource.status == 'published', WritingResource.current_version.is_not(None)).order_by(WritingResource.id))]

def state(db, pid):
    return db.get(ProjectWritingResources, uuid.UUID(str(pid)))

def project_snapshot(db, project_id):
    row = state(db, project_id)
    return deepcopy(dict(revision=row.revision, configured=True, selections=row.selections)) if row else dict(revision=0, configured=False, selections=[])

def capture_task_resources(db, project_id):
    snapshot = project_snapshot(db, project_id) if project_id else dict(revision=0, configured=False, selections=[])
    snapshot['role_prompts'] = capture_role_prompts(db)
    snapshot['reference_library'] = capture_reference_library(db)
    from myink.models.platform import PlatformConfiguration
    policy = db.get(PlatformConfiguration, 1)
    snapshot['legacy_role_supplements'] = deepcopy(policy.document.get('prompts', {}) if policy else {})
    return deepcopy(snapshot)


def is_writing_reference(path):
    """Keep technical support files out of the automatic creative library."""
    import re
    from pathlib import PurePosixPath
    if not isinstance(path, str) or "\\" in path:
        return False
    parts = path.split('/')
    if not path or path.startswith('/') or any(p in ('', '.', '..') for p in parts):
        return False
    name = PurePosixPath(path).name
    return not (re.match(r'^(license|notice|copying)(\.|$)', name, re.I)
                or name.lower() == 'readme.md'
                or re.search(r'author_(?:error_catalog|glossary)|[^/]*-schema|reference-loading-map|reference-gap-register', path, re.I))


def capture_reference_library(db):
    result = []
    for row in db.scalars(select(WritingResource).where(
            WritingResource.kind == 'reference', WritingResource.status == 'published',
            WritingResource.current_version.is_not(None)).order_by(WritingResource.id)):
        pub = row.publication
        if not is_writing_reference(pub['name']):
            continue
        files = [{'path': f['path']} for f in pub['body'].get('files', [])
                 if is_writing_reference(f['path'])]
        if files:
            result.append(dict(resource_id=row.id, version=row.current_version,
                               generation=pub['generation'], name=pub['name'],
                               source=pub['source'], files=files))
    return result


def capture_role_prompts(db):
    return {row.publication['body']['role']: dict(resource_id=row.id, version=row.current_version,
            generation=row.publication['generation'], body=deepcopy(row.publication['body']))
            for row in db.scalars(select(WritingResource).where(WritingResource.kind == 'role_prompt',
                WritingResource.current_version.is_not(None)))}

def save_snapshot(db, pid, expected, selections, dismissed=None):
    from myink.writing_resource_schemas import validate_size, MAX_SNAPSHOT_BYTES
    try:
        validate_size(selections, MAX_SNAPSHOT_BYTES)
    except ValueError as exc:
        fail(422, str(exc))
    row = state(db, pid)
    if row is None:
        if expected != 0:
            fail(409, 'SNAPSHOT_CHANGED')
        row = ProjectWritingResources(project_id=uuid.UUID(str(pid)), revision=1, selections=deepcopy(selections), dismissed=dismissed or {})
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            fail(409, 'SNAPSHOT_CHANGED')
    else:
        values = dict(revision=expected + 1, selections=deepcopy(selections))
        if dismissed is not None:
            values['dismissed'] = dismissed
        changed = db.execute(update(ProjectWritingResources).where(ProjectWritingResources.project_id == row.project_id, ProjectWritingResources.revision == expected).values(**values).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            fail(409, 'SNAPSHOT_CHANGED')
        db.expire(row)
    return project_snapshot(db, pid)

def set_selection(db, pid, uid, expected, selections):
    result = []
    seen = set()
    existing = {(i['origin'], i['resource_id']): i for i in project_snapshot(db, pid)['selections']}
    for item in selections:
        key = (item['origin'], item['resource_id'])
        if key in seen:
            fail(422, 'DUPLICATE_RESOURCE')
        seen.add(key)
        if item['resource_id'].startswith('role-prompt:'):
            fail(422, 'ROLE_PROMPT_IS_AUTOMATIC')
        previous = existing.get(key)
        explicit_override = (
            item.get('personal_override') and item.get('body') is not None
        )
        preserve_snapshot = previous is not None and (
            item['origin'] == 'platform' or previous['personal_override']
        )
        if preserve_snapshot and (not explicit_override or previous['personal_override']):
            saved = deepcopy(previous)
            if explicit_override:
                from myink.writing_resource_schemas import validate_resource_body
                try:
                    validate_resource_body(saved['kind'], item['body'])
                except ValueError as exc:
                    fail(422, str(exc))
                saved['body'] = deepcopy(item['body'])
            result.append(saved)
            continue
        # An explicit save adopts the owner's latest personal library version.
        # Platform releases and project-specific overrides require explicit adoption/editing.
        row = resource(db, item['resource_id'], uid if item['origin'] == 'personal' else None)
        if item['origin'] == 'platform' and row.kind in ('reference', 'role_prompt'):
            fail(422, 'REFERENCE_IS_AUTOMATIC' if row.kind == 'reference' else 'ROLE_PROMPT_IS_AUTOMATIC')
        if row.status != 'published' or row.current_version is None:
            fail(409, 'RESOURCE_NOT_PUBLISHED')
        canonical = out(row, item['origin'] == 'platform')
        override = item.get('personal_override', False)
        result.append(dict(resource_id=row.id, origin=item['origin'], name=canonical['name'], kind=row.kind, version=row.current_version, generation=canonical['generation'], body=deepcopy(item['body'] if override and item.get('body') is not None else canonical['body']), personal_override=override))
    return save_snapshot(db, pid, expected, result)

def updates(db, pid):
    row = state(db, pid)
    if row is None:
        return []
    result = []
    for item in row.selections:
        if item['origin'] != 'platform' or item['personal_override']:
            continue
        source = db.get(WritingResource, item['resource_id'])
        if source is None or source.status != 'published' or source.publication.get('generation') == item['generation']:
            continue
        pub = source.publication
        if all((item[k] == pub[k] for k in ('name', 'kind', 'body'))):
            continue
        result.append(dict(resource_id=source.id, name=pub['name'], kind=pub['kind'], current_version=item['version'], target_version=source.current_version, target_generation=pub['generation'], action=pub['action'], note=pub['note'], dismissed=row.dismissed.get(source.id) == pub['generation']))
    return result

def check_updates(db, pid, requested):
    available = {i['resource_id']: i for i in updates(db, pid)}
    if len({i['resource_id'] for i in requested}) != len(requested):
        fail(422, 'DUPLICATE_RESOURCE')
    for item in requested:
        current = available.get(item['resource_id'])
        if not current or current['target_generation'] != item['target_generation']:
            fail(409, 'PUBLICATION_CHANGED')
        source = resource(db, item['resource_id'])
        # Hold the publication lock through the caller transaction.
        db.refresh(source, with_for_update=True)
        if source.publication.get('generation') != item['target_generation']:
            fail(409, 'PUBLICATION_CHANGED')
    return available

def dismiss(db, pid, requested):
    check_updates(db, pid, requested)
    row = state(db, pid)
    if row is None:
        fail(409, 'SNAPSHOT_CHANGED')
    # Serialize dismissal against selection changes to avoid lost writes.
    db.refresh(row, with_for_update=True)
    row.dismissed = dict(row.dismissed, **{i['resource_id']: i['target_generation'] for i in requested})
    db.flush()

def adopt(db, pid, expected, requested):
    check_updates(db, pid, requested)
    selected = project_snapshot(db, pid)['selections']
    targets = {i['resource_id'] for i in requested}
    for item in selected:
        if item['resource_id'] not in targets:
            continue
        source = resource(db, item['resource_id'])
        item.update(name=source.publication['name'], body=deepcopy(source.publication['body']), version=source.current_version, generation=source.publication['generation'])
    return save_snapshot(db, pid, expected, selected)

def initialize_builtin_resources(db):
    from myink.writing_resource_seed import builtin_resources
    for item in builtin_resources():
        data = deepcopy(item)
        rid = data.pop('id')
        if db.get(WritingResource, rid) is None:
            row = create_resource(db, data, rid=rid)
            publish(db, row.id, 0, 'Built-in initial publication')
