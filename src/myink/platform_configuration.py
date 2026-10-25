"""Central platform resources and published writer model selection policy."""
from copy import deepcopy
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from myink.db import new_session
from myink.models.platform import PlatformConfiguration
from myink.api.routes_settings import ModelConnectionBody
from myink.user_defaults import UserDefaults, merge_defaults, platform_defaults

USER_ROLES = frozenset({'writer', 'planner'})
PLATFORM_ROLES = frozenset({'writer', 'planner', 'extract', 'validator_l2', 'audit', 'summarize'})


class PlatformConnectionBody(ModelConnectionBody):
    enabled: bool = True
    user_visible: bool = True


class GenreFields(BaseModel):
    model_config = ConfigDict(extra='forbid')
    selling_point: str | None = Field(None, max_length=10000)
    pacing: str | None = Field(None, max_length=10000)
    subgenres: list[dict[str, str]] | None = None
    taboos: list[str] | None = None
    satisfaction: list[str] | None = None
    mechanics: list[str] | None = None
    world_hints: list[str] | None = None


class ConfigurationBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_defaults: UserDefaults = Field(default_factory=UserDefaults)
    version: int = Field(ge=0)
    model_connections: list[PlatformConnectionBody]
    model_routes: dict[str, str]
    prompts: dict[str, str]
    genre_packs: dict[str, GenreFields]


class PublishedModel(BaseModel):
    id: str
    name: str


class ModelCatalogOut(BaseModel):
    models: list[PublishedModel]
    model_routes: dict[str, str]


class PlatformConnectionOut(BaseModel):
    origin: Literal['builtin', 'custom'] = 'custom'
    id: str
    name: str
    protocol: str
    base_url: str
    model: str
    input_price: float | None = None
    output_price: float | None = None
    has_api_key: bool
    enabled: bool
    user_visible: bool


class ConfigurationOut(BaseModel):
    user_defaults: UserDefaults = Field(default_factory=UserDefaults)
    version: int
    model_connections: list[PlatformConnectionOut]
    model_routes: dict[str, str]
    prompts: dict[str, str]
    genre_packs: dict[str, GenreFields]


def empty_configuration():
    return {'version': 0, 'connections': {}, 'model_routes': {}, 'prompts': {}, 'genre_packs': {}}


# A deployment model is imported once, then follows ordinary administrator policy.
BUILTIN_MODEL_ID = str(uuid5(NAMESPACE_URL, 'myink:platform-deployment-model'))


def initialize_builtin_model(db, deployment_settings=None) -> bool:
    """Import deployment credentials during explicit CLI initialization, never API reads.

    Caller owns the transaction. The durable marker prevents later initialization
    from undoing an administrator's deletion or replacing edited credentials.
    """
    from myink.config import settings
    from myink.providers.credentials import encrypt_api_key
    deployment_settings = settings if deployment_settings is None else deployment_settings
    if not (deployment_settings.platform_model_api_key and deployment_settings.platform_model_base_url
            and deployment_settings.platform_model_name):
        return False
    row = db.scalar(select(PlatformConfiguration).where(PlatformConfiguration.id == 1).with_for_update())
    document = deepcopy(row.document) if row else {k: v for k, v in empty_configuration().items() if k != 'version'}
    if document.get('builtin_model_imported'):
        return False
    connections = document.setdefault('connections', {})
    if BUILTIN_MODEL_ID not in connections:
        connections[BUILTIN_MODEL_ID] = {
            'name': deployment_settings.platform_model_name,
            'model': deployment_settings.platform_model_name,
            'protocol': deployment_settings.platform_model_protocol,
            'base_url': deployment_settings.platform_model_base_url,
            'api_key_encrypted': encrypt_api_key(deployment_settings.platform_model_api_key),
            'enabled': True, 'user_visible': True, 'origin': 'builtin',
        }
    document.setdefault('model_routes', {}).setdefault('writer', f'custom:{BUILTIN_MODEL_ID}')
    document['builtin_model_imported'] = True
    if row:
        row.document = document
        row.version += 1
    else:
        db.add(PlatformConfiguration(id=1, version=1, document=document))
    db.flush()
    return True


def load_configuration() -> dict:
    # Storage errors must propagate: falling back would silently bypass policy.
    with new_session() as db:
        row = db.get(PlatformConfiguration, 1)
        return {'version': row.version, **deepcopy(row.document)} if row else empty_configuration()


