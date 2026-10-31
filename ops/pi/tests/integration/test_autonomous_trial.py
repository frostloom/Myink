"""Offline day/recovery integration. SIMULATED; no B12/pi_lab runtime claim."""
from datetime import datetime, timezone
from pathlib import Path
import pytest
from ops.pi.ledger import Ledger


@pytest.mark.parametrize('scenario', ['success','not-improved','regressed','sample-short','manual-main','config-change','budget-stop'])
def test_simulated_day_keeps_all_outcomes_and_never_releases(tmp_path, scenario):
    from ops.pi import iteration
    assert hasattr(iteration,'simulate_trial'), 'finite scenario integration missing'
    ledger=Ledger(tmp_path/'ledger.sqlite')
    receipt=iteration.simulate_trial(ledger,scenario,'local-trial-1',datetime(2026,10,12,18,tzinfo=timezone.utc))
    assert receipt.evidence['mode']=='SIMULATED' and receipt.evidence['released'] is False
    assert receipt.evidence['counted_reservations']==0
    with ledger.transaction() as db:
        kinds=[r[0] for r in db.execute('SELECT kind FROM operations')]
        stages=[ledger._decode(r[0])['stage'] for r in db.execute("SELECT payload FROM operations WHERE kind='iteration_stage'")]
    assert 'model-attempt' not in kinds
    if scenario=='budget-stop':
        assert receipt.status=='blocked' and receipt.evidence['recovery']['status']=='done'
    elif scenario!='success': assert 'iteration_followup' in kinds
    if scenario in ('not-improved','regressed'): assert 'diagnose' in stages
    if scenario=='regressed': assert stages.index('recover') < stages.index('diagnose')
