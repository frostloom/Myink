"""Catalog availability, image labels and audit data cannot authorize release."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import importlib,json
import pytest
from ops.pi.audit import AuditStore,digest
from ops.pi.development_inputs import file_hash,read_json
from ops.pi.tests.test_product_reality import product,runner,observe,NOW


def api():return importlib.import_module('ops.pi.product_preflight')

def rehash(value):
    raw={k:v for k,v in value.items() if k not in ('observation_sha256','observation_path')};value['observation_sha256']=digest(raw);return value


def test_actual_shaped_missing_protocol_and_ownership_are_explicit_blockers(product):
    r=observe(product);p=api().inspect_reality(r,at=NOW);codes={b['code'] for b in p['blockers']}
    assert p['release_allowed'] is False and p['authority']=='none' and p['status']=='blocked' and p['observation_sha256']==r['observation_sha256']
    assert {'maintenance_protocol_absent','run_provenance_absent','deployment_ownership_unknown','source_attestation_missing','functional_pause_resume_unverified','compatible_backup_restore_unverified','main_adoption_and_ci_unverified','explicit_product_release_authorization_required','business_validation_unverified'}<=codes
    assert p['component_images']=={k:v['image_id'] for k,v in r['images'].items()}


def test_table_presence_is_not_functional_pause_backup_or_product_approval(product):
    product[4].update({k:True for k in product[4]});r=observe(product);p=api().inspect_reality(r,at=NOW);codes={b['code'] for b in p['blockers']}
    assert 'maintenance_protocol_absent' not in codes and 'run_provenance_absent' not in codes
    assert {'functional_pause_resume_unverified','compatible_backup_restore_unverified','explicit_product_release_authorization_required'}<=codes and not p['release_allowed']


@pytest.mark.parametrize('fault,code',[('old','observation_stale'),('future','observation_clock_unverified'),('confounded','product_inventory_unverified'),('catalog','maintenance_catalog_unknown'),('health','runtime_health_unverified')])
def test_stale_partial_unknown_or_unhealthy_cannot_become_release_base(product,fault,code):
    if fault=='health':product[2][0]['healthy']='unhealthy'
    r=observe(product,runner(product,fault='drift' if fault=='confounded' else 'metadata_error' if fault=='catalog' else None)[0])
    at=NOW+timedelta(minutes=6) if fault=='old' else NOW-timedelta(seconds=1) if fault=='future' else NOW
    p=api().inspect_reality(r,at=at);assert code in {b['code'] for b in p['blockers']} and not p['release_allowed']


@pytest.mark.parametrize('fault',['hash','approved','authority','identity','attested','extra','mode'])
def test_caller_cannot_upgrade_observed_facts_to_authority(product,fault):
    r=observe(product)
    if fault=='hash':r['containers'][0]['image_id']='sha256:'+'f'*64
    else:
        if fault=='approved':r['release_allowed']=True
        elif fault=='authority':r['authority']='release'
        elif fault=='identity':r['owner']='pi';r['generation']=2;r['deployment_id']='caller-forged'
        elif fault=='attested':r['images']['python']['source_attested']=True
        elif fault=='extra':r['approved']=True
        else:r['mode']='UNKNOWN'
        rehash(r)
    with pytest.raises(ValueError):api().inspect_reality(r,at=NOW)


def test_reader_sees_component_observations_and_blockers_without_source_or_permission_laundering(product):
    from myink.pi_audit import AuditReader
    cp,c,*_=product;execute,calls=runner(product);result=api().observe_and_publish(cp,file_hash(cp),runner=execute,clock=lambda:NOW)
    assert result['status']=='recorded' and result['audit_exported'] and result['model_requests']==0 and not result['release_allowed']
    rows=AuditReader(c['export_root']).events(result['run_id'])['items'];assert len(rows)==3
    versions=[row for row in rows if row['kind']=='version'];assert len(versions)==2 and all(e['version']['source_commit'] is None and e['version']['owner'] is None and e['version']['generation'] is None for e in versions)
    assert {tuple(e['version']['image_ids']) for e in versions}=={('python',),('frontend',)}
    assert all(e['details']['availability']=='observed_only' for e in versions)
    plan=next(e for e in rows if e['kind']=='plan');assert plan['status']=='blocked' and plan['details']['reference']=='product.release_preflight.v1'
    assert all('model_requests' not in e['details'] and 'known_cost_microyuan' not in e['details'] for e in rows)
    assert not any(e['kind'] in ('deployment','rollback') for e in rows)


def test_unknown_catalog_error_is_sanitized_and_audit_failure_retains_private_proof(product,monkeypatch):
    cp,c,*_=product;execute,calls=runner(product,fault='metadata_error')
    def fail(*a,**k):raise OSError('synthetic export failure')
    monkeypatch.setattr(AuditStore,'export',fail);r=api().observe_and_publish(cp,file_hash(cp),runner=execute,clock=lambda:NOW)
    assert r['status']=='uncertain' and not r['audit_exported'] and r['model_requests']==0
    assert (Path(r['observation_path'])/'preflight.json').exists() and (Path(r['observation_path'])/'audit-failure.json').exists()
    rows=AuditStore(c['audit_path']).events(run_id=r['run_id']);assert len(rows)==3 and 'hidden-value' not in json.dumps(rows)


def test_product_preflight_is_stdlib_only():
    import subprocess,sys
    project=Path(__file__).resolve().parents[3];code="import sys;sys.path.insert(0,sys.argv[1]);import ops.pi.product_preflight;assert 'httpx' not in sys.modules and 'sqlalchemy' not in sys.modules and 'myink.db' not in sys.modules"
    p=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(project)],capture_output=True,text=True,timeout=10);assert p.returncode==0,p.stderr


def test_real_sqlite_lock_is_retained_as_uncertain_audit_outcome(product,monkeypatch):
    import sqlite3
    cp,c,*_=product;AuditStore(c['audit_path']);connect=sqlite3.connect;blocker=connect(c['audit_path']);blocker.execute('BEGIN IMMEDIATE')
    def fast(*a,**kw):kw['timeout']=0.02;return connect(*a,**kw)
    monkeypatch.setattr(sqlite3,'connect',fast)
    try:r=api().observe_and_publish(cp,file_hash(cp),runner=runner(product)[0],clock=lambda:NOW)
    finally:blocker.rollback();blocker.close()
    assert r['status']=='uncertain' and r['audit_exported'] is False and r['audit_failure_class']=='OperationalError'
    root=Path(r['observation_path']);assert read_json(root/'audit-failure.json')['failure_class']=='OperationalError' and read_json(root/'audit-outcome.json')['status']=='uncertain'
    assert AuditStore(c['audit_path']).events(run_id=r['run_id'])==[]