def public_configuration(config=None) -> dict:
    from myink.providers.connections import public_connections
    config = load_configuration() if config is None else config
    items = public_connections(config['connections'])
    for item in items:
        record = config['connections'][item['id']]
        item.update(enabled=record.get('enabled', True), user_visible=record.get('user_visible', True),
                    origin=record.get('origin', 'custom'))
    return {'version': config['version'], 'model_connections': items,
            'user_defaults': platform_defaults(config),
            **{k: deepcopy(config[k]) for k in ('model_routes', 'prompts', 'genre_packs')}}


def save_configuration(body: ConfigurationBody) -> dict:
    from myink.api.routes_settings import connection_record
    from myink.genre_catalog import PACKS, _clean_fields
    old = load_configuration()
    if old['version'] != body.version:
        raise HTTPException(409, 'CONFIGURATION_VERSION_CONFLICT')
    connections = {}
    for item in body.model_connections:
        cid, record = connection_record(item, old['connections'])
        if cid in connections:
            raise HTTPException(400, 'Duplicate connection id')
        connections[cid] = {**record, 'enabled': item.enabled, 'user_visible': item.user_visible,
                            'origin': old['connections'].get(cid, {}).get('origin', 'custom')}
    for role, ref in body.model_routes.items():
        if role not in PLATFORM_ROLES or not ref.startswith('custom:') or not connections.get(ref[7:], {}).get('enabled'):
            raise HTTPException(400, 'Routes must reference enabled platform models')
    if connections and 'writer' not in body.model_routes:
        raise HTTPException(400, 'A platform writer default is required when models are configured')
    for role, prompt in body.prompts.items():
        if role not in PLATFORM_ROLES or len(prompt) > 20000:
            raise HTTPException(400, 'Invalid role prompt')
    genres = {}
    for pid, fields in body.genre_packs.items():
        if pid not in PACKS:
            raise HTTPException(400, 'Unknown genre pack')
        raw = fields.model_dump(exclude_unset=True, exclude_none=True)
        cleaned = _clean_fields(raw)
        genres[pid] = {key: cleaned[key] for key in raw}
    defaults = old.get('user_defaults', {})
    if 'user_defaults' in body.model_fields_set:
        defaults = merge_defaults(body.user_defaults.model_dump(mode='json', exclude_unset=True),
                                  platform_defaults(old))
    document = {'user_defaults': defaults, 'connections': connections, 'model_routes': body.model_routes,
                'prompts': body.prompts, 'genre_packs': genres}
    if old.get('builtin_model_imported'):
        document['builtin_model_imported'] = True
    with new_session() as db:
        if body.version == 0:
            db.add(PlatformConfiguration(id=1, version=1, document=document))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raise HTTPException(409, 'CONFIGURATION_VERSION_CONFLICT') from None
        else:
            result = db.execute(update(PlatformConfiguration).where(
                PlatformConfiguration.id == 1, PlatformConfiguration.version == body.version
            ).values(version=body.version + 1, document=document))
            if result.rowcount != 1:
                raise HTTPException(409, 'CONFIGURATION_VERSION_CONFLICT')
            db.commit()
    return public_configuration({'version': body.version + 1, **document})


def published_connections(config):
    return {cid: rec for cid, rec in config['connections'].items()
            if rec.get('enabled', True) and rec.get('user_visible', True)}


def catalog() -> dict:
    config = load_configuration()
    published = published_connections(config)
    return {'models': [{'id': f'custom:{cid}', 'name': rec['name']} for cid, rec in published.items()],
            'model_routes': {role: ref for role, ref in config['model_routes'].items()
                             if ref.startswith('custom:') and ref[7:] in published}}


def clean_user_routes(routes, config=None):
    published = published_connections(load_configuration() if config is None else config)
    return {role: ref for role, ref in routes.items() if role in USER_ROLES
            and isinstance(ref, str) and ref.startswith('custom:') and ref[7:] in published}


def validate_user_routes(routes):
    if clean_user_routes(routes) != routes:
        raise HTTPException(400, 'Select a published model for writer or planner')


def resolve_connection(role, selections=None, config=None):
    config = load_configuration() if config is None else config
    routes = clean_user_routes(selections or {}, config)
    if role not in PLATFORM_ROLES:
        return None
    ref = routes.get(role) or config['model_routes'].get(role) or config['model_routes'].get('writer', '')
    rec = config['connections'].get(ref[7:]) if ref.startswith('custom:') else None
    return rec if rec and rec.get('enabled', True) else None
