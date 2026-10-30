"""Waiting cycles stop scheduled hosts before importing side-effecting code."""
import sys
from datetime import timedelta
from pathlib import Path
import pytest
from ops.pi.tests.test_nightly_gate import case,ready,permit,deployment,NOW
from ops.pi.tests.test_observer_entry import module


def admission(g,component):
    from ops.pi.nightly_host import admission
    return admission(g,component)


@pytest.mark.parametrize('days',[0,1,7,30])
def test_waiting_stops_every_scheduled_component_across_dates(case,days):
    g,cycle=ready(case);case[1][0]=NOW+timedelta(days=days);g=case[0]()
    for component in ('observer','product_observer','followup','diagnosis','review_worker','autonomy','manager'):
        value=admission(g,component)
        assert value['status']=='waiting_human' and value['allowed'] is False
        assert value['cycle_id']==cycle and value['model_requests']==0


def test_approved_but_undeployed_still_stops_all_work(case):
    g,cycle=ready(case);(p,pin),_=permit(case,cycle,case[2]);g.approve(cycle,p,pin)
    assert not admission(g,'observer')['allowed']
    assert not admission(g,'manager')['allowed']


def test_only_deployed_cycle_allows_observers_not_new_development(case):
    g,cycle=ready(case);(p,pin),_=permit(case,cycle,case[2]);g.approve(cycle,p,pin)
    d,dpin=deployment(case,cycle,case[2],pin);g.deployed(cycle,d,dpin)
    for c in ('observer','product_observer','followup'):assert admission(g,c)['allowed']
    for c in ('manager','autonomy','diagnosis','review_worker'):assert not admission(g,c)['allowed']


def test_idle_needs_explicit_single_cycle_claim_and_unknown_component_is_rejected(case):
    g=case[0](True)
    assert not admission(g,'autonomy')['allowed']
    with pytest.raises(ValueError):admission(g,'shell')
    g.begin('00000000-0000-4000-8000-000000000001','2026-10-31')
    assert admission(g,'manager')['allowed']
    g.block('00000000-0000-4000-8000-000000000001','preparation interrupted')
    assert not admission(g,'manager')['allowed']


def test_verified_launcher_checks_gate_before_loading_host(tmp_path,monkeypatch,capsys):
    entry=module();seen=[];old=list(sys.path)
    monkeypatch.setattr(entry,'verify_release',lambda *a:seen.append('verified') or tmp_path/'code')
    import ops.pi.nightly_host as host
    monkeypatch.setattr(host,'runtime_admission',lambda component:seen.append(component) or dict(status='waiting_human',allowed=False,model_requests=0))
    monkeypatch.setattr(sys,'argv',['entry.py','--human-gated','--component','manager','--config','/unused','--config-sha256','a'*64])
    try:assert entry.main()==0
    finally:sys.path[:]=old
    assert seen==['verified','manager'] and 'waiting_human' in capsys.readouterr().out


def test_all_scheduled_units_require_human_gate():
    units=list(Path('ops/pi/deploy').glob('myink-pi-*.service'))
    assert len(units)==7
    for path in units:assert '--human-gated' in path.read_text(),path
