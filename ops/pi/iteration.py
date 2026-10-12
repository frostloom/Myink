"""Durable finite administrator dispatch; all external authority is host supplied.

This module never executes commands, enables servers, creates budgets or retries
pending actions. A new evidence/identity revision is linked to the old record.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import re

from .budget import totals
from .contracts import Receipt
from .ledger import _json
from .tools import digest

STAGES = ('observe','baseline','pre','analysis','plan','review','develop','verify',
          'git','build','release','post','open','compare')


def _records(ledger, kind, experiment):
    with ledger.transaction() as db:
        rows = [ledger._record(row) for row in db.execute(
            'SELECT * FROM operations WHERE kind=? ORDER BY rowid', (kind,))]
    return [r for r in rows if r['payload'].get('experiment_id') == experiment]


def _receipt(row):
    return Receipt(row['operation_id'], row['status'], row['evidence'] or {})


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
        raise ValueError('bounded durable identity required')
    return value


def _identity(value):
    if (not isinstance(value, dict) or set(value) != {'main','source','config','owner','generation','deployment_id'}
            or type(value['generation']) is not int or value['generation'] < 1
            or any(not isinstance(value[k], str) or not value[k] for k in value if k != 'generation')):
        raise ValueError('complete reality identity required')
    return deepcopy(value)


def _claim_key(payload):
    # Routing labels are not new evidence. Mode remains bound so a simulated
    # outcome can never be reused as proof of an actual execution.
    return digest({key:payload[key] for key in
                   ('experiment_id','identity','mode','hypothesis','evidence_hash')})


def _run_action(ledger, context, callback):
    operation = context['operation_id']
    # Claim and persist in one transaction. A get/intent pair permits two
    # controllers to observe absence and both invoke the same side effect.
    with ledger.transaction() as db:
        old=ledger._record(db.execute('SELECT * FROM operations WHERE operation_id=?',(operation,)).fetchone())
        if old:
            if old['kind']!='iteration_stage' or old['payload']!=context:
                raise ValueError('stage identity collision')
            return (_receipt(old) if old['status'] != 'pending' else
                    Receipt(operation, 'uncertain', {'reason':'pending_requires_reconciliation'}))
        db.execute("INSERT INTO operations VALUES (?,'iteration_stage',?,'pending',NULL,1)",(operation,_json(context)))
        db.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',
            ('intent',_json(dict(operation_id=operation,kind='iteration_stage',payload=context,schema_version=1))))
    try:
        receipt = callback(deepcopy(context)) if callable(callback) else None
        if (not isinstance(receipt, Receipt) or receipt.operation_id != operation
                or receipt.status not in ('done','failed','blocked','uncertain')):
            receipt = Receipt(operation, 'uncertain', {'reason':'unbound_or_missing_adapter_receipt'})
        elif receipt.status == 'done' and (receipt.evidence.get('verified') is not True
                or receipt.evidence.get('binding') != context['input_hash']
                or receipt.evidence.get('mode') != context['mode']):
            receipt = Receipt(operation, 'blocked', {'reason':'unverified_adapter_receipt', 'adapter':asdict(receipt)})
    except Exception as error:
        receipt = Receipt(operation, 'uncertain', {'reason':'adapter_outcome_unknown','error_class':type(error).__name__})
    ledger.finish(receipt)
    return receipt


def _acceptance(ledger, operation, identity, now, purpose):
    row = ledger.get(operation) if isinstance(operation, str) else None
    try:
        e = row['evidence']
        return (row['kind'] == 'runtime_acceptance' and row['status'] == 'done'
            and e['verified'] is True and e['mode'] == 'ACTUAL' and e['purpose'] == purpose
            and e['identity'] == identity and len(e['proof_sha256']) == 64
            and datetime.fromisoformat(e['expires_at']) > now)
    except (KeyError, TypeError, ValueError):
        return False


def run_iteration(ledger, experiment_id, now, services):
    """Run a finite revision using host-created adapters, not scenario commands.

