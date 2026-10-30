"""Strict request and response contracts for writing resources."""
import json
from typing import Literal
from pathlib import PurePosixPath
from pydantic import BaseModel, ConfigDict, Field, model_validator
MAX_RESOURCE_BYTES = 256 * 1024
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_REFERENCE_FILES = 80


def validate_size(value, limit):
    try:
        size = len(json.dumps(value, ensure_ascii=False).encode('utf-8'))
    except (RecursionError, ValueError) as exc:
        raise ValueError('Invalid resource structure') from exc
    if size > limit:
        raise ValueError(f'Resource exceeds {limit} bytes')


Kind = Literal['reference', 'genre', 'genre_rule', 'style', 'writing_rule', 'expression_rule', 'role_prompt']

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class BoundedBody(Strict):
    @model_validator(mode='after')
    def bounded_body(self):
        body = getattr(self, 'body', None)
        if body is not None:
            validate_size(body, MAX_RESOURCE_BYTES)
        return self

class CreateResource(BoundedBody):
    name: str = Field(min_length=1, max_length=200)
    kind: Kind
    source: str = Field(max_length=2000)
    body: dict

    @model_validator(mode='after')
    def validate_body(self):
        validate_resource_body(self.kind, self.body)
        return self

def validate_resource_body(kind, body):
    validate_size(body, MAX_RESOURCE_BYTES)
    required = {'reference': 'files', 'genre': 'fields', 'genre_rule': 'roles', 'style': 'profile', 'writing_rule': 'roles', 'expression_rule': 'roles', 'role_prompt': 'templates'}[kind]
    if required not in body:
        raise ValueError(f'{required} required')
    if kind == 'role_prompt':
        from myink.prompt_catalog import prompt_catalog
        group = next((g for g in prompt_catalog() if g['role'] == body.get('role')), None)
        if group is None or set(body) - {'role', 'templates', 'supplement'} or not {'role', 'templates'} <= set(body):
            raise ValueError('Invalid role prompt body')
        if 'supplement' in body and not isinstance(body['supplement'], str):
            raise ValueError('supplement must be text')
        templates = body['templates']
        if not isinstance(templates, dict) or not templates or set(templates) - {t['id'] for t in group['templates']} or any(not isinstance(v, str) or not v.strip() for v in templates.values()):
            raise ValueError('Role templates must contain known phases as nonempty text')
    if kind == 'reference':
        if not isinstance(body['files'], list):
            raise ValueError('files must be an array')
        if len(body['files']) > MAX_REFERENCE_FILES:
            raise ValueError('Too many reference files (maximum 80)')
        for file in body['files']:
            if not isinstance(file, dict):
                raise ValueError('file must be an object')
            path = file.get('path', '')
            if not isinstance(path, str):
                raise ValueError('path must be text')
            if len(path) > 240:
                raise ValueError('Reference path exceeds 240 characters')
            if not path or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts or ('\\' in path) or (not isinstance(file.get('content'), str)):
                raise ValueError('Invalid corpus file')
    elif not isinstance(body[required], dict):
        raise ValueError(f'{required} must be an object')
    if kind in ('genre_rule', 'writing_rule', 'expression_rule') and any((not isinstance(v, str) for v in body['roles'].values())):
        raise ValueError('roles must contain text')
    if kind in ('genre_rule', 'writing_rule', 'expression_rule'):
        allowed = {'writer', 'planner', 'audit', 'extract', 'summarize', 'validator_l2'}
        if set(body['roles']) - allowed:
            raise ValueError('Unknown role')
    if kind == 'genre':
        from myink.genre_catalog import empty_fields
        fields = body['fields']
        expected = empty_fields()
        if set(fields) - set(expected):
            raise ValueError('Unknown genre field')
        for key, value in fields.items():
            if not isinstance(value, type(expected[key])):
                raise ValueError('Invalid genre field type')
            if key == 'subgenres':
                for subgenre in value:
                    if (
                        not isinstance(subgenre, dict)
                        or set(subgenre) != {'name', 'hook'}
                        or any(not isinstance(text, str) for text in subgenre.values())
                    ):
                        raise ValueError('subgenres must contain name/hook text objects')
            elif isinstance(value, list) and any(not isinstance(v, str) for v in value):
                raise ValueError('Invalid genre field type')
        if 'setup_caps' in body:
            validate_boolean_options(
                body['setup_caps'],
                {'power_scaling', 'numerical_system', 'era_research'},
                'setup_caps',
            )
    if 'validation' in body:
        validate_boolean_options(body['validation'], {'not_is', 'parallel'}, 'validation')
    if kind == 'genre' and (not isinstance(body.get('catalog_id'), str)):
        raise ValueError('catalog_id required')
    if kind == 'genre_rule' and (not isinstance(body.get('genre_ids'), list) or any((not isinstance(v, str) for v in body['genre_ids']))):
        raise ValueError('genre_ids required')


