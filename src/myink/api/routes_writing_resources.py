"""Audited admin resource publication and published-only public catalog."""
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from sqlalchemy import select
from myink.api.auth import require_admin, require_user, _AuthenticatedUser
from myink.api.routes_admin import _audit_or_fail
from myink.db import new_session
from myink.models.writing_resource import WritingResource
from myink import writing_resources as svc
from myink.writing_resource_schemas import CreateResource, UpdateResource, Publish, Rollback, ResourceOut, ResourceList, RevisionList, validate_resource_body
router = APIRouter(prefix='/api/v1', tags=['writing-resources'])

def admin_guard(request: Request, response: Response, actor: _AuthenticatedUser=Depends(require_admin)):
    response.headers['Cache-Control'] = 'no-store'
    _audit_or_fail(actor, request, 'admin.writing_resources.' + request.method.lower())

@router.get('/writing-resources', response_model=ResourceList, dependencies=[Depends(require_user)])
def catalog(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    with new_session() as db:
        return {'items': svc.catalog(db)}

@router.get('/admin/writing-resources', response_model=ResourceList, dependencies=[Depends(admin_guard)])
def list_resources():
    with new_session() as db:
        return {'items': [svc.out(r) for r in db.scalars(select(WritingResource).order_by(WritingResource.id))]}

@router.post('/admin/writing-resources', response_model=ResourceOut, dependencies=[Depends(admin_guard)])
def create(body: CreateResource):
    with new_session() as db:
        row = svc.create_resource(db, body.model_dump())
        result = svc.out(row)
        db.commit()
        return result

@router.put('/admin/writing-resources/{rid}', response_model=ResourceOut, dependencies=[Depends(admin_guard)])
def edit(rid: str, body: UpdateResource):
    with new_session() as db:
        row = svc.resource(db, rid)
        try:
            validate_resource_body(row.kind, body.body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        row = svc.update_resource(db, rid, body.expected_generation, body.model_dump(exclude={'expected_generation'}))
        result = svc.out(row)
        db.commit()
        return result

@router.get('/admin/writing-resources/{rid}/revisions', response_model=RevisionList, dependencies=[Depends(admin_guard)])
def revisions(rid: str):
    with new_session() as db:
        return {'items': svc.revisions(db, rid)}

@router.post('/admin/writing-resources/{rid}/publish', response_model=ResourceOut, dependencies=[Depends(admin_guard)])
def publish(rid: str, body: Publish):
    with new_session() as db:
        row = svc.publish(db, rid, body.expected_generation, body.note)
        result = svc.out(row)
        db.commit()
        return result

@router.post('/admin/writing-resources/{rid}/rollback', response_model=ResourceOut, dependencies=[Depends(admin_guard)])
def rollback(rid: str, body: Rollback):
    with new_session() as db:
        row = svc.publish(db, rid, body.expected_generation, body.note, body.version)
        result = svc.out(row)
        db.commit()
        return result
