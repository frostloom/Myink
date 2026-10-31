"""Historical original admission is authenticated without reviving old authority."""
from pathlib import Path
import importlib
import pytest
from ops.pi.development_inputs import file_hash,read_json
from ops.pi.tests.test_autonomy_coordinator import profile,research_config,diagnosis_config,config_file,configured,proof,write,NOW,kernels


@pytest.mark.parametrize('fault',[None,'source','phase','phase_result','handoff','withdrawal','coordinator'])
def test_stage_requires_complete_original_admission_not_only_inbox_or_declared_success(profile,proof,monkeypatch,fault):
    pp,p,c,context=profile;coordinator=importlib.import_module('ops.pi.autonomy_coordinator');runner,calls=kernels(profile,proof,monkeypatch);r=coordinator.run(pp,file_hash(pp),runner=runner,clock=lambda:NOW);assert r['status']=='admitted'
    claim=Path(p['root'])/r['research_fingerprint']
    if fault=='source':p['source']['source_sha256']='f'*64
    elif fault=='phase':write(claim/'phase-investigation/receipt.json',dict(status='done'))
    elif fault=='phase_result':v=read_json(claim/'phase-sdk_review/result-private.json');v['status']='blocked';write(claim/'phase-sdk_review/result-private.json',v)
    elif fault=='handoff':(Path(p['handoff_root'])/('request-'+claim.name+'.json')).write_bytes(b'{}')
    elif fault=='withdrawal':(claim/'withdrawal').mkdir(mode=0o700)
    elif fault=='coordinator':write(claim/'receipt.json',dict(r,status='no_task'))
    module=importlib.import_module('ops.pi.candidate_review_stage')
    if fault:
        with pytest.raises((ValueError,OSError)):module._admitted(p,claim)
    else:
        result=module._admitted(p,claim);assert result==dict(task_id='auto-'+claim.name[:32],cycle_sha256=r['cycle_sha256'])
    assert not list(Path(p['permit_root']).glob('candidate-review-*'))
