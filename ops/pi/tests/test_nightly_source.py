"""Fresh source leases require an approved comparison or verified human baseline."""
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


@pytest.mark.parametrize("fault", [None,"receipt","template","observer","cohort","window"])
def test_human_main_baseline_can_issue_fresh_inputs_days_after_interrupted_comparison(source_case,fault):
    from copy import deepcopy
    from ops.pi.nightly_source import prepare
    from ops.pi.product_commands import _write
    prior,old,out,template,observer,read,context=source_case;g=prior[0];now=prior[5]
    manifest=json.loads((prior[2]/'bundle/manifest.json').read_bytes());g.ready(old,manifest)
    permission=out/'approval.json'
    _write(permission,dict(schema='pi-nightly-human-approval-v1',mode='SIMULATED',issuer='human_operator',cycle_id=old,package_sha256=digest(manifest),approved_actions=['deploy'],issued_at=now[0].isoformat(),expires_at=(now[0]+timedelta(hours=1)).isoformat()))
    g.approve(old,permission,file_hash(permission));deployment=out/'deployment.json'
    _write(deployment,dict(schema='pi-nightly-deployment-receipt-v1',mode='SIMULATED',issuer='trusted_deployment_verifier',cycle_id=old,package_sha256=digest(manifest),approval_sha256=file_hash(permission),image_id=manifest['image_id'],source_sha256=manifest['source_sha256'],comparison_sha256=manifest['comparison_sha256'],deployment_id='old-human-test',deployed_at=now[0].isoformat()))
    g.deployed(old,deployment,file_hash(deployment))
    identity=deepcopy(context[0]['identity']);identity.update(deployment_id='human-main-v2',generation=identity['generation']+1,commit_sha='8'*40,image_ids=dict(python='sha256:'+'9'*64))
    for row in context:row.update(identity=identity,image_id=identity['image_ids']['python'])
    oc=json.loads(Path(observer['path']).read_bytes());oc['identity']=identity;Path(observer['path']).write_text(json.dumps(oc));observer['sha256']=file_hash(observer['path'])
    op=str(uuid.uuid4());hp=out/'manual.json'
    h=dict(schema='pi-nightly-manual-handoff-v1',mode='SIMULATED',issuer='human_operator',action='interrupt_for_manual_main_release',operation_id=op,cycle_id=old,package_sha256=digest(manifest),deployment_sha256=file_hash(deployment),new_identity=identity,new_package_sha256='a'*64,driver_sha256='b'*64,profile_sha256='c'*64,issued_at=now[0].isoformat(),expires_at=(now[0]+timedelta(hours=1)).isoformat());_write(hp,h)
    directory=out/('manual-handoff-'+op);directory.mkdir(mode=0o700)
    result=dict(schema='pi-nightly-manual-handoff-result-v1',mode='SIMULATED',cycle_id=old,operation_id=op,permission_sha256=file_hash(hp),driver_sha256=h['driver_sha256'],source_template_sha256=file_hash(template),comparison_status='interrupted',online_improvement_proven=False,proof=dict(identity=identity,package_sha256=h['new_package_sha256'],source_sha256='d'*64,profile_sha256=h['profile_sha256'],cohort_sha256=digest(context),audit_path=str(out/'audit.sqlite'),export_root=str(out/'export'),observer=observer,deployed_at=now[0].isoformat(),metrics_source_sha256=digest(oc['source'])),accounting_sha256=digest((ledger_snapshot(g.state),ledger_snapshot(g.billing))),model_requests=0,known_cost_microyuan=0)
    _write(directory/'verified.json',result);g.interrupt_observation(old,hp,file_hash(hp),digest(result))
    now[0]+=timedelta(days=3)
    new=str(uuid.uuid4());assert g.begin(new,'2026-11-05')['claimed'];fresh=out.parent/new;fresh.mkdir(mode=0o700)
    before=ledger_snapshot(g.state),ledger_snapshot(g.billing)
    source={'src/a.py':(prior[2]/'bundle/candidate/src/a.py').read_text()}
    if fault=='receipt':
        result['online_improvement_proven']=True;(directory/'verified.json').write_text(json.dumps(result))
    elif fault=='template':
        changed=json.loads(template.read_bytes());changed['validity_seconds']=3600;template.write_text(json.dumps(changed))
    elif fault=='observer':
        changed=json.loads(Path(observer['path']).read_bytes());changed['identity']['deployment_id']='different';Path(observer['path']).write_text(json.dumps(changed))
    elif fault=='cohort':context[0]=dict(context[0],identity=dict(identity,deployment_id='different'))
    elif fault=='window':context[0]=dict(context[0],started_at=now[0].isoformat())
    def perform():return prepare(g,new,fresh,template,file_hash(template),collect=read,inspect_cohort=lambda *a:context,read_source=lambda *a:source)
    if fault is not None:
        with pytest.raises(ValueError):perform()
        assert (ledger_snapshot(g.state),ledger_snapshot(g.billing))==before
        return
    r=perform()
    assert r['comparison_sha256'] is None and r['baseline_receipt_sha256']==digest(result) and r['predecessor_kind']=='manual_main_release'
    generated=json.loads(Path(r['profile']['path']).read_bytes());assert generated['source']['reference_commit']==identity['commit_sha'] and generated['checker_image_id']==identity['image_ids']['python']
    assert generated['issued_at']==now[0].isoformat() and (ledger_snapshot(g.state),ledger_snapshot(g.billing))==before
