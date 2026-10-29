"""Admin prompt inventory reads the live runtime templates, never copied placeholders."""
import itertools
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient


def test_catalog_covers_every_runtime_system_template_and_role():
    from myink.prompt_catalog import prompt_catalog
    from myink.workflow import prompts
    roles = prompt_catalog()
    assert {role['role'] for role in roles} == {'writer','planner','extract','validator_l2','audit','summarize'}
    templates = [template for role in roles for template in role['templates']]
    constants = {name for name in vars(prompts) if name.startswith('SYSTEM_')}
    assert constants <= {template['source'].split(':')[-1] for template in templates}
    for template in templates:
        assert template['content'].strip()
        if template['source'].split(':')[-1] in constants:
            assert template['content'] == getattr(prompts,template['source'].split(':')[-1])


def test_catalog_follows_the_actual_runtime_source_without_duplicating_it(monkeypatch):
    from myink.prompt_catalog import prompt_catalog
    from myink.workflow import prompts
    monkeypatch.setattr(prompts,'SYSTEM_WRITE','runtime-updated-writer-template')
    writer = next(role for role in prompt_catalog() if role['role']=='writer')
    assert next(item for item in writer['templates'] if item['id']=='system_write')['content'] == prompts.SYSTEM_WRITE


def test_dynamic_setup_catalog_uses_the_same_builder_for_every_capability_combination():
    from myink.prompt_catalog import prompt_catalog
    from myink.workflow import prompts
    planner = next(role for role in prompt_catalog() if role['role']=='planner')
    dynamic = [item for item in planner['templates'] if item['source'].endswith(':book_setup_system')]
    assert len(dynamic) == 8
    for flags in itertools.product((False,True),repeat=3):
        caps = dict(zip(('power_scaling','numerical_system','era_research'),flags))
        assert any(item['content'] == prompts.book_setup_system(caps) for item in dynamic)


def test_admin_prompt_templates_are_protected_audited_and_not_cached(monkeypatch):
    from myink.api.main import app
    from myink.api.auth import require_admin
    from myink.api import routes_platform
    audits=[]
    monkeypatch.setattr(routes_platform,'_audit_or_fail',lambda actor,request,action: audits.append(action))
    with TestClient(app) as client:
        denied=client.get('/api/v1/admin/configuration/prompt-templates')
        assert denied.status_code == 401
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=uuid.uuid4())
        try:
            response=client.get('/api/v1/admin/configuration/prompt-templates')
        finally:
            app.dependency_overrides.pop(require_admin,None)
    assert response.status_code == 200
    assert response.headers['cache-control']=='no-store'
    assert 'admin.configuration.prompt_templates' in audits
    assert len(response.json())==6


def test_short_plan_review_is_grouped_with_its_actual_planner_chain(monkeypatch):
    from myink import book_setup, providers
    from myink.prompt_catalog import prompt_catalog
    captured = {}

    def generate(messages, **kwargs):
        captured['system'] = messages[0]['content']
        return SimpleNamespace(content='{"verdict":"pass","reason":""}', error=None)

    def chain(role, **kwargs):
        captured['role'] = role
        return SimpleNamespace(generate=generate)

    monkeypatch.setattr(providers, 'make_chain', chain)
    assert book_setup.review_short_plan({}, chapter_count=1) == ('pass', '')
    role = next(group for group in prompt_catalog()
                if any(item['id'] == 'system_short_plan_review' for item in group['templates']))
    template = next(item for item in role['templates'] if item['id'] == 'system_short_plan_review')
    assert role['role'] == captured['role']
    assert template['content'] == captured['system']
