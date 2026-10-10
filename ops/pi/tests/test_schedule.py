import pytest
from datetime import datetime
from ops.pi.tests.test_budget import policy, ledger
from ops.pi.contracts import Receipt
from ops.pi import schedule



from ops.pi.tests.test_plans import candidate


def now(time="03:00", day="2026-10-11"):
    return datetime.fromisoformat(f"{day}T{time}:00+08:00")


def receipt(ledger, day, name, evidence=None, status="done"):
    key=f"maintenance:{day}:{name}"
    ledger.intent(key, name, {})
    ledger.finish(Receipt(key, status, evidence or {"verified": True}))


def test_0530_refuses_new_candidate():
    w=schedule.window_at(now("05:30"))
    assert w["allow_new_candidate"] is False
    assert w["deadline"] == "2026-10-11T06:00:00+08:00"


def test_0600_requires_verified_open_receipt(ledger, policy):
    assert schedule.next_action(ledger, now("06:00"), {}, policy)["kind"] == "open"
    receipt(ledger, "2026-10-11", "open", {"verified": False})
    assert schedule.next_action(ledger, now("06:00"), {}, policy)["kind"] == "recover_open"


def test_backup_before_heavy_work(ledger, policy):
    assert schedule.next_action(ledger, now(), {}, policy)["kind"] == "pre_backup"
    receipt(ledger,"2026-10-11","pre_backup")
    assert schedule.next_action(ledger, now(), {}, policy)["kind"] == "analyze"


def test_pre_failure_still_allows_recovery(ledger, policy):
    receipt(ledger,"2026-10-11","pre_backup",status="failed")
    assert schedule.next_action(ledger, now(), {"budget_exhausted": True}, policy)["kind"] == "recover_open"


def test_development_needs_independent_hash_bound_receipts(ledger, policy):
    receipt(ledger,"2026-10-11","pre_backup")
    p=candidate()
    obs=dict(plan=p, phase="develop")
    assert schedule.next_action(ledger,now(),obs,policy)["kind"] == "plan_gate"
    for name in ("plan_rules", "plan_review"):
        receipt(ledger,"2026-10-11",name,{"plan_hash":p.plan_hash,"source":"model","verified":True})
    assert schedule.next_action(ledger,now(),obs,policy)["kind"] == "plan_gate"


def test_budget_exhaustion_does_not_block_reports_or_closing(ledger, policy):
    receipt(ledger,"2026-10-11","pre_backup")
    assert schedule.next_action(ledger,now(),{"budget_exhausted":True},policy)["kind"] == "report"
    assert schedule.next_action(ledger,now("05:30"),{"budget_exhausted":True},policy)["kind"] == "close"


def test_post_timeout_registers_gap_before_open(ledger, policy):
    receipt(ledger,"2026-10-11","publish")
    assert schedule.next_action(ledger,now("06:00"),{},policy)["kind"] == "backup_pending"
    receipt(ledger,"2026-10-11","backup_pending")
    assert schedule.next_action(ledger,now("06:00"),{},policy)["kind"] == "open"


def test_pending_action_is_reconciled_and_scheduler_is_pure(ledger, policy):
    ledger.intent("maintenance:2026-10-11:pre_backup","pre_backup",{})
    before=ledger.get("maintenance:2026-10-11:pre_backup")
    assert schedule.next_action(ledger,now(),{},policy)["kind"] == "reconcile"
    assert ledger.get("maintenance:2026-10-11:pre_backup") == before


def test_naive_clock_rejected():
    import pytest
    with pytest.raises(ValueError): schedule.window_at(datetime(2026,10,11))


def gates(ledger, p, day="2026-10-11"):
    receipt(ledger,day,"plan_rules:"+p.plan_hash,{"plan_hash":p.plan_hash,"source":"deterministic_rules","verified":True})
    receipt(ledger,day,"plan_review:"+p.plan_hash,{"plan_hash":p.plan_hash,"source":"independent_review","reviewer_id":"separate-reviewer","verified":True})


def test_independent_review_allows_development_and_threshold_edit_revokes_it(ledger,policy):
    from dataclasses import replace
    p=candidate(); gates(ledger,p); receipt(ledger,"2026-10-11","pre_backup")
    assert schedule.next_action(ledger,now(),dict(plan=p,phase="develop"),policy)["kind"] == "develop"
    assert schedule.next_action(ledger,now(),dict(plan=replace(p,minimum_improvement=0.15),phase="develop"),policy)["kind"] == "plan_gate"


def test_grace_deadline_and_remaining_time_stop_heavy_work(ledger,policy):
    action=schedule.next_action(ledger,now("02:05"),dict(existing_tasks=1),policy)
    assert action["kind"] == "drain"
    assert action["deadline"] == "2026-10-11T02:15:00+08:00"
    assert schedule.next_action(ledger,now("02:16"),dict(existing_tasks=1),policy)["kind"] == "pause_tasks"
    receipt(ledger,"2026-10-11","pre_backup")
    assert schedule.next_action(ledger,now("05:29"),dict(phase="build",estimate_seconds=2700),policy)["kind"] == "save_work"


def test_unmet_goal_diagnoses_and_no_new_evidence_preserves_plan(ledger,policy):
    receipt(ledger,"2026-10-11","pre_backup")
    assert schedule.next_action(ledger,now(),dict(target_met=False),policy)["kind"] == "diagnose"
    assert schedule.next_action(ledger,now(),dict(plan=candidate(),new_evidence=False),policy)["kind"] == "save_work"


