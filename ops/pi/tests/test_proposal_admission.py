"""Only a fresh native independently reviewed cycle may enter the inbox."""
import json
from pathlib import Path
import pytest
from ops.pi import proposal_admission as admission,proposals,package_baseline
from ops.pi.development_inputs import file_hash,read_json
from ops.pi.tests.test_proposals import batch
from ops.pi.tests.test_package_baseline import fake_check

@pytest.fixture
def ready(batch,monkeypatch):
    p,c,write=batch;fake_check(package_baseline,monkeypatch)
    report=proposals.execute(p);r=read_json(report['report_path']);proposal=r['proposals'][0]
    cycle=write('cycle-request.json',dict(schema='synthetic-cycle'))
    inbox=p.parent/'inbox';inbox.mkdir(mode=0o700)
    config=dict(schema='pi-proposal-admission-v1',proposal_path=report['report_path'],proposal_sha256=report['report_sha256'],
        proposal_id=proposal['proposal_id'],cycle_path=str(cycle),cycle_sha256=file_hash(cycle),task_id='admitted-task',inbox=str(inbox))
    request=write('admission.json',config)
    selection=dict(root=str(p.parent/'selection'),ledger_path=str(p.parent/'billing.sqlite'))
    native=dict(root=str(p.parent/'cycle-output'),selection_config_path=str(p.parent/'selection.json'),templates_path=str(p.parent/'templates.json'),cycle_id='new-cycle',control_ledger_path=str(p.parent/'control.sqlite'))
    monkeypatch.setattr(admission,'inspect_cycle',lambda _: (native,selection,proposal['catalog'],{}))
    monkeypatch.setattr(admission,'cycle_resources',lambda *a:dict(inputs=[str(cycle)],outputs=[native['root']],identities=['new-cycle']))
    return request,config,write,proposal


def test_check_readonly_and_publish_exact_manifest(ready):
    p,c,write,proposal=ready
    assert admission.check(p)['ready'] and list(Path(c['inbox']).iterdir())==[]
    result=admission.publish(p);target=Path(result['manifest_path'])
    assert result['published'] and not result['already_published'] and target.stat().st_nlink==1
    assert read_json(target)==dict(schema='pi-manager-admission-v1',task_id=c['task_id'],request_path=c['cycle_path'],request_sha256=c['cycle_sha256'],priority=proposal['priority'],mode='ACTUAL')


def test_idempotence_does_not_revalidate_consumed_cycle(ready,monkeypatch):
    p,c,_,_=ready;first=admission.publish(p)
    monkeypatch.setattr(admission,'inspect_cycle',lambda _:pytest.fail('consumed cycle preflight replayed'))
    assert admission.publish(p)['already_published']
    assert Path(first['manifest_path']).stat().st_nlink==1


@pytest.mark.parametrize('bad',['catalog','unreviewed','source','inbox_overlap','hardlink','forged_eligible','recipe','cycle_hash','unknown_field'])
def test_reject_drift_without_inbox_manifest(ready,monkeypatch,bad):
    p,c,write,proposal=ready
    if bad=='catalog':monkeypatch.setattr(admission,'inspect_cycle',lambda _: ({},{},[],{}))
    if bad=='unreviewed':monkeypatch.setattr(admission,'inspect_cycle',lambda _: (_ for _ in ()).throw(ValueError('independent review missing')))
    if bad=='source':(p.parent/'source/src/a.py').write_text('value=99\n')
    if bad=='inbox_overlap':c['inbox']=str(p.parent/'draft')
    if bad=='hardlink':Path(c['proposal_path']).with_suffix('.alias').hardlink_to(c['proposal_path'])
    if bad=='forged_eligible':
        r=read_json(c['proposal_path']);r['assessments']=[];write('proposed/proposals.json',r);c['proposal_sha256']=file_hash(c['proposal_path'])
    if bad=='recipe':write('package.json',{})
    if bad=='cycle_hash':c['cycle_sha256']='0'*64
    if bad=='unknown_field':c['approved']=True
    write(p.name,c)
    with pytest.raises((ValueError,KeyError)):admission.publish(p)
    assert list((p.parent/'inbox').glob('*.task.json'))==[]


def test_publish_conflict_retains_original(ready):
    p,c,_,_=ready;target=Path(c['inbox'])/(c['task_id']+'.task.json');target.write_text('{}');target.chmod(0o600)
    with pytest.raises(ValueError):admission.publish(p)
    assert target.read_text()=='{}'


def test_distinct_recipes_for_same_task_share_maximum_priority(batch,monkeypatch):
    p,c,write=batch;original=read_json(c['rules'][0]['package_request_path'])
    other=write('other-package.json',dict(original,task_id='same-content-alias',root=str(p.parent/'other-draft')))
    c['rules'].append(dict(c['rules'][0],rule_id='other',package_request_path=str(other),package_request_sha256=file_hash(other),priority=8));write(p.name,c)
    fake_check(package_baseline,monkeypatch);r=proposals.execute(p);report=read_json(r['report_path']);proposal=report['proposals'][0]
    verified,_=admission.eligible(r['report_path'],r['report_sha256'],proposal['proposal_id'])
    assert verified['priority']==8 and len(report['proposals'])==1


def test_rejected_inbox_inside_source_never_writes_lock(ready):
    p,c,write,_=ready;source=p.parent/'source';source.chmod(0o700);c['inbox']=str(source);write(p.name,c)
    before={str(f):f.read_bytes() for f in source.rglob('*') if f.is_file()}
    with pytest.raises(ValueError):admission.publish(p)
    assert before=={str(f):f.read_bytes() for f in source.rglob('*') if f.is_file()}
