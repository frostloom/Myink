"""Inspection cannot promote frozen observations to model or repair authority."""
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import importlib,json
import pytest
from ops.pi.tests.test_live_observer import configured,Rows,run,NOW,api as observer
from ops.pi.audit import digest,encoded


def api():return importlib.import_module('ops.pi.live_diagnosis')


def inspect(configured,result,now=NOW,pin=None,controller=None):
    p,c=configured
    return api().inspect_observation(p,pin or sha256(p.read_bytes()).hexdigest(),Path(c['root'])/result['run_id']/'receipt.json',expected_controller_sha256=controller or observer()._controller(),clock=lambda:now)


def test_insufficient_and_known_synthetic_are_only_observations(configured):
    result=run(configured,Rows(1));e=inspect(configured,result)
    assert e['schema']=='pi-live-evidence-v1' and e['authority']=='observation_only'
    assert e['mode']=='SIMULATED' and e['evidence_domain']=='synthetic' and e['observed_samples']==1
    assert e['minimum_samples']==20 and 'insufficient_samples' in e['gaps'] and e['repair_eligible'] is False
    assert len(e['evidence_fingerprint'])==64 and len(e['cohort_sha256'])==64
    assert not any(k.endswith('_path') for k in e)


def test_unchanged_rolling_window_does_not_create_new_charge_identity(configured):
    first=run(configured,Rows(20));second=run(configured,Rows(20),lambda:NOW+timedelta(minutes=15))
    a=inspect(configured,first);b=inspect(configured,second,NOW+timedelta(minutes=15))
    assert a['snapshot_sha256']!=b['snapshot_sha256'] and a['evidence_fingerprint']==b['evidence_fingerprint']
    assert a['repair_eligible'] is False and a['model_requests']==0


@pytest.mark.parametrize('fault',['pin','controller','receipt','snapshot','shape','bool','nan','stale','future','symlink'])
def test_drift_malformed_or_stale_sources_are_rejected(configured,fault,tmp_path):
    result=run(configured,Rows(1));root=Path(configured[1]['root'])/result['run_id'];receipt=root/'receipt.json';snapshot=root/'metrics.json'
    if fault=='pin':
        with pytest.raises(ValueError):inspect(configured,result,pin='0'*64)
        return
    if fault=='controller':
        with pytest.raises(ValueError):inspect(configured,result,controller='0'*64)
        return
    if fault=='receipt':
        changed=json.loads(receipt.read_bytes());changed['status']='passed';receipt.write_text(json.dumps(changed))
    elif fault=='snapshot':snapshot.write_bytes(snapshot.read_bytes()+b' ')
    elif fault in ('shape','bool','nan'):
        value=json.loads(snapshot.read_bytes())
        if fault=='shape':value['command']='never'
        elif fault=='bool':value['complete_tasks']=True
        else:value['measurements']['cost']['value']=float('nan')
        snapshot.write_text(json.dumps(value));r=json.loads(receipt.read_bytes());r['snapshot_sha256']=sha256(snapshot.read_bytes()).hexdigest();r['receipt_sha256']=digest({k:v for k,v in r.items() if k!='receipt_sha256'});receipt.write_bytes(encoded(r))
    elif fault=='stale':
        with pytest.raises(ValueError):inspect(configured,result,NOW+timedelta(hours=2))
        return
    elif fault=='future':
        with pytest.raises(ValueError):inspect(configured,result,NOW-timedelta(hours=2))
        return
    elif fault=='symlink':
        copy=tmp_path/'aliased-receipt';copy.write_bytes(receipt.read_bytes());receipt.unlink();receipt.symlink_to(copy)
    with pytest.raises(ValueError):inspect(configured,result)


def test_mixed_unknown_or_missing_quality_cannot_approve_a_repair(configured):
    for index,rows in enumerate((Rows(20,mixed=True),Rows(20,missing=True),Rows(20))):
        now=NOW+timedelta(minutes=15*index);e=inspect(configured,run(configured,rows,lambda:now),now)
        assert e['repair_eligible'] is False and e['requires']==['source_bound_reproducer','independent_review']
        assert 'insufficient_tail_samples' in e['gaps']


@pytest.mark.parametrize('fault',['receipt_domain','receipt_threshold','metric_shape'])
def test_semantically_inconsistent_but_rehashed_artifacts_are_rejected(configured,fault):
    result=run(configured,Rows(1));root=Path(configured[1]['root'])/result['run_id'];path=root/'receipt.json';r=json.loads(path.read_bytes())
    if fault=='receipt_domain':r['evidence_domain']='online_business'
    elif fault=='receipt_threshold':r['minimum_samples']=1
    else:
        p=root/'metrics.json';m=json.loads(p.read_bytes());m['pricing_id']={'command':'not metadata'};p.write_bytes(encoded(m));r['snapshot_sha256']=sha256(p.read_bytes()).hexdigest()
    r['receipt_sha256']=digest({k:v for k,v in r.items() if k!='receipt_sha256'});path.write_bytes(encoded(r))
    with pytest.raises(ValueError):inspect(configured,result)
