"""PRE and POST both receive genuine two-image application qualification."""
from dataclasses import asdict
import json,uuid
import pytest
from test_product_backup import product_backup,bootstrap_case
from test_product_application_restore import test_frozen_images_read_restored_business_data_without_models as run_source_case
pytestmark=pytest.mark.pi_followup_docker


def test_post_application_restore_keeps_writes_after_pre_snapshot(product_backup,monkeypatch):
    from ops.pi.product_restore import OwnedPostgresRestore
    from ops.pi.backup import create_backup,record_recovery_references,mark_released
    original=OwnedPostgresRestore.restore;completed=[]
    def paired(self,receipt,*,qualification='materials'):
        assert qualification=='application' and receipt.evidence['phase']=='PRE'
        pre=original(self,receipt,qualification=qualification);completed.append('PRE')
        h=self.host;b=self.backend
        refs=record_recovery_references(h.ledger,'application-pre-references',version=1,context=b.context,complete=True,stable_ids=[receipt.evidence['backup_id']],referenced_ids=[])
        assert refs.status=='done'
        mark_released(h.ledger,h.plan['operation_id'],asdict(b.candidate),context=b.context,now=h.clock())
        command=['exec',h._cid('postgres'),'psql','-X','-q','-A','-t','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c']
        new_id=str(uuid.uuid4())
        h._run(command+["INSERT INTO tasks SELECT '"+new_id+"'::uuid,project_id,'{\"after_release\":true}'::json,'done' FROM tasks LIMIT 1"])
        h.inspect_candidate=lambda plan:dict(plan['candidate'])
        h.measure_candidate_quiet=h.measure_quiet
        h.backup_container_id=lambda phase,role:('a'*64 if phase=='POST' and role=='api' else h._cid(role))
        post=create_backup(h.ledger,'POST',b.candidate,b,b.collections,pair=b.pair)
        assert post.status=='done',post
        result=original(OwnedPostgresRestore(b),post,qualification=qualification);completed.append('POST')
        assert result.evidence['target_system_identifier']!=pre.evidence['target_system_identifier']
        assert json.loads(h._bytes(h._run(command+["SELECT json_build_object('n',count(*)) FROM tasks WHERE payload->>'after_release'='true'"])))['n']==1
        # Both two-image proofs are separately bound to the actual restored PG.
        assert set(pre.evidence['application_probes'])==set(result.evidence['application_probes'])=={'legacy','candidate'}
        return result
    monkeypatch.setattr(OwnedPostgresRestore,'restore',paired)
    run_source_case(product_backup,None)
    assert completed==['PRE','POST']
