"""Automatic admission and deadline bounds in real Shanghai maintenance time."""
from datetime import datetime,timezone,timedelta
import importlib,pytest


def api():return importlib.import_module('ops.pi.maintenance_window')


def at(hour,minute=0,second=0):return datetime(2026,10,29,hour,minute,second,tzinfo=timezone(timedelta(hours=8)))


@pytest.mark.parametrize('hour,minute',[(1,59),(5,30),(6,0),(23,0)])
def test_automatic_task_cannot_start_outside_admission_window(hour,minute):
    with pytest.raises(ValueError):api().budget(at(hour,minute),2100)


@pytest.mark.parametrize('now',[at(2),at(5,20),at(5,29,59)])
def test_frozen_cycle_reserves_handoff_and_timer_delay_before_six(now):
    seconds=api().cycle_deadline(now,2100)
    assert 120<=seconds<=2090 and now+timedelta(seconds=seconds+180)<=at(6)
    later=now+timedelta(seconds=119)
    if later<at(5,30):assert seconds+10<=api().budget(later,2100)


def test_utc_representation_and_smaller_reviewed_ceiling_remain_bound():
    now=at(5,25);assert api().cycle_deadline(now.astimezone(timezone.utc),900)==900
    assert api().budget(now,2100)<2100 and now+timedelta(seconds=api().budget(now,2100))<at(6)


def test_old_or_cancelled_auto_history_does_not_window_gate_manual_queue():
    assert api().manager_budget('ACTUAL',False,at(12))==2100
    assert api().manager_budget('SIMULATED',True,at(12))==2100
    with pytest.raises(ValueError):api().manager_budget('ACTUAL',True,at(12))


@pytest.mark.parametrize('now',[at(2),at(5,30),at(5,54,58)])
def test_existing_candidate_review_can_finish_with_cleanup_and_audit_reserve(now):
    seconds=api().completion_budget(now,120)
    assert seconds==120 and now+timedelta(seconds=seconds+180)<at(6)


@pytest.mark.parametrize('now',[at(1,59),at(5,55),at(6),at(12)])
def test_existing_candidate_review_cannot_cross_six_or_start_in_daytime(now):
    with pytest.raises(ValueError):api().completion_budget(now,120)