An adapter receives the durable operation ID, identity and input binding. It
must retain its real primitive receipt in evidence. Uncertain actions remain
unreplayed; reconciliation is a separately reviewed host operation.
"""
    _name(experiment_id)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError('aware clock required')
    mode = services.get('mode')
    if mode not in ('SIMULATED','ACTUAL'):
        raise ValueError('explicit execution mode required')
    identity = _identity(services['identity']())
    if mode == 'ACTUAL' and not _acceptance(ledger, services.get('runtime_acceptance'), identity, now, 'pi'):
        return Receipt('iteration:runtime-blocked', 'blocked', {'mode':mode,'released':False,
            'reason':'fresh_independent_runtime_acceptance_required','next_action':'accept_runtime'})
    run_id, slice_id = _name(services['run_id']), _name(services['slice_id'])
    frozen = dict(experiment_id=experiment_id, identity=identity, mode=mode,
        hypothesis=services['hypothesis'], evidence_hash=services['evidence_hash'], slice_id=slice_id,
        scenario=services.get('scenario'))
    fingerprint = digest(frozen)
    claim_key=_claim_key(frozen)
    # History lookup and claim creation are atomic even when two controllers
    # choose different slice/scenario routing for the same optimization.
    with ledger.transaction() as db:
        revisions=[ledger._record(row) for row in db.execute(
            "SELECT * FROM operations WHERE kind='iteration_revision' ORDER BY rowid")]
        revisions=[row for row in revisions if row['payload']['experiment_id']==experiment_id]
        latest=revisions[-1] if revisions else None
        # Derive legacy rows' key without changing any immutable old payload.
        matching=next((row for row in revisions if _claim_key(row['payload'])==claim_key),None)
        if matching:
            if matching['status']!='pending': return _receipt(matching)
            if matching['payload']['fingerprint']!=fingerprint:
                return Receipt(matching['operation_id'],'uncertain',dict(mode=mode,released=False,
                    next_action='reconcile',reason='existing_optimization_claim',claim_key=claim_key))
            payload,operation=matching['payload'],matching['operation_id']
        else:
            revision=len(revisions)+1
            operation=f'iteration:{experiment_id}:{run_id}:{slice_id}:{revision}:{fingerprint}'
            payload=dict(**frozen,run_id=run_id,fingerprint=fingerprint,claim_key=claim_key,revision=revision,
                parent_revision=latest['operation_id'] if latest else None,started_at=now.isoformat())
            db.execute("INSERT INTO operations VALUES (?,'iteration_revision',?,'pending',NULL,1)",(operation,_json(payload)))
            db.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',
                ('intent',_json(dict(operation_id=operation,kind='iteration_revision',payload=payload,schema_version=1))))
    receipts = []; changed = bool(latest and latest['payload']['identity'] != identity)
    def summary(status, **extra):
        count, used = totals(ledger, 'local-trial-1')
        evidence = dict(mode=mode, revision=payload['revision'], parent_revision=payload['parent_revision'],
            attribution='confounded' if changed else 'pending_measurement', stage_receipts=receipts,
            budget_scope_id='local-trial-1', counted_reservations=count, charged_or_reserved_microyuan=used,
            actual_http_attempts=None, released=False, semantic_quality='unknown', **extra)
        result = Receipt(operation, status, evidence)
        # A pending stage must first be reconciled; don't terminalize the parent.
        if status != 'uncertain': ledger.finish(result)
        ledger.append_event('iteration_summary', asdict(result))
        return result
    for stage in STAGES:
        current = _identity(services['identity']())
        if current != identity:
            changed = True
            return summary('blocked', next_action='rebaseline_review_retest', reason='reality_changed')
        inputs = dict(revision=operation, identity=identity, previous=receipts, stage=stage)
        input_hash = digest(inputs)
        context = dict(experiment_id=experiment_id, run_id=payload['run_id'], slice_id=slice_id,
            stage=stage, identity=identity, mode=mode, input_hash=input_hash,
            operation_id=f'{operation}:{stage}:{input_hash}')
        # B12's expired packet is not replaced by an injected successful receipt.
        if mode == 'ACTUAL' and stage in ('pre','build','release','post','open'):
            if not _acceptance(ledger, services.get('release_acceptance'), identity, now, 'build_release'):
                return summary('blocked', next_action='accept_build_release', reason='downstream_runtime_unaccepted')
        receipt = _run_action(ledger, context, services.get('stages', {}).get(stage))
        receipts.append(asdict(receipt))
        if receipt.status != 'done':
            if receipt.status == 'uncertain':
                return summary('uncertain', next_action='reconcile', reason='pending_or_uncertain_stage')
            current = _identity(services['identity']())
            changed |= current != identity
            if current != identity:
                recovery = Receipt(operation + ':recover', 'blocked', {'reason':'old_owner_recovery_denied'})
            else:
                recovery_input = digest(dict(revision=operation, failed=receipt.operation_id, identity=identity))
                recovery_context = dict(context, stage='recover', input_hash=recovery_input,
                    operation_id=operation + ':recover:' + recovery_input)
                recovery = _run_action(ledger, recovery_context, services.get('recover'))
            return summary(receipt.status, next_action='save_and_reconcile', recovery=asdict(recovery),
                           reason=receipt.evidence.get('reason','stage_failed'))
    result = receipts[-1]['evidence'].get('comparison')
    next_action='observe_next_window'
    if result in ('not_improved','regressed','insufficient_evidence','confounded'):
        followup=continue_experiment(ledger, experiment_id, dict(status=result,evidence_hash=digest(receipts)),
                                     parent_revision=operation)
        next_action=followup.evidence['next_action']
        stages=('recover','diagnose') if result=='regressed' else ('diagnose',) if result=='not_improved' else ()
        for action in stages:
            if _identity(services['identity']())!=identity:
                changed=True
                return summary('blocked',next_action='rebaseline_review_retest',reason='old_owner_recovery_denied')
            action_hash=digest(dict(parent=followup.operation_id,stage=action,identity=identity))
            callback=services.get('recover') if action=='recover' else services.get('stages',{}).get('diagnose')
            action_context=dict(context,stage=action,input_hash=action_hash,
                                operation_id=operation+':'+action+':'+action_hash)
            action_receipt=_run_action(ledger,action_context,callback)
            receipts.append(asdict(action_receipt))
            if action_receipt.status!='done':
                return summary(action_receipt.status,next_action='reconcile',reason='continuation_incomplete')
    return summary('done', next_action=next_action, simulated_release=mode == 'SIMULATED')


def continue_experiment(ledger, experiment_id, observations, *, parent_revision=None):
    """Link work to a bound revision, defaulting to latest for external callers."""
    _name(experiment_id)
    rows = _records(ledger, 'iteration_revision', experiment_id)
    if not rows: raise ValueError('known experiment required')
    parent = rows[-1] if parent_revision is None else next(
        (row for row in rows if row['operation_id'] == parent_revision), None)
    if parent is None: raise ValueError('parent revision must belong to this experiment')
    status = observations.get('status'); evidence = observations.get('evidence_hash')
    if (status not in ('improved','not_improved','regressed','insufficient_evidence','confounded')
            or not isinstance(evidence, str) or not re.fullmatch('[0-9a-f]{64}', evidence)):
        raise ValueError('frozen observation outcome required')
    payload = dict(experiment_id=experiment_id, parent_revision=parent['operation_id'],
                   observations=deepcopy(observations))
    operation = 'iteration-followup:' + digest(payload)
    old = ledger.get(operation)
    if old: return _receipt(old)
    ledger.intent(operation, 'iteration_followup', payload)
    next_action = ('extend_observation' if status == 'insufficient_evidence' else
        'rebaseline_review_retest' if status == 'confounded' else
        'diagnose' if status in ('not_improved','regressed') else 'observe_next_window')
    receipt = Receipt(operation, 'done', dict(parent_experiment_id=experiment_id,
        parent_revision=parent['operation_id'], reason=status, next_action=next_action,
        repeat_hypothesis_allowed=evidence != parent['payload']['evidence_hash'],
        evidence_hash=evidence, recovery_required=status == 'regressed', released=False))
    ledger.finish(receipt)
    return receipt


def simulate_trial(ledger, scenario, experiment_id, now):
    """Finite offline failure injection; never calls Pi, Git or a service."""
    rows=json.loads(Path(__file__).with_name('lab').joinpath('scenarios.json').read_text(encoding='utf-8'))
    if scenario not in rows: raise ValueError('unknown frozen scenario')
    data=rows[scenario]
    identity=dict(main='a'*40,source='b'*64,config='c'*64,owner='pi',generation=1,deployment_id='simulated-1')
    def action(context):
        if context['stage']==data.get('fail_stage'):
            return Receipt(context['operation_id'],'blocked',{'reason':'budget_exhausted'})
        return Receipt(context['operation_id'],'done',dict(verified=True,mode='SIMULATED',
            binding=context['input_hash'],comparison=data['comparison'],released=False,
            simulated_action=context['stage']))
    services=dict(mode='SIMULATED',identity=lambda:deepcopy(identity),scenario=scenario,
        hypothesis='cleaned capture byte fidelity',evidence_hash=digest(data),
        run_id='simulated-day',slice_id='capture',stages={s:action for s in (*STAGES,'diagnose')},recover=action)
    return run_iteration(ledger,experiment_id,now,services)


def resume_simulated_trial(ledger, experiment_id):
    records=_records(ledger,'iteration_revision',experiment_id)
    if not records or records[-1]['payload']['mode']!='SIMULATED':
        raise ValueError('live reconciliation requires the trusted host runtime')
    row=records[-1]
    return simulate_trial(ledger,row['payload']['scenario'],experiment_id,
                          datetime.fromisoformat(row['payload']['started_at']))
