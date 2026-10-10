"""Pure maintenance action selection. Trusted controller persists intents and receipts.

Observations describe desired work, never certify gates. Ledger provenance is the
controller boundary; independent review may be a separate model role.
"""
from datetime import datetime, timedelta, timezone

from .contracts import Record
from .ledger import Ledger
from .policy import Policy
from .budget import totals
from .plans import Plan

SHANGHAI = timezone(timedelta(hours=8), 'Asia/Shanghai')


def window_at(now: datetime) -> Record:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('clock must include timezone')
    local = now.astimezone(SHANGHAI)
    start = local.replace(hour=2, minute=0, second=0, microsecond=0)
    end = start.replace(hour=6)
    cutoff = start.replace(hour=5, minute=30)
    return dict(day=local.date().isoformat(), start=start.isoformat(), deadline=end.isoformat(),
                active=start <= local < end, allow_new_candidate=start <= local < cutoff,
                remaining_seconds=max(0, int((end - local).total_seconds())))


def next_action(ledger: Ledger | None, now: datetime, observations: Record, policy: Policy) -> Record:
    w = window_at(now)
    local = now.astimezone(SHANGHAI)
    prefix = 'maintenance:' + w['day'] + ':'

    def record(name):
        return ledger.get(prefix + name) if ledger is not None else None

    def verified(name):
        r = record(name)
        return bool(r and r['status'] == 'done' and r['evidence'].get('verified') is True)

    def action(kind, reason=None, deadline=None, target=None):
        phase = kind.split(':', 1)[0]
        bound = 600 if phase in ('pre_backup', 'post_backup', 'repair_backup') else 2700 if phase in ('test', 'build') else policy.timeout_seconds
        duration = bound
        if phase in ('analyze', 'develop'):
            plan = observations.get('plan')
            duration = observations.get('estimate_seconds', plan.time_estimate if isinstance(plan, Plan) else bound)
            if type(duration) is not int or duration <= 0:
                duration = bound
        end = min(local + timedelta(seconds=duration), datetime.fromisoformat(w['deadline']))
        return dict(schema_version=1, kind=kind, operation_id=prefix + kind + (':' + target if target else ''),
                    deadline=deadline or end.isoformat(), tool_timeout_seconds=bound, remaining_seconds=w['remaining_seconds'],
                    reason=reason, target=target, allow_new_candidate=w['allow_new_candidate'])

    def request(name, reason=None, operation_id=None, target=None):
        r = ledger.get(operation_id) if ledger is not None and operation_id else record(name)
        if r:
            if r['status'] == 'done' and r['evidence'].get('verified') is True:
                return action('wait', reason='already_complete')
            return action('reconcile', reason=reason, target=r['operation_id'])
        result = action(name, reason=reason, target=target)
        if operation_id:
            result['operation_id'] = operation_id
        result['kind'] = name.split(':', 1)[0]
        return result

    # Recovery and reporting do not consult the model budget.
    if observations.get('incident') is True:
        return request('recover_open')
    published = verified('publish')
    if ledger is not None:
        with ledger.transaction() as connection:
            rows = connection.execute('SELECT * FROM operations WHERE operation_id LIKE ?', (prefix + 'publish:%',)).fetchall()
        published = published or any(r['status'] == 'done' and ledger._decode(r['evidence']).get('verified') is True for r in rows)
    post_missing = published and not verified('post_backup')
    if local >= datetime.fromisoformat(w['deadline']):
        if post_missing and not verified('backup_pending'):
            return request('backup_pending')
        if not verified('open'):
            return request('recover_open' if record('open') else 'open')
        if observations.get('work_pending') is True and not verified('save_work'):
            return request('save_work')
        return request('report') if not verified('report') else action('wait')
    if local < datetime.fromisoformat(w['start']):
        if observations.get('work_pending') is True and not verified('save_work'):
            return request('save_work')
        return action('wait', deadline=w['start'])
    pre = record('pre_backup')
    if pre and pre['status'] in ('failed', 'blocked', 'uncertain'):
        return request('recover_open')
    if not w['allow_new_candidate']:
        if post_missing:
            return request('post_backup') if w['remaining_seconds'] >= 600 else request('backup_pending')
        if observations.get('work_pending') is True and not verified('save_work'):
            return request('save_work')
        return request('close') if not verified('close') else request('open')
    if observations.get('existing_tasks', 0) and not verified('pause_tasks'):
        drain_end = datetime.fromisoformat(w['start']) + timedelta(seconds=policy.grace_seconds)
        return action('drain', deadline=drain_end.isoformat()) if local < drain_end else request('pause_tasks')
    if not verified('pre_backup'):
        return request('pre_backup')
    if post_missing:
        return request('post_backup')
    phase = observations.get('phase', 'analyze')
    if phase not in ('analyze', 'develop', 'test', 'build', 'publish'):
        return request('report', reason='invalid_phase')
    if phase == 'publish':
        if published:
            return request('report', reason='daily_publish_limit')
        if ledger is not None:
            with ledger.transaction() as connection:
                gaps = connection.execute("SELECT operation_id FROM operations WHERE kind='backup_pending' AND status='done'").fetchall()
            for gap in gaps:
                repair_id = gap['operation_id'] + ':repair_backup'
                repair = ledger.get(repair_id)
                if not (repair and repair['status'] == 'done' and repair['evidence'].get('verified') is True):
                    return request('repair_backup', operation_id=repair_id, target=gap['operation_id'])
    attempts, spent = totals(ledger, 'local-trial-1') if ledger is not None else (0, 0)
    if observations.get('budget_exhausted') is True or attempts >= policy.max_attempts or spent >= policy.budget_microyuan:
        return request('report')
    if observations.get('target_met') is False:
        return request('diagnose')
    plan = observations.get('plan')
    if plan is not None and not isinstance(plan, Plan):
        return action('plan_gate', reason='invalid_plan')
    if plan is not None and observations.get('new_evidence') is False:
        return request('save_work')
    estimate = observations.get('estimate_seconds', plan.time_estimate if plan else policy.timeout_seconds)
    bound = 2700 if phase in ('test', 'build') else w['remaining_seconds']
    if type(estimate) is not int or estimate <= 0 or estimate > min(bound, w['remaining_seconds']):
        return request('save_work')
    if phase != 'analyze':
        if plan is None:
            return action('plan_gate', reason='missing_plan')
        digest = plan.plan_hash
        rules = record('plan_rules:' + digest)
        review = record('plan_review:' + digest)
        for r, source in ((rules, 'deterministic_rules'), (review, 'independent_review')):
            if not (r and r['status'] == 'done' and r['evidence'].get('verified') is True
                    and r['evidence'].get('plan_hash') == digest and r['evidence'].get('source') == source):
                return action('plan_gate', reason='missing_trusted_receipt', target=digest)
        if not review['evidence'].get('reviewer_id'):
            return action('plan_gate', reason='missing_independent_reviewer', target=digest)
        # Development, test, build and publish each require the previous durable phase.
        previous = {'test': 'develop', 'build': 'test', 'publish': 'build'}.get(phase)
        if previous and not verified(previous + ':' + digest):
            return action('plan_gate', reason='missing_previous_phase', target=previous)
        name = phase + ':' + digest
        if verified(name):
            return action('save_work', reason='phase_already_complete')
        return request(name)
    return request('analyze') if not verified('analyze') else request('save_work')
