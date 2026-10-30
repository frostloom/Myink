"""A fresh finite source lease requires a completed human-deployed comparison."""
from pathlib import Path
from datetime import timedelta
import json,sys,uuid
import pytest
from ops.pi.tests.test_nightly_binding import binding_case,deployed_case,bundle_case,finished,stopped,completed,config_file,Image,confirm,bind
from ops.pi.audit import digest
from ops.pi.development_inputs import file_hash,ledger_snapshot,tree_hash


@pytest.fixture
def source_case(binding_case):
    deployed,observer_template=binding_case;case,calls=deployed;g,previous,root,task,finished,now=case;confirm(deployed);observer=bind(binding_case)
    now[0]+=timedelta(hours=26)
    def read(path,pin):return dict(schema='pi-live-observer-result-v1',mode='SIMULATED',status='passed',config_sha256=digest(json.loads(Path(path).read_bytes())),observed_samples=20,confounders=[],window=dict(start=(now[0]-timedelta(hours=1)).isoformat(),end=(now[0]-timedelta(minutes=1)).isoformat()),run_id='fresh-window')
    def check(e,*a):return dict(passed=True,tests=len(e['test_cases']),failures=0,errors=0,skipped=0,cleanup=[dict(removed=True)])
    from ops.pi.nightly_observation import assess
    assert assess(g,previous,root/'bundle',observer['path'],observer['sha256'],observe=read,check=check)['status']=='completed'
    cycle=str(uuid.uuid4());assert g.begin(cycle,'2026-11-02')['claimed'];out=root.parent/cycle;out.mkdir(mode=0o700)
    c=finished[5];roots={}
    for key in ('root','permit_root','handoff_root','review_root','investigation_root','reproduction_root'):
        p=root.parent/('source-'+key);p.mkdir(mode=0o700);roots[key]=str(p)
    inbox=root.parent/'inbox';inbox.mkdir(mode=0o700);lock=root.parent/'maintenance.lock';lock.touch(mode=0o600)
    fee=ledger_snapshot(g.billing)
    profile=dict(schema='pi-autonomy-profile-v1',authority='bounded_source_investigation_and_review',mode='SIMULATED',**roots,host={k:c[k] for k in ('runtime_path','runtime_sha256','ledger_path','policy_path','policy_sha256','credential_path','credential_sha256','docker','endpoint','daemon_id','image_id')},audit_path=json.loads(observer_template.read_bytes())['audit_path'],export_root=str(root/'export'),manager_state=str(g.state),inbox=str(inbox),lock_path=str(lock),budget_microyuan=fee['limits']['budget_microyuan'],legacy_unknown_ids=[],limits=dict(investigation_seconds=60,review_seconds=60,checker_seconds=60,max_requests=30,max_tools=64,development_seconds=900,cycle_seconds=1800,review_wait_seconds=60,priority=1),worker_entry_path=str(Path(sys.executable).resolve()),controller_sha256='a'*64)
    template=root.parent/'source-template.json';template.write_text(json.dumps(dict(schema='pi-nightly-source-template-v1',mode='SIMULATED',profile=profile,source_scope=dict(files=['src/a.py'],behavior='value'),validity_seconds=7200)));template.chmod(0o600)
    context=json.loads((root/'deployment-context.json').read_bytes())['containers']
    return case,cycle,out,template,observer,read,context


def issue(case,**kwargs):
    from ops.pi.nightly_source import prepare
    prior,cycle,out,template,observer,read,context=case;g=prior[0]
    def source(packet,rows,files,path):
        available={'src/a.py':(prior[2]/'bundle/candidate/src/a.py').read_text(),'src/other.py':'value = 3\n'}
        if not set(files)<=set(available):raise ValueError('file not in installed package')
        return {f:available[f] for f in files}
    return prepare(g,cycle,out,template,file_hash(template),collect=kwargs.get('collect',read),inspect_cohort=kwargs.get('inspect_cohort',lambda *a:context),read_source=kwargs.get('read_source',source))


