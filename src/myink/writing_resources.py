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
    data.update(source_resource_id=getattr(row, 'source_resource_id', None),
                source_generation=getattr(row, 'source_generation', None))
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
    if user_id is not None and row.kind == 'genre' and row.source_resource_id and data.get('body', row.body).get('catalog_id') != row.body.get('catalog_id'):
        fail(422, 'GENRE_CATALOG_ID_IMMUTABLE')
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

def catalog(db, include_automatic=False):
    query = select(WritingResource).where(WritingResource.status == 'published', WritingResource.current_version.is_not(None))
    if not include_automatic:
        query = query.where(WritingResource.kind.notin_(['role_prompt', 'reference']))
    return [out(row, True) for row in db.scalars(query.order_by(WritingResource.id))]

def state(db, pid):
    return db.get(ProjectWritingResources, uuid.UUID(str(pid)))

_STYLE_MANAGED_KEY = '__myink_style_managed_v1'


def project_snapshot(db, project_id):
    row = state(db, project_id)
    return deepcopy(dict(revision=row.revision, configured=row.configured, selections=row.selections,
                         style_managed=bool((row.dismissed or {}).get(_STYLE_MANAGED_KEY)))) if row else dict(revision=0, configured=False, selections=[], style_managed=False)

def ensure_project_resources(db, project_id, user_id=None):
    """Initialize frozen defaults once under the same project lock as task admission."""
    from myink.models import Project
    project = db.get(Project, uuid.UUID(str(project_id)), with_for_update=True)
    if project is None:
        return project_snapshot(db, project_id)
    if user_id is not None and project.user_id != uuid.UUID(str(user_id)):
        fail(404, 'project_not_found')
    row = state(db, project_id)
    automatic_needed = row is None or not row.automatic_initialized
    defaults_needed = row is None or not row.defaults_initialized
    if automatic_needed or defaults_needed:
        additions = initialization_selections(db, project_id, project.user_id, automatic_needed, defaults_needed)
        previous = merge_automatic_selections(deepcopy(row.selections) if row else [], additions)
        save_snapshot(db, project_id, row.revision if row else 0, previous,
                      configured=row.configured if row else False,
                      automatic_initialized=True, defaults_initialized=True)
    return project_snapshot(db, project_id)


def initialization_selections(db, pid, uid, automatic_needed, defaults_needed):
    return [item for item in automatic_selections(db, pid, uid)
            if (defaults_needed if item['kind'] in ('writing_rule', 'expression_rule') else automatic_needed)]


def capture_task_resources(db, project_id, user_id=None):
    if project_id:
        ensure_project_resources(db, project_id, user_id)
    snapshot = project_snapshot(db, project_id) if project_id else dict(revision=0, configured=False, selections=[])
    if project_id and state(db, project_id) is not None:
        snapshot['role_prompts'] = {item['body']['role']: dict(resource_id=item['resource_id'],
            version=item['version'], generation=item['generation'], body=deepcopy(item['body']))
            for item in snapshot['selections'] if item['kind'] == 'role_prompt'}
        snapshot['reference_library'] = [dict(resource_id=item['resource_id'], version=item['version'],
            generation=item['generation'], name=item['name'], files=deepcopy(item['body']['files']))
            for item in snapshot['selections'] if item['kind'] == 'reference' and item['body'].get('published_reference')]
    else:
        snapshot['role_prompts'] = capture_role_prompts(db, user_id)
        snapshot['reference_library'] = capture_reference_library(db, user_id)
    from myink.models.platform import PlatformConfiguration
    policy = db.get(PlatformConfiguration, 1)
    snapshot['legacy_role_supplements'] = deepcopy(policy.document.get('prompts', {}) if policy else {})
    return deepcopy(snapshot)


def merge_automatic_selections(existing, automatic):
    """Upgrade missing automatic resources without replacing historical genre choices."""
    keys = {(item['origin'], item['resource_id']) for item in existing}
    frozen_kinds = {item['kind'] for item in existing if item['kind'] in ('genre', 'genre_rule', 'writing_rule', 'expression_rule')}
    return deepcopy(existing) + [item for item in automatic
        if item['kind'] not in frozen_kinds and (item['origin'], item['resource_id']) not in keys]


