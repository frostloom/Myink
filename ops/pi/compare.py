"""Deterministic evidence gates; cost reductions cannot prove writing quality."""
import math
from .contracts import Record
from .plans import Plan


def compare_windows(baseline: Record, candidate: Record, plan: Plan) -> Record:
    result = dict(status='insufficient_evidence', p95_conclusion=None, baseline=plan.baseline,
                  candidate=candidate.get('id'), config_hash=plan.baseline_config_hash,
                  plan_hash=plan.plan_hash, evidence_domain=plan.evidence_domain,
                  baseline_identity=baseline.get('identity'), candidate_identity=candidate.get('identity'))
    def finish(status, reason):
        return {**result, 'status': status, 'reason': reason}
    if baseline.get('id') != plan.baseline or baseline.get('config_hash') != plan.baseline_config_hash:
        return finish('confounded', 'frozen_baseline_mismatch')
    if any(s.get('confounders') for s in (baseline, candidate)):
        return finish('confounded', 'window_confounders')
    fields = ('config_hash', 'prompt_hash', 'rubric_hash', 'data_hash', 'schema_id', 'model_ids')
    for key in fields:
        if baseline.get(key) and candidate.get(key) and baseline[key] != candidate[key]:
            return finish('confounded', 'version_changed:' + key)
    bi, ci = baseline.get('identity') or {}, candidate.get('identity') or {}
    if bi != ci and ci.get('owner') != 'pi':
        return finish('confounded', 'manual_deployment')
    if any(not s.get(key) for s in (baseline, candidate) for key in fields) or not bi or not ci:
        return finish('insufficient_evidence', 'unknown_provenance')
    if any(s.get('availability') != 'measured' or s.get('evidence_domain') != plan.evidence_domain
           for s in (baseline, candidate)):
        return finish('insufficient_evidence', 'unknown_or_incompatible_domain')
    if plan.evidence_domain == 'synthetic':
        pairs = [s.get('paired_group_ids', []) for s in (baseline, candidate)]
        if any(not isinstance(p, list) or not all(isinstance(v, str) and v for v in p) for p in pairs):
            return finish('insufficient_evidence', 'invalid_pairs')
        if set(pairs[0]) != set(pairs[1]) or len(set(pairs[0])) < max(5, plan.sample_floor):
            return finish('insufficient_evidence', 'insufficient_matched_pairs')
    elif any(type(s.get('complete_tasks')) is not int or s['complete_tasks'] < max(20, plan.sample_floor)
             for s in (baseline, candidate)):
        return finish('insufficient_evidence', 'insufficient_complete_tasks')
    if 'p95' in plan.metric.lower() and any(type(s.get('tail_samples')) is not int or s['tail_samples'] < 100 for s in (baseline, candidate)):
        return finish('insufficient_evidence', 'insufficient_tail_samples')
    deltas = {}
    if plan.scope == 'writing_quality' and plan.metric != 'quality':
        return finish('insufficient_evidence', 'quality_requires_rubric_measurement')
    for metric in (plan.metric, *plan.guard_metrics):
        measures = [(s.get('measurements') or {}).get(metric, {}) for s in (baseline, candidate)]
        floor = max(plan.sample_floor, 5 if plan.evidence_domain == 'synthetic' else 20,
                    100 if 'p95' in metric.lower() else 0)
        if any(m.get('availability') != 'measured' or type(m.get('value')) not in (int, float)
               or not math.isfinite(m['value']) or m['value'] < 0
               or type(m.get('samples')) is not int or m['samples'] < floor for m in measures):
            return finish('insufficient_evidence', 'missing_measurement:' + metric)
        if measures[0].get('direction') not in ('higher', 'lower') or measures[0].get('direction') != measures[1].get('direction'):
            return finish('insufficient_evidence', 'unknown_direction:' + metric)
        before, after = (m['value'] for m in measures)
        sign = 1 if measures[0]['direction'] == 'higher' else -1
        # Zero baseline uses absolute change; never divide by zero or hide new failures.
        deltas[metric] = sign * (after - before) / (abs(before) if before else 1)
    result['deltas'] = deltas
    status = ('regressed' if any(v <= -plan.severe_regression for v in deltas.values()) else
              'improved' if deltas[plan.metric] >= plan.minimum_improvement else 'not_improved')
    if 'p95' in plan.metric.lower():
        result['p95_conclusion'] = status
    return finish(status, 'thresholds_applied')
