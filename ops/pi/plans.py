"""Frozen candidate contracts and deterministic gates; no model evidence is authority."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import PurePosixPath

from .contracts import Receipt, Record
from .policy import Policy


@dataclass(frozen=True)
class Plan:
    hypothesis: str
    metric: str
    minimum_improvement: float
    severe_regression: float
    sample_floor: int
    guard_metrics: tuple[str, ...]
    baseline: str
    baseline_config_hash: str
    scope: str
    files: tuple[str, ...]
    slice_ids: tuple[str, ...]
    compatibility: str
    rollback: str
    call_estimate: int
    time_estimate: int
    behavior: str
    reason: str | None = None
    change_types: tuple[str, ...] = ('behavior',)
    evidence_domain: str = 'online'

    @property
    def plan_hash(self):
        return sha256(json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                                 allow_nan=False).encode()).hexdigest()


def _path(path):
    return (isinstance(path, str) and path and '\\' not in path and ':' not in path
            and not any(ord(c) < 32 for c in path) and not PurePosixPath(path).is_absolute()
            and all(p not in ('', '.', '..') and not p.endswith(('.', ' ')) for p in path.split('/')))


def _protected(files, policy):
    return any(path.casefold() == prefix.casefold() or path.casefold().startswith(prefix.casefold().rstrip('/') + '/')
               for path in files for prefix in policy.protected_paths)


def _receipt(plan, reason=None):
    try:
        digest = plan.plan_hash
    except (ValueError, TypeError):
        digest = 'invalid'
    return Receipt('plan_rules:' + digest, 'blocked' if reason else 'done',
                   dict(plan_hash=digest, source='deterministic_rules', verified=reason is None,
                        reason=reason, independent_review_required=True))


def validate_plan(plan: Plan, baseline: Record, policy: Policy) -> Receipt:
    if not isinstance(plan, Plan) or not isinstance(baseline, dict):
        raise ValueError('plan and baseline required')
    texts = ('hypothesis', 'metric', 'baseline', 'baseline_config_hash', 'scope', 'compatibility', 'rollback', 'behavior')
    if any(not isinstance(getattr(plan, key), str) or not getattr(plan, key).strip() for key in texts):
        return _receipt(plan, 'invalid_plan')
    for key in ('files', 'slice_ids', 'guard_metrics', 'change_types'):
        values = getattr(plan, key)
        if (not isinstance(values, tuple) or not values
                or any(not isinstance(v, str) or not v.strip() for v in values)
                or len(values) != len(set(values))):
            return _receipt(plan, 'invalid_plan')
    if not all(_path(path) for path in plan.files):
        return _receipt(plan, 'invalid_path')
    if plan.scope not in ('stability', 'cost', 'speed', 'writing_quality', 'experience') or _protected(plan.files, policy) or any(t in policy.high_risk_types for t in plan.change_types):
        return _receipt(plan, 'user_decision')
    if any(t not in ('behavior', 'test', 'documentation') for t in plan.change_types):
        return _receipt(plan, 'invalid_change_type')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 1
           for v in (plan.minimum_improvement, plan.severe_regression)):
        return _receipt(plan, 'invalid_threshold')
    if plan.evidence_domain not in ('synthetic', 'online'):
        return _receipt(plan, 'invalid_evidence_domain')
    floor = 5 if plan.evidence_domain == 'synthetic' else 20
    if (type(plan.sample_floor) is not int or plan.sample_floor < floor
            or type(plan.call_estimate) is not int or not 0 <= plan.call_estimate <= policy.max_attempts
            or type(plan.time_estimate) is not int or plan.time_estimate <= 0):
        return _receipt(plan, 'invalid_estimate')
    if plan.reason is not None and (not isinstance(plan.reason, str) or not plan.reason.strip()):
        return _receipt(plan, 'invalid_reason')
    if len(plan.files) > policy.hard_tracked_files:
        return _receipt(plan, 'hard_scope_limit')
    if len(plan.files) > policy.soft_production_files and not plan.reason:
        return _receipt(plan, 'smaller_slice_or_reason')
    # Missing domain is legacy online data until the A4 evidence producer is integrated.
    domain = baseline.get('evidence_domain', 'online')
    count = baseline.get('paired_groups' if plan.evidence_domain == 'synthetic' else 'complete_tasks')
    if (domain != plan.evidence_domain or baseline.get('id') != plan.baseline
            or baseline.get('metric') != plan.metric or baseline.get('config_hash') != plan.baseline_config_hash
            or type(count) is not int or count < plan.sample_floor):
        return _receipt(plan, 'insufficient_baseline')
    if 'p95' in plan.metric.lower():
        tail = baseline.get('tail_samples')
        if type(tail) is not int or tail < 100:
            return _receipt(plan, 'insufficient_baseline')
    return _receipt(plan)


def check_diff(plan: Plan, diff: Record, policy: Policy) -> Receipt:
    """Diff is the trusted executor's cumulative frozen-base aggregate, never a commit delta."""
    if diff.get('plan_hash') != plan.plan_hash:
        return _receipt(plan, 'plan_changed')
    files = diff.get('files')
    counts = [diff.get(k) for k in ('production_added', 'production_deleted', 'tracked_files')]
    if (not isinstance(files, list) or not files or not all(_path(p) for p in files)
            or len(files) != len(set(files)) or any(type(v) is not int or v < 0 for v in counts)
            or counts[2] != len(files)):
        return _receipt(plan, 'invalid_diff')
    if _protected(files, policy):
        return _receipt(plan, 'user_decision')
    if not set(files).issubset(plan.files):
        return _receipt(plan, 'undeclared_scope')
    if counts[2] > policy.hard_tracked_files or counts[0] + counts[1] > policy.hard_production_lines:
        return _receipt(plan, 'hard_scope_limit')
    if (counts[0] + counts[1] > policy.soft_production_lines or counts[2] > policy.soft_production_files) and not plan.reason:
        return _receipt(plan, 'smaller_slice_or_reason')
    return _receipt(plan)


def comparison_valid(plan: Plan, evidence: Record) -> bool:
    return (evidence.get('plan_hash') == plan.plan_hash and evidence.get('baseline') == plan.baseline
            and evidence.get('config_hash') == plan.baseline_config_hash
            and evidence.get('evidence_domain', 'online') == plan.evidence_domain)