def frozen_book_genres(project, pack):
    """An existing long book owns its genre fields, even before resource snapshots existed."""
    from myink.genre_catalog import FIELD_KEYS, setup_capabilities
    publications = {item['resource_id']: item for item in pack.get('_resource_publications', [])}
    definitions = [(pack.get('source_id'), pack.get('source_name') or project.genre, pack)]
    if pack.get('secondary_id'):
        definitions.append((pack['secondary_id'], pack.get('secondary_name') or pack['secondary_id'],
                            pack.get('_secondary_snapshot') or {}))
    result = []
    for index, (catalog_id, name, fields) in enumerate(definitions):
        publication = publications.get('genre:' + str(catalog_id), {})
        result.append(dict(resource_id=publication.get('resource_id', f'book-genre:{project.id}:{index}'),
            origin='platform', name=name, kind='genre', version=publication.get('version', 1),
            generation=publication.get('generation', 0), personal_override=False,
            body={'catalog_id': catalog_id or '',
                  'fields': {key: deepcopy(fields[key]) for key in FIELD_KEYS if key in fields},
                  'setup_caps': setup_capabilities(fields if index == 0 else dict(fields, source_id=catalog_id))}))
    return result


def automatic_selections(db, pid, uid):
    from myink.models import Project, ProjectSettings
    from myink.genre_catalog import resolve_pack_id
    from myink.creation import DRAFT_STATES
    project = db.get(Project, uuid.UUID(str(pid)))
    if project is None:
        return []
    settings = db.scalar(select(ProjectSettings).where(ProjectSettings.project_id == project.id))
    pack = settings.genre_pack if settings else {}
    ids = [pack.get('source_id') or resolve_pack_id(project.genre, db=db), pack.get('secondary_id')]
    ids = [value for value in ids if value]
    personal = {row.source_resource_id: row for row in db.scalars(select(PersonalWritingResource).where(
        PersonalWritingResource.user_id == uuid.UUID(str(uid)), PersonalWritingResource.source_resource_id.is_not(None)))}
    genre_locked = project.form == 'long' and project.creation_status not in DRAFT_STATES
    result = frozen_book_genres(project, pack) if genre_locked else []
    for document in catalog(db, include_automatic=True):
        kind, body = document['kind'], document['body']
        if kind not in ('genre', 'genre_rule', 'role_prompt', 'reference', 'writing_rule', 'expression_rule'):
            continue
        if kind == 'genre' and (genre_locked or body.get('catalog_id') not in ids):
            continue
        if kind == 'genre_rule' and body.get('genre_ids') and not set(body['genre_ids']).intersection(ids):
            continue
        owned = personal.get(document['id'])
        canonical = out(owned) if owned else document
        frozen = deepcopy(canonical['body'])
        if kind == 'genre':
            # A personal wording change cannot change which book genre this resource belongs to.
            frozen['catalog_id'] = body['catalog_id']
        if kind == 'reference':
            if not is_writing_reference(document['name']):
                continue
            frozen['files'] = [f for f in frozen.get('files', []) if is_writing_reference(f['path'])]
            if not owned:
                frozen = {'files': [{'path': f['path']} for f in frozen['files']], 'published_reference': True}
        result.append(dict(resource_id=canonical['id'], origin='personal' if owned else 'platform',
            name=canonical['name'], kind=kind, version=canonical['current_version'], generation=canonical['generation'],
            body=frozen, personal_override=False))
    result.sort(key=lambda item: (0, ids.index(item['body']['catalog_id']) if item['body']['catalog_id'] in ids else 0) if item['kind'] == 'genre' else (1, item['resource_id']))
    return result


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


def capture_reference_library(db, user_id=None):
    overrides = linked_personal(db, user_id)
    result = []
    for row in db.scalars(select(WritingResource).where(
            WritingResource.kind == 'reference', WritingResource.status == 'published',
            WritingResource.current_version.is_not(None)).order_by(WritingResource.id)):
        pub = row.publication
        if not is_writing_reference(pub['name']):
            continue
        owned = overrides.get(row.id)
        files = [deepcopy(f) if owned else {'path': f['path']}
                 for f in (owned.body if owned else pub['body']).get('files', [])
                 if is_writing_reference(f['path'])]
        if files:
            result.append(dict(resource_id=row.id, version=row.current_version,
                               generation=pub['generation'], name=pub['name'],
                               source=pub['source'], files=files))
    return result


