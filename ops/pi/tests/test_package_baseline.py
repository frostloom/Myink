"""A fresh isolated failed baseline is evidence, not execution permission."""
import importlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from threading import Event

import pytest

from ops.pi.development_inputs import file_hash, read_json, tree_hash
from ops.pi.task_package import freeze


def api(): return importlib.import_module('ops.pi.package_baseline')


@pytest.fixture
def package(tmp_path):
    p=tmp_path.resolve();p.chmod(0o700);source=p/'input';(source/'src').mkdir(parents=True)
    (source/'src/a.py').write_text('value = 1\n')
    gold=p/'gold.py';gold.write_text('import unittest\nfrom a import value\nclass Case(unittest.TestCase):\n def test_bad(self): self.assertEqual(value,2)\n def test_good(self): self.assertEqual(value,1)\n');gold.chmod(0o600)
    q=p/'package.json';q.write_text(json.dumps(dict(schema='pi-task-package-v1',task_id='value-fix',problem='Existing value expected2 is1',source_path=str(source),source_sha256=tree_hash(source),test_path=str(gold),test_sha256=file_hash(gold),files=['src/a.py'],root=str(p/'draft'))));q.chmod(0o600);freeze(q)
    draft=p/'draft/task-draft.json';request=p/'baseline.json'
    c=dict(schema='pi-package-baseline-request-v1',baseline_id='baseline-1',draft_path=str(draft),draft_sha256=file_hash(draft),root=str(p/'baseline'),docker=str(Path(sys.executable).resolve()),endpoint='unix:///tmp/synthetic-docker.sock',daemon_id='synthetic-daemon',checker_image_id='sha256:'+'a'*64,deadline_seconds=60)
    request.write_text(json.dumps(c));request.chmod(0o600)
    return request,c,read_json(draft)


def update(package,**kw):
    request,c,_=package;c.update(kw);request.write_text(json.dumps(c));request.chmod(0o600)


def fake_check(module,monkeypatch,kind='failed',change=None):
    def run(c,candidate,dest,limits,write,owners):
        dest.mkdir();shutil.copytree(candidate/'src',dest/'src');shutil.copyfile(c['test_path'],dest/'test.py')
        cases=c['test_cases'];code=0 if kind=='green' else 1
        failed=[cases[0]] if kind=='failed' else []
        errors=[cases[0]] if kind=='error' else []
        result=dict(tests=len(cases),cases=cases,failures=len(failed),errors=len(errors),skipped=0,passed=kind=='green',failed_cases=failed,error_cases=errors,diagnostics=[dict(case=cases[0],category='RuntimeError',attribute=None)] if errors else [],load_error=False,attach_returncode=code,container_id='synthetic-cid')
        owners.history.append(dict(container_id='synthetic-cid',removed=True,exit_code=code))
        if change:change(c,candidate,dest,limits,owners,result)
        return result
    monkeypatch.setattr(module,'_fixed_check',run)


def test_default_preflight_never_writes_launches_or_connects(package,monkeypatch):
    request,c,_=package;before=sorted(str(p) for p in request.parent.rglob('*'))
    def no(*args,**kwargs):raise AssertionError('read-only preflight must not contact Docker or a provider')
    with monkeypatch.context() as m:
        m.setattr(subprocess,'Popen',no);m.setattr(socket,'socket',no)
        result=api().check(request)
    assert result['ready'] and result['mode']=='read-only-baseline'
    assert not Path(c['root']).exists() and before==sorted(str(p) for p in request.parent.rglob('*'))


def test_real_failed_inventory_is_only_catalog_eligibility_not_approval(package,monkeypatch):
    module=api();fake_check(module,monkeypatch)
    result=module.execute(package[0]);out=read_json(result['result_path'])
    assert result['verified'] and result['eligible_for_selection'] and not out['check_passed']
    task=out['catalog'][0]
    from ops.pi.maintenance_handoff import _catalog
    assert _catalog(out['catalog'])==out['catalog']
    assert task['baseline']['failures']==1 and task['baseline']['failed_cases']==[package[2]['test_case_hints'][0]]
    assert task['source_sha256']==package[2]['source_sha256']
    assert out['requires']==['fresh_run_identity','independent_reviews','current_runtime']
    assert not {'approved','review_path','ledger_path','runtime_path','plan_path'} & out.keys()
    from ops.pi.development_inputs import prepare_template
    with pytest.raises(ValueError,match='unsupported development config'):prepare_template(result['result_path'])


