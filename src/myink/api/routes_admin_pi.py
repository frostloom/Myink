"""Admin-only Pi reporting and explicit human publication decisions."""
from datetime import date
from typing import Annotated, Literal
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from myink.api.auth import require_admin, _AuthenticatedUser
from myink.api.routes_admin import write_access_log, _safe_target
from myink.api.admin_schemas import AdminPage
from myink.api.pi_schemas import PiDecision, PiOperation, PiStatus
from myink.config import settings
from myink.pi_console import (PiConsoleClient, PiConsoleUnavailable, PiConsoleNotConfigured,
                              PiConsoleConflict, PiConsoleNotFound)

router = APIRouter(prefix='/api/v1/admin/pi', tags=['admin-pi'])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=1000000)]
EventKind = Literal['observation','analysis','plan','review','tool','development','test','deployment','rollback','followup','version','enhancement','memory']


def _console():
    if not settings.pi_console_socket or not settings.pi_console_token_file: raise PiConsoleNotConfigured()
    return PiConsoleClient(settings.pi_console_socket, settings.pi_console_token_file)


def _audit(actor, action, target):
    try: write_access_log(actor.id, action, target)
    except Exception: raise HTTPException(503, 'ADMIN_AUDIT_UNAVAILABLE') from None


def _actor(request: Request, actor: _AuthenticatedUser = Depends(require_admin)):
    _audit(actor, request.scope['route'].name, _safe_target(request))
    return actor


def _fetch(method, path, *, params=None, body=None, model=None):
    try:
        data = _console().call(method, path, params=params, body=body)
        return model.model_validate(data) if model else data
    except PiConsoleConflict: raise HTTPException(409, 'PI_CANDIDATE_CHANGED_OR_BUSY') from None
    except PiConsoleNotFound: raise HTTPException(404, 'PI_RECORD_NOT_FOUND') from None
    except PiConsoleUnavailable as error: raise HTTPException(503, error.code) from None
    except (ValidationError, ValueError, TypeError): raise HTTPException(503, 'PI_CONSOLE_UNAVAILABLE') from None


@router.get('/status', response_model=PiStatus, name='admin.pi.status')
def status(actor: _AuthenticatedUser = Depends(_actor)):
    return _fetch('GET', '/v1/status', model=PiStatus)


@router.get('/runs', response_model=AdminPage[dict], name='admin.pi.runs')
def runs(limit: Limit = 25, offset: Offset = 0, day: date | None = None,
         actor: _AuthenticatedUser = Depends(_actor)):
    params = dict(limit=limit, offset=offset)
    if day is not None: params['day'] = day.isoformat()
    return _fetch('GET', '/v1/runs', params=params, model=AdminPage[dict])


@router.get('/events', response_model=AdminPage[dict], name='admin.pi.events')
def events(run_id: Annotated[str, Query(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$')],
           limit: Limit = 25, offset: Offset = 0, kind: EventKind | None = None,
           actor: _AuthenticatedUser = Depends(_actor)):
    params = dict(run_id=run_id, limit=limit, offset=offset)
    if kind is not None: params['kind'] = kind
    return _fetch('GET', '/v1/events', params=params, model=AdminPage[dict])


@router.get('/daily', response_model=dict, name='admin.pi.daily')
def daily(day: date, actor: _AuthenticatedUser = Depends(_actor)):
    data = _fetch('GET', '/v1/daily', params=dict(day=day.isoformat()))
    if data.get('schema_version') != 1 or data.get('authority') != 'audit_only' or data.get('day') != day.isoformat():
        raise HTTPException(503, 'PI_CONSOLE_UNAVAILABLE')
    return data


@router.get('/enhancements', response_model=AdminPage[dict], name='admin.pi.enhancements')
def enhancements(limit: Limit = 25, offset: Offset = 0, actor: _AuthenticatedUser = Depends(_actor)):
    return _fetch('GET', '/v1/enhancements', params=dict(limit=limit, offset=offset), model=AdminPage[dict])


@router.get('/operations/{operation_id}', response_model=PiOperation, name='admin.pi.operation')
def operation(operation_id: uuid.UUID, actor: _AuthenticatedUser = Depends(_actor)):
    return _fetch('GET', '/v1/operations/'+str(operation_id), model=PiOperation)


@router.post('/decisions', response_model=PiOperation, status_code=202, name='admin.pi.decision')
def decision(body: PiDecision, actor: _AuthenticatedUser = Depends(require_admin)):
    _audit(actor, 'admin.pi.decision', f'cycle_id={body.cycle_id},request_id={body.request_id}')
    packet = dict(body.model_dump(mode='json'), actor_id=str(actor.id))
    return _fetch('POST', '/v1/decisions', body=packet, model=PiOperation)
