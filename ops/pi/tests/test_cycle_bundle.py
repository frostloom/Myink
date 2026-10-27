"""Mechanical bundle creation never supplies an independent approval."""
import json
from pathlib import Path
import pytest
from ops.pi.tests.test_maintenance_adapters import pack
from ops.pi.tests.test_development_inputs import config_file
from ops.pi.development_inputs import file_hash,read_json
from ops.pi import cycle_bundle as bundle


@pytest.fixture
def bundle_request(pack,tmp_path):
    adapter,ctx,c,template,_=pack;task=ctx['task']
    outcome=tmp_path/'outcome.json';outcome.write_text(json.dumps(dict(schema='pi-package-baseline-outcome-v1',
        verified=True,eligible_for_selection=True,catalog=[task],source_sha256=task['source_sha256'],test_sha256=task['test_sha256'])));outcome.chmod(0o600)
    p=tmp_path/'bundle-bundle_request.json';value=dict(schema='pi-cycle-bundle-v1',root=str(tmp_path/'bundle'),
        cycle_id='bundle-1',selection_run_id='selection-1',template_path=str(template),template_sha256=file_hash(template),
        outcome_path=str(outcome),outcome_sha256=file_hash(outcome),deadline_seconds=1800,review_wait_seconds=60)
    p.write_text(json.dumps(value));p.chmod(0o600)
    return p,value,c,task


def update(p,c):p.write_text(json.dumps(c));p.chmod(0o600)


def test_check_is_readonly_and_freeze_does_not_approve(bundle_request):
    p,c,template,task=bundle_request;before=set(p.parent.rglob('*'))
    assert bundle.check(p)['ready'] and set(p.parent.rglob('*'))==before
    result=bundle.freeze(p);root=Path(c['root'])
    assert result['requires']==['independent_selection_review','independent_development_review']
    selection=read_json(root/'selection-config.json')
    assert selection['prompt_version']==2
    assert selection['review_sha256']=='0'*64 and not Path(selection['review_path']).exists()
    assert read_json(root/'catalog.json')==[task]
    assert not (root/'cycle.json').exists() and not (root/'control.sqlite').exists()
    with pytest.raises(ValueError):bundle.freeze(p)


@pytest.mark.parametrize('kind',['green','outcome_drift','template_drift','catalog_mismatch','overlap','extra','deadline'])
def test_invalid_bundle_never_publishes(bundle_request,kind):
    p,c,template,task=bundle_request
    if kind=='green':
        o=read_json(c['outcome_path']);o['eligible_for_selection']=False;update(Path(c['outcome_path']),o);c['outcome_sha256']=file_hash(c['outcome_path'])
    if kind=='outcome_drift':c['outcome_sha256']='0'*64
    if kind=='template_drift':c['template_sha256']='0'*64
    if kind=='catalog_mismatch':
        o=read_json(c['outcome_path']);o['catalog'][0]['files']=['src/wrong.py'];update(Path(c['outcome_path']),o);c['outcome_sha256']=file_hash(c['outcome_path'])
    if kind=='overlap':c['root']=str(Path(template['source_path'])/'bundle')
    if kind=='extra':c['approved']=True
    if kind=='deadline':c['deadline_seconds']=True
    update(p,c)
    with pytest.raises((ValueError,OSError)):bundle.freeze(p)
    assert not (Path(c['root'])/'bundle.json').exists()


def test_seal_requires_real_review_and_full_entry_preflight(bundle_request,monkeypatch):
    p,c,_,_=bundle_request;bundle.freeze(p);root=Path(c['root'])
    with pytest.raises((ValueError,OSError)):bundle.seal(root/'bundle.json')
    assert not (root/'cycle.json').exists()


def approve_selection(root):
    from ops.pi.development_inputs import authorization_hash,digest
    s=read_json(root/'selection-config.json');tasks=read_json(s['catalog_path'])
    review=dict(source='independent_review',verified=True,result='approved',reviewer='synthetic-review',
        authorization_sha256=authorization_hash(s),plan_hash=digest(tasks),base=s['source_sha256'],
        candidate_id=s['run_id'],owner='local-development-controller',generation=1)
    update(Path(s['review_path']),review)


def test_seal_publishes_executable_entry_only_after_bound_review(bundle_request,monkeypatch):
    from ops.pi import selection_launcher
    p,c,_,_=bundle_request;bundle.freeze(p);root=Path(c['root']);approve_selection(root)
    monkeypatch.setattr(selection_launcher,'verify_source',lambda *a:{})
    result=bundle.seal(root/'bundle.json')
    assert result['ready'] and Path(result['cycle_path']).name=='cycle.json'
    assert read_json(root/'selection-config.json')['review_sha256']=='0'*64
    assert read_json(root/'selection-reviewed.json')['review_sha256']==file_hash(root/'selection-review.json')
    from ops.pi.local_cycle import check
    assert check(result['cycle_path'])['ready']
    with pytest.raises(ValueError):bundle.seal(root/'bundle.json')


@pytest.mark.parametrize('kind',['review_identity','catalog','template','request','templates'])
def test_seal_rechecks_all_authority_before_publication(bundle_request,monkeypatch,kind):
    from ops.pi import selection_launcher
    p,c,_,_=bundle_request;bundle.freeze(p);root=Path(c['root']);approve_selection(root)
    monkeypatch.setattr(selection_launcher,'verify_source',lambda *a:{})
    if kind=='review_identity':
        review=read_json(root/'selection-review.json');review['authorization_sha256']='0'*64;update(root/'selection-review.json',review)
    if kind=='catalog':update(root/'catalog.json',[])
    if kind=='template':Path(c['template_path']).write_text('{}')
    if kind=='request':update(p,dict(c,cycle_id='changed'))
    if kind=='templates':update(root/'templates.json',{})
    with pytest.raises((ValueError,OSError,KeyError,TypeError)):bundle.seal(root/'bundle.json')
    assert not (root/'cycle.json').exists()


def test_bundle_cannot_occupy_missing_docker_socket(bundle_request):
    p,c,template,_=bundle_request
    socket=Path(template['source_path']).parent/'missing-docker.sock'
    tc=read_json(c['template_path']);tc['endpoint']='unix://'+str(socket)
    update(Path(c['template_path']),tc);c['template_sha256']=file_hash(c['template_path']);c['root']=str(socket);update(p,c)
    with pytest.raises(ValueError,match='overlap'):bundle.check(p)


def test_bundle_case_alias_cannot_enter_source(bundle_request):
    p,c,template,_=bundle_request;source=Path(template['source_path']);alias=source.with_name(source.name.upper())
    if not alias.exists():pytest.skip('case-sensitive test filesystem')
    source.chmod(0o700)
    c['root']=str(alias/'nested');update(p,c)
    with pytest.raises(ValueError,match='overlap'):bundle.check(p)


def test_published_hardlinked_entry_is_not_ready(bundle_request,monkeypatch):
    from ops.pi import selection_launcher
    p,c,_,_=bundle_request;bundle.freeze(p);root=Path(c['root']);approve_selection(root)
    monkeypatch.setattr(selection_launcher,'verify_source',lambda *a:{})
    original=Path.unlink
    def fail_cleanup(target,*a,**kw):
        if target.name=='.cycle.json.pending':raise OSError('synthetic cleanup failure')
        return original(target,*a,**kw)
    monkeypatch.setattr(Path,'unlink',fail_cleanup)
    result=bundle.seal(root/'bundle.json')
    assert result['ready'] is False
    assert result['published'] is True and result['staging_retained'] is True
    assert result['ready'] is False and result['next_action']=='reconcile_publication'
    assert (root/'cycle.json').exists()