@pytest.mark.parametrize('kind', ['green','error'])
def test_green_or_error_baseline_cannot_enter_catalog(package,monkeypatch,kind):
    module=api();fake_check(module,monkeypatch,kind)
    result=module.execute(package[0]);out=read_json(result['result_path'])
    assert not result['eligible_for_selection'] and out['catalog']==[]
    assert result['verified'] is (kind=='green')
    assert out['check_passed'] is (kind=='green')


@pytest.mark.parametrize('bad',['skipped','inventory','cleanup','cleanup_transient','copy','gold_copy','source','gold','draft','cancel','deadline'])
def test_invalid_or_changed_check_never_emits_eligible_catalog(package,monkeypatch,bad):
    module=api();cancel=Event()
    def change(c,source,dest,limits,owners,result):
        if bad=='skipped':result.update(skipped=1,passed=False,failures=0,failed_cases=[])
        elif bad=='inventory':result['cases']=[]
        elif bad=='cleanup':owners.history.clear()
        elif bad=='cleanup_transient':owners.failed=True
        elif bad=='copy':(dest/'src/a.py').write_text('wrong = True\n')
        elif bad=='gold_copy':(dest/'test.py').write_text('wrong = True\n')
        elif bad=='source':(source/'src/a.py').write_text('changed = True\n')
        elif bad=='gold':Path(c['test_path']).write_text('changed = True\n')
        elif bad=='draft':Path(package[1]['draft_path']).write_text('{}')
        elif bad=='cancel':cancel.set()
        else:limits.deadline=0
    fake_check(module,monkeypatch,change=change)
    result=module.execute(package[0],cancel=cancel);out=read_json(result['result_path'])
    assert result['verified'] is False and not result['eligible_for_selection'] and out['catalog']==[]


def test_preset_cancel_does_not_create_output_or_run_checker(package,monkeypatch):
    module=api();cancel=Event();cancel.set()
    def no(*args):raise AssertionError('cancelled work must not run')
    monkeypatch.setattr(module,'_fixed_check',no)
    with pytest.raises(ValueError):module.execute(package[0],cancel=cancel)
    assert not Path(package[1]['root']).exists()


def test_cleanup_finish_failure_is_not_hidden_by_valid_report(package,monkeypatch):
    module=api();fake_check(module,monkeypatch);original=module.OwnedHosts
    class Failed(original):
        def finish(self):raise RuntimeError('synthetic cleanup failure')
    monkeypatch.setattr(module,'OwnedHosts',Failed)
    result=module.execute(package[0]);out=read_json(result['result_path'])
    assert not result['verified'] and out['catalog']==[] and out['cleanup_failure_class']=='RuntimeError'


@pytest.mark.parametrize('field,value',[
    ('schema','pi-development-v1'),('deadline_seconds',True),('deadline_seconds',301),
    ('baseline_id','../escape'),('endpoint','tcp://example.com:123'),
    ('checker_image_id','latest'),('draft_sha256','0'*64),('root','relative'),
    ('ledger_path','not-allowed'),
])
def test_bad_requests_fail_before_any_output(package,monkeypatch,field,value):
    module=api();update(package,**{field:value})
    def no(*args):raise AssertionError('invalid package must not run')
    monkeypatch.setattr(module,'_fixed_check',no)
    with pytest.raises(ValueError):module.check(package[0])
    assert not Path(package[1]['root']).exists()


@pytest.mark.parametrize('change',['case_hints','source_path','requires','inventory','authority','files'])
def test_draft_cannot_be_promoted_by_tampering_metadata(package,change):
    request,c,d=package
    if change=='case_hints':d['test_case_hints']=d['test_case_hints'][:1]
    elif change=='source_path':d['source_path']=str(Path(c['draft_path']).parent.parent/'input')
    elif change=='requires':d['requires']=[]
    elif change=='inventory':d['inventory_status']='verified'
    elif change=='authority':d['approved']=True
    else:d['files']=['../outside']
    Path(c['draft_path']).write_text(json.dumps(d));update(package,draft_sha256=file_hash(c['draft_path']))
    with pytest.raises(ValueError):api().check(request)
    assert not Path(c['root']).exists()


