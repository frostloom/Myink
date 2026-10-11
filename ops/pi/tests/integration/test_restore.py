"""Complete synthetic PG16 recovery, guarded by the actual owned native lab."""
import pytest
from ops.pi.lab import backup_lab
pytestmark=pytest.mark.pi_lab


def test_actual_pre_post_pair_complete_restore_and_snapshot(lab_identity):
    result=backup_lab.run_actual_pair()
    assert result['pre']=='done' and result['post']=='done'
    assert result['restore']=='done'
    assert result['offsite_status']=='not_configured'
    assert result['census_unknown']==0 and result['source_unchanged']


@pytest.mark.parametrize('fault',['wrong-key','missing-key','missing-role','missing-attachment','missing-certificate'])
def test_actual_restore_negative_materials(fault,lab_identity):
    result=backup_lab.run_restore_fault(fault)
    assert result.status=='failed'