def test_daily_publish_cap_and_previous_post_gap(ledger,policy):
    receipt(ledger,"2026-10-11","pre_backup")
    receipt(ledger,"2026-10-11","publish")
    assert schedule.next_action(ledger,now(),dict(phase="publish"),policy)["kind"] == "post_backup"
    receipt(ledger,"2026-10-11","post_backup")
    assert schedule.next_action(ledger,now(),dict(phase="publish"),policy)["kind"] == "report"
    receipt(ledger,"2026-10-12","pre_backup")
    receipt(ledger,"2026-10-10","backup_pending")
    assert schedule.next_action(ledger,now(day="2026-10-12"),dict(phase="publish"),policy)["kind"] == "repair_backup"


def test_overnight_save_and_verified_open_report(ledger,policy):
    receipt(ledger,"2026-10-11","open")
    assert schedule.next_action(ledger,now("06:01"),dict(work_pending=True),policy)["kind"] == "save_work"
    receipt(ledger,"2026-10-11","save_work")
    assert schedule.next_action(ledger,now("06:01"),dict(work_pending=True),policy)["kind"] == "report"


def test_schedule_cli_is_offline(capsys):
    from ops.pi.control import main
    assert main(["schedule","--clock","2026-10-11T05:30:00+08:00","--simulate"]) == 0
    import json
    assert json.loads(capsys.readouterr().out)["kind"] == "close"


def test_hashed_publication_is_counted_and_pending_build_reconciles(ledger,policy):
    p=candidate(); gates(ledger,p); receipt(ledger,"2026-10-11","pre_backup")
    receipt(ledger,"2026-10-11","publish:"+p.plan_hash)
    assert schedule.next_action(ledger,now(),dict(phase="publish",plan=p),policy)["kind"] == "post_backup"


def test_model_self_review_at_exact_gate_identity_cannot_authorize(ledger,policy):
    p=candidate(); receipt(ledger,"2026-10-11","pre_backup")
    receipt(ledger,"2026-10-11","plan_rules:"+p.plan_hash,{"plan_hash":p.plan_hash,"source":"deterministic_rules","verified":True})
    receipt(ledger,"2026-10-11","plan_review:"+p.plan_hash,{"plan_hash":p.plan_hash,"source":"model","reviewer_id":"originating-pi","verified":True})
    assert schedule.next_action(ledger,now(),dict(plan=p,phase="develop"),policy)["kind"] == "plan_gate"


def test_observations_do_not_replace_ledger_authority(ledger,policy):
    receipt(ledger,"2026-10-11","pre_backup")
    assert schedule.next_action(ledger,now(),dict(plan=candidate(),phase="develop",rules_verified=True,review_verified=True),policy)["kind"] == "plan_gate"


def test_post_pending_at_deadline_does_not_delay_open(ledger,policy):
    receipt(ledger,"2026-10-11","publish")
    ledger.intent("maintenance:2026-10-11:post_backup","post_backup",{})
    assert schedule.next_action(ledger,now("06:00"),{},policy)["kind"] == "backup_pending"
    receipt(ledger,"2026-10-11","backup_pending")
    assert schedule.next_action(ledger,now("06:00"),{},policy)["kind"] == "open"


def test_completed_report_is_not_reexecuted(ledger,policy):
    receipt(ledger,"2026-10-11","pre_backup")
    receipt(ledger,"2026-10-11","report")
    assert schedule.next_action(ledger,now(),dict(budget_exhausted=True),policy)["kind"] == "wait"


def test_successful_phase_chain_and_missing_prior_phase(ledger,policy):
    p=candidate(); gates(ledger,p); receipt(ledger,"2026-10-11","pre_backup")
    assert schedule.next_action(ledger,now(),dict(plan=p,phase="build"),policy)["kind"] == "plan_gate"
    receipt(ledger,"2026-10-11","test:"+p.plan_hash)
    assert schedule.next_action(ledger,now(),dict(plan=p,phase="build"),policy)["kind"] == "build"
    ledger.intent("maintenance:2026-10-11:build:"+p.plan_hash,"build",{})
    assert schedule.next_action(ledger,now(),dict(plan=p,phase="build"),policy)["kind"] == "reconcile"


def test_phase_deadlines_apply_tool_bounds_and_absolute_window(ledger,policy):
    action=schedule.next_action(ledger,now(),{},policy)
    assert action["deadline"] == "2026-10-11T03:10:00+08:00"
    receipt(ledger,"2026-10-11","pre_backup")
    assert schedule.next_action(ledger,now(),{},policy)["deadline"] == "2026-10-11T03:02:00+08:00"
    p=candidate();gates(ledger,p);receipt(ledger,"2026-10-11","test:"+p.plan_hash)
    assert schedule.next_action(ledger,now(),dict(plan=p,phase="build"),policy)["deadline"] == "2026-10-11T03:45:00+08:00"


def test_before_window_preserves_pending_work_without_model_budget(ledger,policy):
    assert schedule.next_action(ledger,now("01:00",day="2026-10-12"),dict(work_pending=True,budget_exhausted=True),policy)["kind"] == "save_work"


def test_heavy_group_estimate_must_fit_group_limit_as_well_as_window(ledger,policy):
    receipt(ledger,"2026-10-11","pre_backup")
    p=candidate();gates(ledger,p);receipt(ledger,"2026-10-11","test:"+p.plan_hash)
    assert schedule.next_action(ledger,now(),dict(plan=p,phase="build",estimate_seconds=2701),policy)["kind"] == "save_work"


def test_multicall_development_has_phase_deadline_and_individual_tool_timeout(ledger,policy):
    from dataclasses import replace
    p=replace(candidate(),time_estimate=900)
    gates(ledger,p);receipt(ledger,"2026-10-11","pre_backup")
    action=schedule.next_action(ledger,now(),dict(plan=p,phase="develop"),policy)
    assert action["kind"] == "develop"
    assert action["deadline"] == "2026-10-11T03:15:00+08:00"
    assert action["tool_timeout_seconds"] == 120
