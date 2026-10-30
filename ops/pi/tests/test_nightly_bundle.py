"""A complete original-manager candidate becomes one immutable approval package."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,uuid
import pytest
from ops.pi.tests.test_manager_completion import finished,stopped,completed,config_file
from ops.pi.development_inputs import file_hash,tree_hash,ledger_snapshot
from ops.pi.nightly_gate import ApprovalGate
from ops.pi.audit import digest


class Image:
    calls=[]
    def __init__(self,g,cycle,root,*args):self.g=g;self.cycle=cycle;self.root=root
    def build(self,source,candidate,base):
        self.calls.append(self.cycle);self.root.mkdir(mode=0o700);archive=self.root/'image.tar';archive.write_bytes(b'synthetic transport artifact');archive.chmod(0o600)
        r=dict(schema='pi-nightly-local-image-v1',status='ready',cycle_id=self.cycle,base_image_id=base,image_id='sha256:'+'7'*64,source_sha256=tree_hash(source),candidate_sha256=tree_hash(candidate),package_sha256='8'*64,archive_path=str(archive),archive_sha256=file_hash(archive),published=False,deployed=False)
        p=self.root/'receipt.json';p.write_text(json.dumps(r));p.chmod(0o600);return r


@pytest.fixture
def bundle_case(finished):
    state,fee,task,qp,q,c,r=finished;store=state.parent/'nightly.sqlite';ApprovalGate.initialize(store,state,fee,mode='SIMULATED')
    now=[datetime(2026,10,30,18,tzinfo=timezone.utc)];g=ApprovalGate(store,state,fee,mode='SIMULATED',clock=lambda:now[0]);cycle=str(uuid.uuid4());g.begin(cycle,'2026-10-31')
    parent=qp.parent/'nightly';parent.mkdir(mode=0o700);root=parent/cycle;root.mkdir(mode=0o700);Image.calls=[]
    return g,cycle,root,task,finished,now


def prepare(case):
    from ops.pi.nightly_bundle import prepare
    g,cycle,root,task,_,_=case
    return prepare(g,cycle,root/'bundle',task,'sha256:'+'6'*64,Path('/bin/echo'),'unix:///test.sock','test-daemon',image_factory=Image)


def test_verified_original_candidate_is_frozen_with_comparison_and_no_release(bundle_case):
    g,cycle,root,task,finished,now=bundle_case;before=ledger_snapshot(finished[0]),ledger_snapshot(finished[1]);result=prepare(bundle_case)
    assert result['phase']=='awaiting_approval' and result['cycle_id']==cycle and Image.calls==[cycle]
    from ops.pi.nightly_bundle import verify
    packet=verify(g,root/'bundle');manifest=packet['manifest'];assert result['package_sha256']==digest(manifest)
    assert manifest['source_sha256']==tree_hash(Path(finished[5]['root'])/'candidate')
    assert tree_hash(root/'bundle/candidate')==manifest['source_sha256'] and tree_hash(root/'bundle/baseline')==manifest['baseline_sha256']
    comparison=packet['comparison'];assert file_hash(root/'bundle/regression.py')==comparison['test_sha256'];assert comparison['anchor']=='verified_deployment' and comparison['day_offset']==1 and comparison['status']=='planned'
    assert comparison['online_improvement_proven'] is False and comparison['test_cases']==finished[5]['test_cases']
    evaluation=packet['evaluation'];assert evaluation['sdk_verified'] and evaluation['independent_review']['kind']=='pre_development_file_review' and evaluation['checker']['passed']
    assert (ledger_snapshot(finished[0]),ledger_snapshot(finished[1]))==before
    assert packet['image']['published'] is packet['image']['deployed'] is False
    assert packet['changes'] and (root/'bundle/patch.diff').read_text()
    now[0]+=timedelta(days=10)
    with pytest.raises(ValueError):prepare(bundle_case)
    assert Image.calls==[cycle] and g.status()['cycle_id']==cycle


@pytest.mark.parametrize('fault',['candidate','patch','evaluation','comparison','changes','archive','manifest','regression'])
def test_postseal_drift_is_detected_before_any_publication(bundle_case,fault):
    prepare(bundle_case);g,_,root,*_=bundle_case;bundle=root/'bundle'
    if fault=='candidate':next((bundle/'candidate').rglob('*.py')).write_text('tampered')
    elif fault=='regression':(bundle/'regression.py').write_text('tampered')
    elif fault=='archive':(root/'image/image.tar').write_bytes(b'tampered')
    else:(bundle/({'patch':'patch.diff'}.get(fault,fault+'.json'))).write_text('{}')
    from ops.pi.nightly_bundle import verify
    with pytest.raises(ValueError):verify(g,bundle)


def test_incomplete_or_changed_original_development_never_reaches_image_builder(bundle_case):
    c=bundle_case[4][5];p=Path(c['root'])/'result.json';p.write_text('{}')
    with pytest.raises(ValueError):prepare(bundle_case)
    assert Image.calls==[] and bundle_case[0].status()['phase']=='preparing'


def test_interrupted_image_claim_is_not_replayed_or_resealed(bundle_case):
    from ops.pi import nightly_bundle
    def fail(*a,**k):raise TimeoutError('unknown image preparation')
    Image.build_original=Image.build
    try:
        Image.build=fail
        with pytest.raises(TimeoutError):prepare(bundle_case)
    finally:Image.build=Image.build_original
    with pytest.raises(ValueError):prepare(bundle_case)
    assert not (bundle_case[2]/'bundle/manifest.json').exists()


def test_image_metadata_is_bound_even_if_both_private_receipt_copies_change(bundle_case):
    prepare(bundle_case);g,_,root,*_=bundle_case
    for p in (root/'image/receipt.json',root/'bundle/image.json'):
        data=json.loads(p.read_bytes());data['base_image_id']='sha256:'+'9'*64;p.write_text(json.dumps(data))
    from ops.pi.nightly_bundle import verify
    with pytest.raises(ValueError):verify(g,root/'bundle')


def test_reserved_audit_and_tool_flow_are_admin_readable_without_duplicate_model_charges(bundle_case):
    prepare(bundle_case);g,cycle,root,task,finished,now=bundle_case
    from ops.pi.nightly_bundle import verify
    from ops.pi.audit import AuditStore
    from myink.pi_audit import AuditReader
    packet=verify(g,root/'bundle');audit=packet['audit'];flow=packet['tool_flow']
    assert flow and [r['sequence'] for r in flow]==list(range(1,len(flow)+1))
    assert all({'tool','operation_id','status','receipt_sha256'}<=set(r) for r in flow)
    assert str(finished[0].parent.parent) not in json.dumps(audit)
    parent=root/'audit-state';parent.mkdir(mode=0o700);store=AuditStore(parent/'audit.sqlite')
    for item in audit['records']:store.append(item['record_key'],item['event'])
    export=root/'audit-export';store.export(export);reader=AuditReader(export)
    events=reader.events(task)['items'];assert len(events)==2
    assert {e['status'] for e in events}=={'no_release','blocked'}
    assert all(e['details'].get('model_requests',0)==0 and e['details'].get('known_cost_microyuan',0)==0 for e in events)
    assert all(not e['followups'] for e in events) # Calendar dates only after deployment.
