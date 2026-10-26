"""Repository entry wiring; synthetic artifacts, never provider calls."""
import json
from pathlib import Path
import pytest
from ops.pi.tests.test_maintenance_adapters import pack
from ops.pi.tests.test_development_inputs import config_file
from ops.pi.development_inputs import file_hash, read_json
from ops.pi.contracts import Receipt
from ops.pi import local_cycle as cycle


@pytest.fixture
def entry(pack,tmp_path,monkeypatch):
    adapter,ctx,c,template,_=pack
    ctx['tasks']=[ctx['task']]
    selection=tmp_path/'selection.json'
    sc=dict(c,catalog_path=str(tmp_path/'catalog.json'),catalog_sha256='a'*64,root=str(tmp_path/'selection-output'))
    selection.write_text(json.dumps(sc));selection.chmod(0o600)
    templates=tmp_path/'templates.json';templates.write_text(json.dumps(adapter.templates));templates.chmod(0o600)
    request=tmp_path/'cycle.json'
    value=dict(schema='pi-local-cycle-v1',cycle_id='cycle-1',root=str(tmp_path/'cycle-output'),
        control_ledger_path=str(tmp_path/'control.sqlite'),selection_config_path=str(selection),
        selection_config_sha256=file_hash(selection),templates_path=str(templates),
        templates_sha256=file_hash(templates),deadline_seconds=1800,review_wait_seconds=60)
    request.write_text(json.dumps(value));request.chmod(0o600)
    monkeypatch.setattr(cycle,'prepare_selection',lambda p:(read_json(p),None,ctx['tasks'],None,None))
    return request,value,sc,adapter,ctx


def rewrite(p,c):p.write_text(json.dumps(c));p.chmod(0o600)


def test_readonly_checks_all_packages_without_creating_outputs(entry):
    p,c,*_=entry
    before={str(f):f.read_bytes() for f in p.parent.rglob('*') if f.is_file()}
    assert cycle.check(p)['ready'] is True
    assert before=={str(f):f.read_bytes() for f in p.parent.rglob('*') if f.is_file()}
    assert not Path(c['root']).exists() and not Path(c['control_ledger_path']).exists()


@pytest.mark.parametrize('change',['unknown','boolean_deadline','large_deadline','bad_id','bad_wait','selection_drift','template_drift','missing_template','extra_template','billing_alias','root_reuse','stage_overlap','input_overlap'])
def test_invalid_entry_fails_before_coordinator(entry,monkeypatch,change):
    p,c,sc,adapter,_=entry
    if change=='unknown':c['unknown']=True
    if change=='boolean_deadline':c['deadline_seconds']=True
    if change=='large_deadline':c['deadline_seconds']=3601
    if change=='bad_id':c['cycle_id']='../bad'
    if change=='bad_wait':c['review_wait_seconds']=601
    if change=='selection_drift':c['selection_config_sha256']='0'*64
    if change=='template_drift':c['templates_sha256']='0'*64
    if change in ('missing_template','extra_template'):
        templates=read_json(c['templates_path'])
        if change=='missing_template':templates={}
        else:templates['extra']=next(iter(templates.values()))
        rewrite(Path(c['templates_path']),templates);c['templates_sha256']=file_hash(c['templates_path'])
    if change=='billing_alias':c['control_ledger_path']=sc['ledger_path']
    if change=='root_reuse':Path(c['root']).mkdir(mode=0o700)
    if change=='stage_overlap':c['root']=sc['root']
    if change=='input_overlap':c['root']=str(Path(sc['source_path'])/'nested')
    rewrite(p,c)
    monkeypatch.setattr(cycle,'run_local_development',lambda *a,**k:pytest.fail('coordinator reached'))
    with pytest.raises((ValueError,OSError)):cycle.execute(p)
    assert not Path(c['control_ledger_path']).exists() or change=='billing_alias'