def test_completed_baseline_is_not_replayed_or_overwritten(package,monkeypatch):
    module=api();fake_check(module,monkeypatch);result=module.execute(package[0]);p=Path(result['result_path']);before=p.read_bytes()
    def no(*args):raise AssertionError('must not retry an existing root')
    monkeypatch.setattr(module,'_fixed_check',no)
    with pytest.raises(ValueError):module.execute(package[0])
    assert p.read_bytes()==before


def test_cli_exit_zero_means_baseline_verified_not_all_tests_passed(package,monkeypatch,capsys):
    module=api();fake_check(module,monkeypatch)
    assert module.main(['--request',str(package[0])])==0
    assert json.loads(capsys.readouterr().out)['mode']=='read-only-baseline'
    assert module.main(['--request',str(package[0]),'--execute'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['verified'] and result['eligible_for_selection']
    assert read_json(result['result_path'])['check_passed'] is False


@pytest.mark.parametrize('changed',['source','gold','draft','request','copy'])
def test_inputs_and_actual_copy_are_rechecked_after_cleanup(package,monkeypatch,changed):
    module=api();fake_check(module,monkeypatch);original=module.OwnedHosts
    class LateChange(original):
        def finish(self):
            rows=super().finish()
            if changed=='source':(Path(package[2]['source_path'])/'src/a.py').write_text('late = True\n')
            elif changed=='gold':Path(package[2]['test_path']).write_text('late = True\n')
            elif changed=='draft':Path(package[1]['draft_path']).write_text('{}')
            elif changed=='request':package[0].write_text(package[0].read_text()+' ')
            else:(Path(package[1]['root'])/'check/src/a.py').write_text('late = True\n')
            return rows
    monkeypatch.setattr(module,'OwnedHosts',LateChange)
    result=module.execute(package[0]);out=read_json(result['result_path'])
    assert result['verified'] is False and out['catalog']==[]


def test_oversized_catalog_still_preserves_authenticated_baseline(package,monkeypatch):
    request,c,d=package;gold=Path(d['test_path'])
    gold.write_text('import unittest\nclass Case(unittest.TestCase):\n'+''.join(f' def test_{i:04d}(self): self.assertTrue(True)\n' for i in range(900)))
    from ops.pi.task_package import _case_hints
    d.update(test_sha256=file_hash(gold),test_case_hints=_case_hints(gold.read_bytes()))
    Path(c['draft_path']).write_text(json.dumps(d));update(package,draft_sha256=file_hash(c['draft_path']))
    module=api();fake_check(module,monkeypatch)
    assert module.check(request)['ready']
    result=module.execute(request);out=read_json(result['result_path'])
    assert result['verified'] and not result['eligible_for_selection'] and out['catalog']==[]
    assert out['checker_report']['tests']==900 and out['checker_report']['failures']==1
    assert out['catalog_rejection']=='task catalog too large'


@pytest.mark.parametrize('overlap',['same','parent','alias','loop'])
def test_output_must_not_occupy_or_contain_daemon_socket_path(package,overlap):
    request,c,_=package;p=request.parent
    if overlap=='same':
        target=p/'daemon.sock';update(package,root=str(target),endpoint='unix://'+str(target))
    elif overlap=='parent':
        target=p/'daemon-root';update(package,root=str(target),endpoint='unix://'+str(target/'daemon.sock'))
    elif overlap=='alias':
        real=p/'real';real.mkdir(mode=0o700);alias=p/'alias';alias.symlink_to(real,target_is_directory=True)
        target=real/'daemon.sock';update(package,root=str(target),endpoint='unix://'+str(alias/'daemon.sock'))
    else:
        target=Path(c['root']);alias=p/'loop';alias.symlink_to(alias)
        update(package,endpoint='unix://'+str(alias))
    with pytest.raises(ValueError):api().check(request)
    assert not target.exists()
