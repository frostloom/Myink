"""A prior independent review may authorize only its exact frozen selection catalog."""
from pathlib import Path
import importlib,pytest
from ops.pi.audit import digest
from ops.pi.development_inputs import authorization_hash,file_hash,ledger_snapshot,read_json,validate_review
from ops.pi.tests.test_review_lease import completed,write,NOW
from ops.pi.tests.test_sdk_review_launcher import review_config
from ops.pi.tests.test_review_dossier import dossier_input,config_file
from ops.pi.tests.test_selection_launcher import proof


@pytest.fixture
def ready(completed,monkeypatch):
    pp,p,cp,c,tc=completed;selection=importlib.import_module('ops.pi.selection_launcher');monkeypatch.setattr(selection,'verify_source',lambda *args:dict(machine='aarch64'))
    lease=importlib.import_module('ops.pi.review_lease').create(pp,file_hash(pp),cp,file_hash(cp),clock=lambda:NOW)
    catalog=read_json(c['outcome_path'])['catalog'];catalog_path=cp.parent/'selector-catalog.json';write(catalog_path,catalog)
    sc={k:tc[k] for k in selection.FIELDS if k in tc};sc.update(schema='pi-maintenance-selection-v1',prompt_version=2,run_id='approved-selection',root=str(cp.parent/'selection-output'),ledger_sha256=ledger_snapshot(c['ledger_path'])['sha256'],catalog_path=str(catalog_path),catalog_sha256=file_hash(catalog_path),deadline_seconds=60,review_path=str(cp.parent/'selection-review.json'),review_sha256='0'*64)
    sp=cp.parent/'selection-config.json';write(sp,sc);return pp,p,cp,c,tc,lease,sp,sc,catalog


def api():return importlib.import_module('ops.pi.selection_review_issuer')


def test_host_issues_exact_selection_review_without_another_model(ready):
    pp,p,cp,c,tc,lease,sp,sc,catalog=ready;before=ledger_snapshot(c['ledger_path'])
    result=api().issue(lease['lease_path'],lease['lease_sha256'],sp,file_hash(sp),clock=lambda:NOW)
    review=read_json(sc['review_path']);validate_review(review,sc,digest(catalog),sc['source_sha256'])
    assert result['model_requests']==0 and result['status']=='published' and ledger_snapshot(c['ledger_path'])==before
    assert not Path(sc['root']).exists()
    sc['review_sha256']=file_hash(sc['review_path']);write(sp,sc)
    assert importlib.import_module('ops.pi.selection_launcher').prepare(sp)[0]==sc
    with pytest.raises(ValueError):api().issue(lease['lease_path'],lease['lease_sha256'],sp,file_hash(sp),clock=lambda:NOW)


@pytest.mark.parametrize('fault',['policy','catalog','source','runtime','fee','review_location','config_pin','lease_pin','existing'])
def test_host_selection_scope_cannot_be_broadened(ready,fault):
    pp,p,cp,c,tc,lease,sp,sc,catalog=ready;lp=lease['lease_sha256']
    if fault=='policy':write(pp,{})
    elif fault=='catalog':catalog[0]['problem']='changed';write(Path(sc['catalog_path']),catalog);sc['catalog_sha256']=file_hash(sc['catalog_path'])
    elif fault in ('source','runtime'):sc[fault+'_sha256']='f'*64
    elif fault=='fee':sc['ledger_sha256']='f'*64
    elif fault=='review_location':sc['review_path']=str(sp.parent/'wrong-review.json')
    elif fault=='lease_pin':lp='f'*64
    elif fault=='existing':write(Path(sc['review_path']),dict(previous=True))
    write(sp,sc);pin='f'*64 if fault=='config_pin' else file_hash(sp);before=ledger_snapshot(c['ledger_path'])
    with pytest.raises((ValueError,OSError,KeyError)):api().issue(lease['lease_path'],lp,sp,pin,clock=lambda:NOW)
    assert ledger_snapshot(c['ledger_path'])==before
    if fault!='existing':assert not Path(sc['review_path']).exists()