def test_next_lease_is_fresh_source_bound_and_does_not_reset_original_ledgers(source_case):
    prior,cycle,out,template,observer,read,context=source_case;g=prior[0];before=ledger_snapshot(g.state),ledger_snapshot(g.billing)
    r=issue(source_case);p=json.loads(Path(r['profile']['path']).read_bytes())
    assert p['source']['source_sha256']==tree_hash(prior[2]/'bundle/candidate') and p['source']['source_path']!=str(prior[2]/'bundle/candidate')
    assert p['observer']['observer_config_path']==observer['path'] and p['checker_image_id']==r['base_image_id']=='sha256:'+'7'*64
    assert p['host']['image_id']==prior[4][5]['image_id'] and p['host']['ledger_path']==str(g.billing)
    assert p['issued_at']==prior[5][0].isoformat() and p['expires_at']==(prior[5][0]+timedelta(hours=2)).isoformat()
    assert json.loads(Path(p['source']['pending_path']).read_bytes())==[]
    assert (ledger_snapshot(g.state),ledger_snapshot(g.billing))==before
    assert r==issue(source_case,collect=lambda *a:pytest.fail('completed source stage must not recollect'))


@pytest.mark.parametrize('fault',['cohort','template_budget','template_scope','stale_metrics'])
def test_unverified_context_cannot_issue_next_source_lease(source_case,fault):
    prior,cycle,out,template,observer,read,context=source_case
    if fault.startswith('template'):
        value=json.loads(template.read_bytes())
        if fault=='template_budget':value['profile']['budget_microyuan']+=1
        else:value['source_scope']['files']=['src/foreign.py']
        template.write_text(json.dumps(value))
    def wrong(*a):
        result=read(*a)
        if fault=='stale_metrics':result['window']['start']=(prior[5][0]-timedelta(days=3)).isoformat()
        return result
    with pytest.raises(ValueError):issue(source_case,collect=wrong,inspect_cohort=lambda *a:[] if fault=='cohort' else context)
    assert not (out/'source-stage.json').exists()


def test_incomplete_source_intent_is_not_replayed(source_case):
    out=source_case[2];p=out/'source-intent.json';p.write_text('{}');p.chmod(0o600)
    with pytest.raises(ValueError):issue(source_case,collect=lambda *a:pytest.fail('interrupted intent must not recollect'))


def test_operator_scope_can_select_a_deployed_file_outside_previous_candidate(source_case):
    prior,cycle,out,template,*_=source_case;value=json.loads(template.read_bytes());value['source_scope']['files']=['src/other.py'];template.write_text(json.dumps(value))
    result=issue(source_case);p=json.loads(Path(result['profile']['path']).read_bytes());source=Path(p['source']['source_path'])
    assert (source/'src/other.py').read_text()=='value = 3\n' and not (source/'src/a.py').exists()
    assert p['source']['source_sha256']!=tree_hash(prior[2]/'bundle/candidate')


@pytest.mark.parametrize('files',[['../escape.py'],['src/a.py']*2,['src/a.py','src/b.py','src/c.py','src/d.py']])
def test_invalid_operator_scope_is_rejected_before_metrics_or_source_read(source_case,files):
    value=json.loads(source_case[3].read_bytes());value['source_scope']['files']=files;source_case[3].write_text(json.dumps(value))
    with pytest.raises(ValueError):issue(source_case,collect=lambda *a:pytest.fail('invalid scope queried metrics'),read_source=lambda *a:pytest.fail('invalid scope read source'))


def test_copy_changed_during_ownership_handoff_cannot_be_signed_as_deployed_source(source_case,monkeypatch):
    from ops.pi import nightly_source
    def corrupt(path,mode):
        if path.name=='a.py':path.write_text('unapproved = True\n')
    monkeypatch.setattr(nightly_source,'_ordinary',corrupt)
    with pytest.raises(ValueError):issue(source_case)
    assert not (source_case[2]/'source-stage.json').exists()