def test_execute_uses_actual_adapters_and_original_receipt(entry,monkeypatch):
    p,c,sc,adapter,ctx=entry;calls=[]
    def run(control,identity,tasks,**kwargs):
        calls.append((control,identity,tasks,kwargs))
        assert kwargs['mode']=='ACTUAL'
        assert type(kwargs['analyze']) is cycle.SelectionAdapter
        assert type(kwargs['prepare_development'].reviewer) is cycle.FileReview
        assert kwargs['source_identity']()==sc['source_sha256']
        return Receipt('maintenance:cycle-1','done',dict(verified=True,next_action='observe',released=False))
    monkeypatch.setattr(cycle,'run_local_development',run)
    out=cycle.execute(p)
    assert out['status']=='done' and out['evidence']['next_action']=='observe'
    assert read_json(Path(c['root'])/'result.json')==out and len(calls)==1
    with pytest.raises(ValueError):cycle.execute(p)
    assert len(calls)==1


def test_package_rejection_precedes_selection(entry,monkeypatch):
    p,c,sc,adapter,_=entry
    templates=read_json(c['templates_path']);templates['names']['sha256']='0'*64
    rewrite(Path(c['templates_path']),templates);c['templates_sha256']=file_hash(c['templates_path']);rewrite(p,c)
    monkeypatch.setattr(cycle,'run_local_development',lambda *a,**k:pytest.fail('paid stage reached'))
    with pytest.raises(ValueError,match='template|package'):cycle.execute(p)


def test_uncertain_receipt_is_preserved_without_retry(entry,monkeypatch):
    p,c,*_=entry;calls=[]
    def run(*a,**k):
        calls.append(1);return Receipt('maintenance:cycle-1','uncertain',dict(next_action='reconcile',released=False))
    monkeypatch.setattr(cycle,'run_local_development',run)
    result=cycle.execute(p)
    assert result['status']=='uncertain' and len(calls)==1
    assert read_json(Path(c['root'])/'result.json')==result


def test_control_ledger_created_private_even_with_public_process_umask(entry,monkeypatch):
    import os
    p,c,*_=entry
    def run(*args,**kwargs):
        assert Path(c['control_ledger_path']).stat().st_mode&0o777==0o600
        return Receipt('maintenance:cycle-1','done',dict(verified=True,next_action='observe'))
    monkeypatch.setattr(cycle,'run_local_development',run)
    old=os.umask(0o022)
    try:cycle.execute(p)
    finally:os.umask(old)


@pytest.mark.parametrize('status',['done','uncertain','blocked'])
def test_real_coordinator_observe_and_failure_are_persisted(entry,monkeypatch,status):
    p,c,*_=entry;calls=[]
    def analyze(self,context):
        calls.append(context['operation_id'])
        return Receipt(context['operation_id'],status,dict(mode='ACTUAL',verified=status=='done',
            binding=context['input_hash'],proposal=dict(task_id=None,source_sha256=None,evidence_sha256=None,reason='no work')))
    monkeypatch.setattr(cycle.SelectionAdapter,'__call__',analyze)
    result=cycle.execute(p)
    assert result['status']==status and len(calls)==1
    assert result['evidence']['next_action']==('observe' if status=='done' else 'reconcile' if status=='uncertain' else 'stop')
    assert read_json(Path(c['root'])/'result.json')==result


@pytest.mark.parametrize('suffix',['-wal','-shm','-journal'])
def test_control_cannot_occupy_billing_sqlite_sidecar(entry,suffix):
    p,c,sc,*_=entry;c['control_ledger_path']=sc['ledger_path']+suffix;rewrite(p,c)
    with pytest.raises(ValueError,match='overlap'):cycle.check(p)


def test_case_aliases_cannot_bypass_source_isolation(entry):
    p,c,sc,*_=entry
    source=Path(sc['source_path']);alias=source.with_name(source.name.upper())
    if not alias.exists():pytest.skip('case-sensitive test filesystem')
    source.chmod(0o700)
    c['root']=str(alias/'nested');rewrite(p,c)
    with pytest.raises(ValueError,match='overlap'):cycle.check(p)


def test_phase_root_cannot_occupy_docker_socket(entry):
    p,c,sc,*_=entry;c['root']='/tmp/synthetic-docker.sock';rewrite(p,c)
    with pytest.raises(ValueError):cycle.check(p)
