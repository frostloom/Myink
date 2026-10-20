"""Administrator resource management, separate from read-only reporting sessions."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from myink.api.auth import require_admin, require_user, _AuthenticatedUser
from myink.api.routes_admin import _audit_or_fail
from myink.api.routes_settings import ConnectionProbeBody, _clean_base_url, _assert_host_allowed
from myink.api.schemas import ModelListOut, ConnectionTestOut
from myink.platform_configuration import ConfigurationBody, ConfigurationOut, ModelCatalogOut, catalog, load_configuration, public_configuration, save_configuration
from myink.providers import probe
from myink.providers.credentials import decrypt_api_key

router = APIRouter(prefix='/api/v1', tags=['platform'])


def probe_key(body):
    key = body.api_key.get_secret_value().strip() if body.api_key else ''
    if not key and body.connection_id:
        rec = load_configuration()['connections'].get(body.connection_id, {})
        key = decrypt_api_key(rec.get('api_key_encrypted', ''))
    if not key:
        raise HTTPException(400, 'API key required')
    return key


@router.get('/model-catalog', dependencies=[Depends(require_user)], response_model=ModelCatalogOut)
def get_model_catalog(response: Response) -> dict:
    response.headers['Cache-Control'] = 'no-store'
    return catalog()


@router.get('/admin/configuration', response_model=ConfigurationOut, response_model_exclude_none=True)
def get_configuration(request: Request, response: Response, actor: _AuthenticatedUser = Depends(require_admin)) -> dict:
    response.headers['Cache-Control'] = 'no-store'
    _audit_or_fail(actor, request, 'admin.configuration.read')
    return public_configuration()


@router.put('/admin/configuration', response_model=ConfigurationOut, response_model_exclude_none=True)
def put_configuration(body: ConfigurationBody, request: Request, response: Response,
                      actor: _AuthenticatedUser = Depends(require_admin)) -> dict:
    response.headers['Cache-Control'] = 'no-store'
    _audit_or_fail(actor, request, 'admin.configuration.update')
    return save_configuration(body)


@router.post('/admin/configuration/models', response_model=ModelListOut)
def list_models(body: ConnectionProbeBody, request: Request, response: Response,
                actor: _AuthenticatedUser = Depends(require_admin)) -> dict:
    response.headers['Cache-Control'] = 'no-store'
    _audit_or_fail(actor, request, 'admin.configuration.models')
    url = _clean_base_url(body.base_url)
    _assert_host_allowed(url)
    models, error = probe.list_models(body.protocol, url, probe_key(body))
    return {'ok': error is None, 'models': models, 'error': error}


@router.post('/admin/configuration/test-connection', response_model=ConnectionTestOut)
def test_connection(body: ConnectionProbeBody, request: Request, response: Response,
                    actor: _AuthenticatedUser = Depends(require_admin)) -> dict:
    response.headers['Cache-Control'] = 'no-store'
    _audit_or_fail(actor, request, 'admin.configuration.test')
    model = (body.model or '').strip()
    if not model or len(model) > 160:
        raise HTTPException(400, 'Model id must be 1–160 characters')
    url = _clean_base_url(body.base_url)
    _assert_host_allowed(url)
    ok, latency, reply, error = probe.test_connection(body.protocol, url, probe_key(body), model)
    return {'ok': ok, 'latency_ms': latency, 'reply': reply, 'error': error}
