from dataclasses import replace
import pytest
from ops.pi.tests.test_budget import policy
from ops.pi import plans





def candidate(**changes):
    data = dict(hypothesis="reduce retry latency", metric="latency", minimum_improvement=0.1,
                severe_regression=0.2, sample_floor=20, guard_metrics=("errors",),
                baseline="base-1", baseline_config_hash="config-1", scope="speed", files=("app/worker.py",), slice_ids=("slice-1",),
                compatibility="unchanged API", rollback="restore prior image", call_estimate=2,
                time_estimate=60, behavior="retry", reason=None)
    data.update(changes)
    return plans.Plan(**data)


def baseline():
    return dict(id="base-1", paired_groups=5, complete_tasks=20, tail_samples=100,
                metric="latency", config_hash="config-1")


def test_new_feature_enters_user_decision(policy):
    assert plans.validate_plan(candidate(scope="new_feature"), baseline(), policy).evidence["reason"] == "user_decision"


def test_plan_soft_target_requires_smaller_slice_or_reason(policy):
    p = candidate(files=tuple(f"app/{i}.py" for i in range(4)))
    assert plans.validate_plan(p, baseline(), policy).status == "blocked"
    assert plans.validate_plan(replace(p, reason="shared atomic behavior"), baseline(), policy).status == "done"


def test_cumulative_diff_cannot_split_commits(policy):
    p = candidate()
    diff = dict(files=["app/worker.py"], production_added=151, production_deleted=150,
                tracked_files=1, plan_hash=p.plan_hash)
    assert plans.check_diff(p, diff, policy).status == "blocked"


def test_threshold_change_invalidates_comparison(policy):
    p = candidate()
    changed = replace(p, minimum_improvement=0.15)
    assert p.plan_hash != changed.plan_hash
    assert not plans.comparison_valid(changed, dict(plan_hash=p.plan_hash, baseline="base-1"))


def test_protected_path_and_risky_type_require_user_policy(policy):
    for p in (candidate(files=("ops/pi/policy.py",)), candidate(scope="schema")):
        assert plans.validate_plan(p, baseline(), policy).evidence["reason"] == "user_decision"


def test_insufficient_baseline_blocks(policy):
    b = baseline(); b["complete_tasks"] = 19
    assert plans.validate_plan(candidate(), b, policy).status == "blocked"


def test_diff_requires_frozen_hash_and_declared_paths(policy):
    p = candidate()
    for d in (dict(files=["other.py"], production_added=1, production_deleted=0, tracked_files=1, plan_hash=p.plan_hash),
              dict(files=["app/worker.py"], production_added=1, production_deleted=0, tracked_files=1)):
        assert plans.check_diff(p, d, policy).status == "blocked"


@pytest.mark.parametrize("changes", [dict(files=("../policy.py",)),dict(call_estimate=-1),dict(sample_floor=19),dict(minimum_improvement=float("nan")),dict(files=()),dict(slice_ids=())])
def test_malformed_plan_blocks(policy,changes):
    assert plans.validate_plan(candidate(**changes),baseline(),policy).status == "blocked"


def test_hard_file_cap_and_soft_line_reason(policy):
    p=candidate()
    d=dict(files=["app/worker.py"], production_added=151,production_deleted=0,tracked_files=1,plan_hash=p.plan_hash)
    assert plans.check_diff(p,d,policy).status == "blocked"
    p=candidate(reason="atomic fix"); d["plan_hash"]=p.plan_hash
    assert plans.check_diff(p,d,policy).status == "done"
    d["tracked_files"]=9
    assert plans.check_diff(p,d,policy).status == "blocked"


def test_p95_needs_one_hundred_samples(policy):
    b=baseline(); b.update(metric="p95",tail_samples=99)
    assert plans.validate_plan(candidate(metric="p95"),b,policy).status == "blocked"


def test_high_risk_type_cannot_hide_inside_speed_scope(policy):
    assert plans.validate_plan(candidate(change_types=("schema",)), baseline(), policy).evidence["reason"] == "user_decision"


def test_configuration_change_requires_new_frozen_baseline(policy):
    b=baseline(); b["config_hash"]="config-2"
    assert plans.validate_plan(candidate(),b,policy).status == "blocked"
    assert not plans.comparison_valid(candidate(),dict(plan_hash=candidate().plan_hash,baseline="base-1",config_hash="config-2"))


@pytest.mark.parametrize("changes", [dict(guard_metrics=({},)),dict(files=({},)),dict(change_types=()),dict(change_types=("unknown",))])
def test_structurally_invalid_collections_fail_closed(policy,changes):
    assert plans.validate_plan(candidate(**changes),baseline(),policy).status == "blocked"


def test_policy_plan_limits_cannot_be_relaxed(tmp_path):
    import json
    from pathlib import Path
    from ops.pi.policy import load_policy
    data=json.loads(Path("ops/pi/policy.example.json").read_text())
    for key,value in (("hard_tracked_files",9),("hard_production_lines",301),("grace_seconds",901),("protected_paths",[])):
        changed=dict(data);changed[key]=value
        path=tmp_path/"policy.json";path.write_text(json.dumps(changed))
        with pytest.raises(ValueError):load_policy(path)


@pytest.mark.parametrize("files", [[{}],["../bad.py"],["app/worker.py","app/worker.py"]])
def test_invalid_diff_collection_blocks(policy,files):
    p=candidate()
    assert plans.check_diff(p,dict(files=files,production_added=1,production_deleted=0,tracked_files=len(files),plan_hash=p.plan_hash),policy).status == "blocked"


@pytest.mark.parametrize("path", ["ops/pi./policy.py",".github /workflows/ci.yml","app/file.py\x00","app//worker.py"])
def test_ambiguous_filesystem_path_fails_closed(policy,path):
    assert plans.validate_plan(candidate(files=(path,)),baseline(),policy).status == "blocked"


def test_synthetic_only_baseline_uses_paired_floor_without_online_counts(policy):
    p=candidate(evidence_domain="synthetic",sample_floor=5)
    b=dict(id="base-1",metric="latency",config_hash="config-1",evidence_domain="synthetic",paired_groups=5)
    assert plans.validate_plan(p,b,policy).status == "done"
    b["paired_groups"]=4
    assert plans.validate_plan(p,b,policy).status == "blocked"


def test_online_floor_uses_complete_tasks_without_synthetic_or_tail_counts(policy):
    p=candidate(evidence_domain="online")
    b=dict(id="base-1",metric="latency",config_hash="config-1",evidence_domain="online",complete_tasks=20)
    assert plans.validate_plan(p,b,policy).status == "done"
    b["complete_tasks"]=19
    assert plans.validate_plan(p,b,policy).status == "blocked"


def test_evidence_domain_is_frozen_and_cannot_relabel_baseline(policy):
    p=candidate(evidence_domain="online")
    changed=replace(p,evidence_domain="synthetic",sample_floor=5)
    assert p.plan_hash != replace(p,evidence_domain="synthetic").plan_hash
    assert plans.validate_plan(changed,baseline(),policy).status == "blocked"


def test_synthetic_p95_needs_tail_floor_only_for_tail_conclusion(policy):
    p=candidate(evidence_domain="synthetic",sample_floor=5,metric="p95")
    b=dict(id="base-1",metric="p95",config_hash="config-1",evidence_domain="synthetic",paired_groups=5)
    assert plans.validate_plan(p,b,policy).status == "blocked"
    b["tail_samples"]=100
    assert plans.validate_plan(p,b,policy).status == "done"
