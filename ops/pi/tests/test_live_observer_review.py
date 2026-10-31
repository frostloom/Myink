"""Concrete final-review regressions, independent of production data."""
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import json
from ops.pi.tests.test_live_observer import configured,Rows,run,NOW,api,update
from myink.pi_audit import AuditReader


def test_null_image_cohort_never_certifies_measured_observation(configured):
    rows=Rows(20)
    def source(request):
        result=rows(request)
        if request['source']=='agent_runs':
            for row in result:row['provenance']=dict(row['provenance'],image_ids=dict(web=None))
        return result
    result=run(configured,source)
    assert result['status']=='insufficient_evidence' and result['availability']=='unknown'


def test_daily_sample_count_does_not_add_overlapping_cohorts(configured):
    run(configured,Rows(20));run(configured,Rows(20),lambda:NOW+timedelta(minutes=15))
    reader=AuditReader(Path(configured[1]['audit_path']).parent/'export')
    day=reader.daily('2026-10-28')
    assert day['observed_samples'] is None
    assert len(day['sample_windows'])==2
    assert [x['observed_samples'] for x in day['sample_windows']]==[20,20]


def test_actual_observer_cannot_claim_a_product_release_outcome(configured,monkeypatch):
    path=update(configured,mode='ACTUAL');module=api()
    monkeypatch.setattr(module,'PsqlMetricsReader',lambda *a,**k:Rows())
    result=module.observe(path,clock=lambda:NOW,expected_config_sha256=sha256(path.read_bytes()).hexdigest())
    reader=AuditReader(Path(configured[1]['audit_path']).parent/'export')
    assert reader.daily('2026-10-28')['release_state']=='unknown'
    assert reader.events(result['run_id'],kind='deployment')['total']==0
