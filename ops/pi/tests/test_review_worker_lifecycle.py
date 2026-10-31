"""Expired policy never creates permission; terminal facts remain readonly."""
from datetime import timedelta
from pathlib import Path
import importlib
import pytest
from ops.pi.development_inputs import file_hash,ledger_snapshot,read_json
from ops.pi.tests.test_manager_review_worker import published,handoff,completed,review_config,dossier_input,config_file,proof,select,prepared_config,write,NOW


def api():return importlib.import_module('ops.pi.manager_review_worker')


def call(published,late=False):return api().tick(published[0],file_hash(published[0]),clock=lambda:NOW+timedelta(days=2) if late else NOW)


@pytest.mark.parametrize('terminal',['published','no_action'])
def test_completed_facts_remain_readable_after_expiry_without_new_authority(published,proof,monkeypatch,terminal):
    sp,sc,task=select(published,proof,monkeypatch,abstain=terminal=='no_action')
    if terminal=='published':prepared_config(published,task)
    assert call(published)['status']==terminal;before=ledger_snapshot(sc['ledger_path'])
    result=call(published,True);assert result['status']==terminal and result['cached'] is True and result['model_requests']==0
    assert api().inspect_terminal(published[0],file_hash(published[0]),clock=lambda:NOW+timedelta(days=2))['status']==terminal
    assert ledger_snapshot(sc['ledger_path'])==before
    from ops.pi.review_lease import load_policy
    q=published[1]
    with pytest.raises(ValueError):load_policy(q['issuer_policy_path'],q['issuer_policy_sha256'],lambda:NOW+timedelta(days=2))


def test_expired_pending_selection_cannot_bind_or_publish(published,proof,monkeypatch):
    sp,sc,task=select(published,proof,monkeypatch);prepared_config(published,task);before=ledger_snapshot(sc['ledger_path'])
    with pytest.raises(ValueError):call(published,True)
    assert not (Path(published[4]['lease_path']).parent/'binding').exists() and ledger_snapshot(sc['ledger_path'])==before


def test_readonly_terminal_inspection_does_not_advance_a_valid_pending_task(published,proof,monkeypatch):
    sp,sc,task=select(published,proof,monkeypatch);before=ledger_snapshot(sc['ledger_path'])
    assert api().inspect_terminal(published[0],file_hash(published[0]),clock=lambda:NOW) is None
    assert not (Path(published[4]['lease_path']).parent/'binding').exists() and ledger_snapshot(sc['ledger_path'])==before


def test_expired_completed_receipt_with_drift_is_not_accepted_as_terminal(published,proof,monkeypatch):
    sp,sc,task=select(published,proof,monkeypatch);cp,current=prepared_config(published,task);assert call(published)['status']=='published';write(cp.parent/'review.json',{})
    with pytest.raises(ValueError):call(published,True)
