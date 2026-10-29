"""Finite automatic selection authority remains live up to provider forwarding."""
from datetime import timedelta
from pathlib import Path
import importlib
import pytest
from ops.pi.development_inputs import file_hash,ledger_snapshot,read_json
from ops.pi.tests.test_manager_review_worker import published,handoff,completed,review_config,dossier_input,config_file,proof,select,write,NOW


def test_issuer_revocation_during_sdk_startup_stops_before_reservation(published,proof,monkeypatch):
    q=published[1];before=ledger_snapshot(published[3]['ledger_path'])
    def revoke():
        path=Path(q['issuer_policy_path']);p=read_json(path);p['expires_at']=(NOW-timedelta(seconds=1)).isoformat();write(path,p)
    sp,sc,task=select(published,proof,monkeypatch,before_forward=revoke);result=read_json(Path(sc['root'])/'result.json')
    assert result['verified'] is False and result['new_attempts']==0 and ledger_snapshot(sc['ledger_path'])==before


def test_issuer_revoked_before_selection_cannot_create_host_or_attempt(published,proof,monkeypatch):
    q=published[1];path=Path(q['issuer_policy_path']);p=read_json(path);p['expires_at']=(NOW-timedelta(seconds=1)).isoformat();write(path,p);before=ledger_snapshot(published[3]['ledger_path'])
    with pytest.raises(ValueError):select(published,proof,monkeypatch)
    assert not (Path(q['root'])/'bundle/selection-output').exists() and ledger_snapshot(published[3]['ledger_path'])==before


def test_unchanged_issuer_expiring_during_startup_stops_before_reservation(published,proof,monkeypatch):
    now=[NOW];before=ledger_snapshot(published[3]['ledger_path'])
    sp,sc,task=select(published,proof,monkeypatch,before_forward=lambda:now.__setitem__(0,NOW+timedelta(days=2)),clock=lambda:now[0]);result=read_json(Path(sc['root'])/'result.json')
    assert result['verified'] is False and result['new_attempts']==0 and ledger_snapshot(sc['ledger_path'])==before


def test_actual_selection_rejects_injected_authorization_clock(published):
    from threading import Event
    import time
    cycle=read_json(published[4]['cycle_path']);cp=Path(cycle['selection_config_path']);sc=read_json(cp);tasks=read_json(sc['catalog_path']);before=ledger_snapshot(sc['ledger_path'])
    with pytest.raises(ValueError):importlib.import_module('ops.pi.selection_launcher').execute(cp,dict(mode='ACTUAL',source_sha256=sc['source_sha256'],tasks=tasks,input_hash='c'*64,deadline=time.monotonic()+90,cancel=Event()),expected_config_sha256=file_hash(cp),clock=lambda:NOW)
    assert ledger_snapshot(sc['ledger_path'])==before and not Path(sc['root']).exists()