def validate_boolean_options(value, allowed, field):
    if not isinstance(value, dict):
        raise ValueError(f'{field} must be an object')
    if set(value) - allowed:
        raise ValueError(f'Unknown {field} option')
    if any(type(flag) is not bool for flag in value.values()):
        raise ValueError(f'{field} options must be booleans')


class UpdateResource(BoundedBody):
    expected_generation: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=200)
    source: str = Field(max_length=2000)
    body: dict
    status: Literal['draft', 'archived'] | None = None

class CopyPlatform(BoundedBody):
    source_resource_id: str = Field(min_length=1, max_length=160)
    target_generation: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    body: dict | None = None

class SyncPersonal(Strict):
    expected_generation: int = Field(ge=1)
    target_generation: int = Field(ge=1)
    acknowledge_overwrite: bool = Field(strict=True)

class Publish(Strict):
    expected_generation: int = Field(ge=0)
    note: str = Field(default='', max_length=4000)

class Rollback(Publish):
    version: int = Field(ge=1)

class SelectionInput(BoundedBody):
    origin: Literal['platform', 'personal']
    resource_id: str = Field(min_length=1, max_length=160)
    personal_override: bool = False
    body: dict | None = None

class SelectionBody(Strict):
    expected_revision: int = Field(ge=0)
    selections: list[SelectionInput] = Field(max_length=200)

    @model_validator(mode='after')
    def bounded_selections(self):
        validate_size([item.model_dump() for item in self.selections], MAX_SNAPSHOT_BYTES)
        return self

class UpdateTarget(Strict):
    resource_id: str
    target_generation: int = Field(ge=1)

class DismissBody(Strict):
    updates: list[UpdateTarget] = Field(max_length=200)

class AdoptBody(DismissBody):
    expected_revision: int = Field(ge=0)

class ResourceOut(Strict):
    source_resource_id: str | None = None
    source_generation: int | None = None
    id: str
    name: str
    kind: Kind
    source: str
    status: Literal['draft', 'published', 'archived']
    generation: int
    current_version: int | None
    body: dict

class ResourceList(Strict):
    items: list[ResourceOut]

class RevisionOut(Strict):
    version: int
    name: str
    source: str
    kind: Kind
    body: dict
    created_at: str
    action: Literal['publish', 'rollback', 'initial']
    note: str

class RevisionList(Strict):
    items: list[RevisionOut]

class SelectionOut(Strict):
    authoritative_style: bool = False
    resource_id: str
    origin: Literal['platform', 'personal']
    name: str
    kind: Kind
    version: int
    generation: int
    body: dict
    personal_override: bool

class SnapshotOut(Strict):
    style_managed: bool = False
    revision: int
    configured: bool
    selections: list[SelectionOut]

class UpdateOut(Strict):
    resource_id: str
    name: str
    kind: Kind
    current_version: int
    target_version: int
    target_generation: int
    action: Literal['publish', 'rollback']
    note: str
    dismissed: bool

class UpdateList(Strict):
    items: list[UpdateOut]

class OkOut(Strict):
    ok: bool