def linked_personal(db, user_id):
    if user_id is None:
        return {}
    return {row.source_resource_id: row for row in db.scalars(select(PersonalWritingResource).where(
        PersonalWritingResource.user_id == uuid.UUID(str(user_id)), PersonalWritingResource.source_resource_id.is_not(None)))}


def capture_role_prompts(db, user_id=None):
    overrides = linked_personal(db, user_id)
    result = {}
    for row in db.scalars(select(WritingResource).where(WritingResource.kind == 'role_prompt',
            WritingResource.status == 'published', WritingResource.current_version.is_not(None))):
        owned = overrides.get(row.id)
        canonical = out(owned) if owned else out(row, True)
        result[canonical['body']['role']] = dict(resource_id=canonical['id'], version=canonical['current_version'],
            generation=canonical['generation'], body=deepcopy(canonical['body']))
    return result

def save_snapshot(db, pid, expected, selections, dismissed=None, configured=None, automatic_initialized=None, defaults_initialized=None):
    from myink.writing_resource_schemas import validate_size, MAX_SNAPSHOT_BYTES
    try:
        validate_size(selections, MAX_SNAPSHOT_BYTES)
    except ValueError as exc:
        fail(422, str(exc))
    row = state(db, pid)
    if row is None:
        if expected != 0:
            fail(409, 'SNAPSHOT_CHANGED')
        row = ProjectWritingResources(project_id=uuid.UUID(str(pid)), revision=1, selections=deepcopy(selections), dismissed=dismissed or {}, configured=True if configured is None else configured, automatic_initialized=bool(automatic_initialized), defaults_initialized=bool(defaults_initialized))
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            fail(409, 'SNAPSHOT_CHANGED')
    else:
        values = dict(revision=expected + 1, selections=deepcopy(selections))
        if configured is not None:
            values['configured'] = configured
        if automatic_initialized is not None:
            values['automatic_initialized'] = automatic_initialized
        if defaults_initialized is not None:
            values['defaults_initialized'] = defaults_initialized
        if dismissed is not None:
            values['dismissed'] = dismissed
        changed = db.execute(update(ProjectWritingResources).where(ProjectWritingResources.project_id == row.project_id, ProjectWritingResources.revision == expected).values(**values).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            fail(409, 'SNAPSHOT_CHANGED')
        db.expire(row)
    return project_snapshot(db, pid)

def require_selection_editable(db, pid, uid):
    """Serialize future-rule changes with admission; admitted tasks retain their snapshot."""
    from myink.models import Project
    project = db.get(Project, uuid.UUID(str(pid)), with_for_update=True)
    if project is None or project.user_id != uuid.UUID(str(uid)):
        raise HTTPException(404, 'project_not_found')


def rule_source_key(db, uid, item):
    if item['origin'] == 'platform':
        return ('source', item['resource_id'])
    row = db.scalar(select(PersonalWritingResource).where(
        PersonalWritingResource.id == item['resource_id'],
        PersonalWritingResource.user_id == uuid.UUID(str(uid))))
    return ('source', row.source_resource_id) if row and row.source_resource_id else ('personal', item['resource_id'])


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
        if previous and previous['kind'] == 'reference':
            fail(422, 'REFERENCE_IS_AUTOMATIC')
        if previous and previous['kind'] in ('genre', 'genre_rule', 'role_prompt'):
            fail(422, 'GENRE_RESOURCE_IS_AUTOMATIC')
        explicit_override = (
            item.get('personal_override') and item.get('body') is not None
        )
        if previous is not None:
            saved = deepcopy(previous)
            if explicit_override:
                from myink.writing_resource_schemas import validate_resource_body
                try:
                    validate_resource_body(saved['kind'], item['body'])
                except ValueError as exc:
                    fail(422, str(exc))
                saved['body'] = deepcopy(item['body'])
                saved['personal_override'] = True
                if saved['kind'] == 'style':
                    saved['authoritative_style'] = True
            result.append(saved)
            continue
        # New selections take the current library version. Existing selections
        # keep their frozen version until explicit adoption or a project edit.
        row = resource(db, item['resource_id'], uid if item['origin'] == 'personal' else None)
        if row.kind in ('reference', 'role_prompt'):
            fail(422, 'REFERENCE_IS_AUTOMATIC' if row.kind == 'reference' else 'ROLE_PROMPT_IS_AUTOMATIC')
        if row.kind in ('genre', 'genre_rule'):
            fail(422, 'GENRE_RESOURCE_IS_AUTOMATIC')
        if row.kind == 'role_prompt':
            fail(422, 'ROLE_PROMPT_IS_AUTOMATIC')
        if row.status != 'published' or row.current_version is None:
            fail(409, 'RESOURCE_NOT_PUBLISHED')
        canonical = out(row, item['origin'] == 'platform')
        override = item.get('personal_override', False)
        result.append(dict(resource_id=row.id, origin=item['origin'], name=canonical['name'], kind=row.kind, version=row.current_version, generation=canonical['generation'], body=deepcopy(item['body'] if override and item.get('body') is not None else canonical['body']), personal_override=override, **({'authoritative_style': True} if row.kind == 'style' else {})))
    # This endpoint receives an explicit selection, including an intentional [].
    # Only genre/context resources are automatic; omitted rules must stay omitted.
    automatic = [deepcopy(item) for item in existing.values() if item['kind'] in ('genre', 'genre_rule', 'role_prompt', 'reference')]
    stored = state(db, pid)
    automatic_needed = stored is None or not stored.automatic_initialized
    if automatic_needed:
        automatic = merge_automatic_selections(automatic, initialization_selections(db, pid, uid, True, False))
    keys = {(item['origin'], item['resource_id']) for item in result}
    chosen_rule_sources = set()
    for item in result:
        if item['kind'] not in ('writing_rule', 'expression_rule'):
            continue
        lineage = rule_source_key(db, uid, item)
        if lineage in chosen_rule_sources:
            fail(422, 'DUPLICATE_RESOURCE_SOURCE')
        chosen_rule_sources.add(lineage)
    for item in automatic:
        if (item['origin'], item['resource_id']) in keys:
            continue
        result.append(item)
    was_managed = bool(stored and (stored.dismissed or {}).get(_STYLE_MANAGED_KEY))
    has_managed_style = any(item['kind'] == 'style' and item.get('authoritative_style') for item in list(existing.values()) + result)
    dismissed = dict(stored.dismissed or {}) if stored else {}
    if was_managed or has_managed_style:
        dismissed[_STYLE_MANAGED_KEY] = True
    return save_snapshot(db, pid, expected, result, dismissed=dismissed, configured=True, automatic_initialized=True, defaults_initialized=True)

def snapshot_source(db, pid, item, lock=False):
    if item['origin'] == 'platform':
        source = db.get(WritingResource, item['resource_id'])
    else:
        from myink.models import Project
        project = db.get(Project, uuid.UUID(str(pid)))
        if project is None:
            return None
        source = db.scalar(select(PersonalWritingResource).where(
            PersonalWritingResource.id == item['resource_id'], PersonalWritingResource.user_id == project.user_id))
    if source is not None and lock:
        db.refresh(source, with_for_update=True)
    return source


def updates(db, pid):
    row = state(db, pid)
    if row is None:
        return []
    from myink.models import Project
    from myink.creation import DRAFT_STATES
    project = db.get(Project, uuid.UUID(str(pid)))
    genre_locked = project is not None and project.form == 'long' and project.creation_status not in DRAFT_STATES
    result = []
    for item in row.selections:
        if item['kind'] == 'genre' and genre_locked:
            continue
        source = snapshot_source(db, pid, item)
        if source is None or source.status != 'published':
            continue
        pub = out(source, item['origin'] == 'platform')
        if pub['generation'] == item['generation']:
            continue
        if all(item[k] == pub[k] for k in ('name', 'kind', 'body')):
            continue
        publication = source.publication if item['origin'] == 'platform' else {}
        result.append(dict(resource_id=source.id, name=pub['name'], kind=pub['kind'], current_version=item['version'], target_version=source.current_version, target_generation=pub['generation'], action=publication.get('action','publish'), note=publication.get('note','个人版本更新'), dismissed=row.dismissed.get(source.id) == pub['generation']))
    return result

def check_updates(db, pid, requested):
    available = {i['resource_id']: i for i in updates(db, pid)}
    if len({i['resource_id'] for i in requested}) != len(requested):
        fail(422, 'DUPLICATE_RESOURCE')
    for item in requested:
        current = available.get(item['resource_id'])
        if not current or current['target_generation'] != item['target_generation']:
            fail(409, 'PUBLICATION_CHANGED')
        selected = next(s for s in project_snapshot(db, pid)['selections'] if s['resource_id'] == item['resource_id'])
        source = snapshot_source(db, pid, selected, lock=True)
        if source is None or source.status != 'published' or out(source, selected['origin'] == 'platform')['generation'] != item['target_generation']:
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
    from myink.models import Project
    from myink.creation import DRAFT_STATES
    project = db.get(Project, uuid.UUID(str(pid)), with_for_update=True)
    check_updates(db, pid, requested)
    selected = project_snapshot(db, pid)['selections']
    targets = {i['resource_id'] for i in requested}
    for item in selected:
        if item['resource_id'] not in targets:
            continue
        if item['kind'] == 'genre' and project is not None and project.form == 'long' and project.creation_status not in DRAFT_STATES:
            fail(409, '长篇建书完成后不可更改题材')
        source = snapshot_source(db, pid, item)
        canonical = out(source, item['origin'] == 'platform')
        body = deepcopy(canonical['body'])
        if item['kind'] == 'reference' and item['origin'] == 'platform':
            body = {'files': [{'path': f['path']} for f in body.get('files', []) if is_writing_reference(f['path'])], 'published_reference': True}
        item.update(name=canonical['name'], body=body, version=source.current_version, generation=canonical['generation'], personal_override=False)
        if item['kind'] == 'style':
            item['authoritative_style'] = True
    return save_snapshot(db, pid, expected, selected)

def initialize_builtin_resources(db):
    from myink.writing_resource_seed import builtin_resources
    for item in builtin_resources():
        data = deepcopy(item)
        rid = data.pop('id')
        if db.get(WritingResource, rid) is None:
            row = create_resource(db, data, rid=rid)
            publish(db, row.id, 0, 'Built-in initial publication')


def published_source(db, rid, target):
    row = resource(db, rid)
    db.refresh(row, with_for_update=True)
    if row.status != 'published' or not row.current_version:
        fail(409, 'RESOURCE_NOT_PUBLISHED')
    if row.publication.get('generation') != target:
        fail(409, 'PUBLICATION_CHANGED')
    return row


def copy_platform(db, rid, uid, target, name=None, body=None):
    source = published_source(db, rid, target)
    owner = uuid.UUID(str(uid))
    if db.scalar(select(PersonalWritingResource.id).where(
            PersonalWritingResource.user_id == owner,
            PersonalWritingResource.source_resource_id == rid)):
        fail(409, 'PERSONAL_RESOURCE_ALREADY_EXISTS')
    document = source.publication
    personal_body = deepcopy(body if body is not None else document['body'])
    from myink.writing_resource_schemas import validate_resource_body
    try:
        validate_resource_body(document['kind'], personal_body)
    except ValueError as exc:
        fail(422, str(exc))
    if document['kind'] == 'role_prompt' and personal_body.get('role') != document['body']['role']:
        fail(422, 'ROLE_PROMPT_ROLE_IMMUTABLE')
    if document['kind'] == 'genre' and personal_body.get('catalog_id') != document['body'].get('catalog_id'):
        fail(422, 'GENRE_CATALOG_ID_IMMUTABLE')
    row = PersonalWritingResource(user_id=owner, source_resource_id=rid,
        source_generation=target, name=name or document['name'], kind=document['kind'],
        source=document['source'], body=personal_body, status='published', generation=1, current_version=1)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        fail(409, 'PERSONAL_RESOURCE_ALREADY_EXISTS')
    return row


def sync_personal(db, rid, uid, expected, target, acknowledge):
    if acknowledge is not True:
        fail(422, 'OVERWRITE_ACKNOWLEDGEMENT_REQUIRED')
    row = resource(db, rid, uid)
    if not row.source_resource_id:
        fail(409, 'PERSONAL_RESOURCE_HAS_NO_SOURCE')
    source = published_source(db, row.source_resource_id, target)
    document = source.publication
    cas(db, row, expected, dict(name=document['name'], source=document['source'],
        body=deepcopy(document['body']), source_generation=target,
        current_version=(row.current_version or 0) + 1))
    return row
