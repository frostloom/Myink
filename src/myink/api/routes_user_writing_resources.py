"""Account-private resources and explicitly owned project snapshots."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from myink.models import StyleLibraryItem
from myink.style_extract import validate_profile
from myink.api.auth import require_user, require_owner
from myink.db import new_session, tenant_session
from myink.models.writing_resource import PersonalWritingResource
from myink import writing_resources as svc
from myink.writing_resource_schemas import CopyPlatform, SyncPersonal, CreateResource, UpdateResource, SelectionBody, DismissBody, AdoptBody, ResourceOut, ResourceList, SnapshotOut, UpdateList, OkOut, validate_resource_body
router = APIRouter(prefix='/api/v1', tags=['writing-resources'])

def no_store(response: Response):
    response.headers['Cache-Control'] = 'no-store'
router.dependencies.append(Depends(no_store))

@router.get('/my-writing-resources', response_model=ResourceList)
def mine(uid: str=Depends(require_user)):
    with new_session() as db:
        return {'items': [svc.out(r) for r in db.scalars(select(PersonalWritingResource).where(PersonalWritingResource.user_id == uuid.UUID(uid)))]}

@router.post('/my-writing-resources', response_model=ResourceOut)
def create(body: CreateResource, uid: str=Depends(require_user)):
    with new_session() as db:
        row = svc.create_resource(db, body.model_dump(), user_id=uid)
        result = svc.out(row)
        db.commit()
        return result

@router.post('/my-writing-resources/import-legacy/{item_id}', response_model=ResourceOut)
def import_legacy_style(item_id: str, uid: str = Depends(require_user)):
    try:
        old_id = uuid.UUID(item_id)
    except (ValueError, TypeError):
        raise HTTPException(404, 'RESOURCE_NOT_FOUND') from None
    owner = uuid.UUID(uid)
    source_id = 'legacy-style:' + str(old_id)
    with new_session() as db:
        old = db.scalar(select(StyleLibraryItem).where(StyleLibraryItem.id == old_id, StyleLibraryItem.user_id == owner))
        if old is None:
            raise HTTPException(404, 'RESOURCE_NOT_FOUND')
        def existing():
            return db.scalar(select(PersonalWritingResource).where(
                PersonalWritingResource.user_id == owner, PersonalWritingResource.source_resource_id == source_id))
        row = existing()
        if row is None:
            try:
                profile = validate_profile(old.profile)
                body = {'profile': profile}
                validate_resource_body('style', body)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            data = dict(name=old.name, kind='style', source='旧版个人文风导入' + ('：' + old.note if old.note else ''), body=body)
            try:
                # The existing per-owner source uniqueness constraint makes retries
                # and simultaneous tabs converge on one private copy.
                with db.begin_nested():
                    row = svc.create_resource(db, data, user_id=uid)
                    row.source_resource_id = source_id
                    db.flush()
            except IntegrityError:
                row = existing()
                if row is None:
                    raise
            db.commit()
        return svc.out(row)


@router.post('/my-writing-resources/from-platform', response_model=ResourceOut)
def copy_platform(body: CopyPlatform, uid: str=Depends(require_user)):
    with new_session() as db:
        row = svc.copy_platform(db, body.source_resource_id, uid, body.target_generation, body.name, body.body)
        result = svc.out(row)
        db.commit()
        return result

@router.post('/my-writing-resources/{rid}/sync', response_model=ResourceOut)
def sync_personal(rid: str, body: SyncPersonal, uid: str=Depends(require_user)):
    with new_session() as db:
        row = svc.sync_personal(db, rid, uid, body.expected_generation, body.target_generation, body.acknowledge_overwrite)
        result = svc.out(row)
        db.commit()
        return result

@router.put('/my-writing-resources/{rid}', response_model=ResourceOut)
def edit(rid: str, body: UpdateResource, uid: str=Depends(require_user)):
    with new_session() as db:
        row = svc.resource(db, rid, uid)
        try:
            validate_resource_body(row.kind, body.body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        row = svc.update_resource(db, rid, body.expected_generation, body.model_dump(exclude={'expected_generation', 'status'}), user_id=uid)
        result = svc.out(row)
        db.commit()
        return result

@router.get('/projects/{project_id}/writing-resources', response_model=SnapshotOut, dependencies=[Depends(require_owner)])
def snapshot(project_id: str, uid: str=Depends(require_user)):
    with tenant_session(project_id) as db:
        return svc.ensure_project_resources(db, project_id, uid)

@router.put('/projects/{project_id}/writing-resources', response_model=SnapshotOut, dependencies=[Depends(require_owner)])
def select_resources(project_id: str, body: SelectionBody, uid: str=Depends(require_user)):
    with tenant_session(project_id) as db:
        svc.require_selection_editable(db, project_id, uid)
        previous = {(s['origin'], s['resource_id']): s
                    for s in svc.project_snapshot(db, project_id)['selections']}
        for item in body.selections:
            if item.personal_override and item.body is not None:
                old = previous.get((item.origin, item.resource_id))
                kind = old['kind'] if old and old['personal_override'] else svc.resource(
                    db, item.resource_id, uid if item.origin == 'personal' else None).kind
                try:
                    validate_resource_body(kind, item.body)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
        return svc.set_selection(db, project_id, uid, body.expected_revision, [i.model_dump() for i in body.selections])

@router.get('/projects/{project_id}/writing-resources/updates', response_model=UpdateList, dependencies=[Depends(require_owner)])
def updates(project_id: str, uid: str=Depends(require_user)):
    with tenant_session(project_id) as db:
        return {'items': svc.updates(db, project_id)}

@router.post('/projects/{project_id}/writing-resources/dismiss', response_model=OkOut, dependencies=[Depends(require_owner)])
def dismiss(project_id: str, body: DismissBody, uid: str=Depends(require_user)):
    with tenant_session(project_id) as db:
        svc.dismiss(db, project_id, [i.model_dump() for i in body.updates])
    return {'ok': True}

@router.post('/projects/{project_id}/writing-resources/adopt', response_model=SnapshotOut, dependencies=[Depends(require_owner)])
def adopt(project_id: str, body: AdoptBody, uid: str=Depends(require_user)):
    with tenant_session(project_id) as db:
        return svc.adopt(db, project_id, body.expected_revision, [i.model_dump() for i in body.updates])
