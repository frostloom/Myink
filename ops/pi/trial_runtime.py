"""Fixed host-composed C17 seams. No launcher, credentials or alternate budget."""
from datetime import datetime, timezone
from dataclasses import asdict
from hashlib import sha256
import json

from .budget import effective_limits_in_connection
from .contracts import Receipt
from .engine import AdministratorContext
from .ledger import Ledger, _json
from .plans import Plan
from .tools import PHASE_TOOLS, digest

FENCE_ID = 'c17-phase-admission:local-trial-1'
ALLOCATIONS = {'analysis':15,'develop':45,'experiment':30,'reserve':10}
NEGATIVE_PROOFS = ('source_write_denied','harness_write_denied','foreign_files_denied',
    'foreign_native_aliases_denied','ledger_credentials_sessions_denied','host_sockets_denied',
    'network_denied','timeout_tree_cleanup','output_overflow_denied','resource_limits_verified')


def ensure_phase_fence(ledger):
    with ledger.transaction() as db:
        row = db.execute('SELECT * FROM operations WHERE operation_id=?',(FENCE_ID,)).fetchone()
        if row:
            data = Ledger._decode(row['payload'])
            if row['kind'] != 'phase-fence' or data.get('allocations') != ALLOCATIONS or data.get('scope_id') != 'local-trial-1':
                raise ValueError('immutable phase fence mismatch')
            return data
        inherited = [r['operation_id'] for r in db.execute("SELECT * FROM operations WHERE kind='model-attempt' ORDER BY rowid")
                     if Ledger._decode(r['payload'])['scope_id']=='local-trial-1']
        if len(inherited)>15: raise ValueError('inherited analysis allowance exhausted')
        data = dict(scope_id='local-trial-1', allocations=ALLOCATIONS, inherited_analysis_attempts=inherited)
        db.execute("INSERT INTO operations VALUES (?,'phase-fence',?,'pending',NULL,1)",(FENCE_ID,_json(data)))
        return data


def phase_transport(ledger, phase, transport):
    """Wrap the real transport AFTER canonical reserve; zero retries.

    The host creates this wrapper before any new reservation and calls sequentially.
    Admission counts reservations; a denied transport is not evidence of HTTP.
    Existing preview fencing is deliberately not reused or altered.
    """
    category = {'plan':'analysis','analysis':'analysis','diagnose':'analysis',
                'develop':'develop','experiment':'experiment','reserve':'reserve'}.get(phase)
    if category is None: raise ValueError('fixed phase required')
    fence = ensure_phase_fence(ledger)
    def send(body, timeout):
        with ledger.transaction() as db:
            admissions = [ledger._record(row) for row in db.execute("SELECT * FROM operations WHERE kind='phase-admission'")]
            if any(row['status']=='pending' for row in admissions):
                raise ValueError('unsettled phase transport; reconcile before continuing')
            assigned = set(fence['inherited_analysis_attempts']) | {r['payload']['attempt_id'] for r in admissions}
            attempts = [ledger._record(row) for row in db.execute("SELECT * FROM operations WHERE kind='model-attempt' ORDER BY rowid")]
            outstanding = [r for r in attempts if r['payload']['scope_id']=='local-trial-1' and r['operation_id'] not in assigned]
            if len(outstanding)!=1 or outstanding[0]['status']!='pending':
                raise ValueError('exactly one fresh canonical reservation required')
            attempt = outstanding[0]
            allocations = effective_limits_in_connection(db)['phase_allocations']
            count = sum(r['payload']['category']==category for r in admissions)
            if category=='analysis': count += len(fence['inherited_analysis_attempts'])
            payload = dict(attempt_id=attempt['operation_id'], category=category, phase=phase, body_sha256=digest(body))
            operation = 'phase-admission:' + attempt['operation_id']
            db.execute("INSERT INTO operations VALUES (?,'phase-admission',?,'pending',NULL,1)",(operation,_json(payload)))
        if allocations is not None and count >= allocations[category]:
            ledger.finish(Receipt(operation,'blocked',{'transport_invoked':False,'reason':'phase_allowance_exhausted'}))
            raise ValueError('phase allowance exhausted; reservation remains counted')
        try:
            response = transport(body, timeout)
        except Exception:
            ledger.finish(Receipt(operation,'uncertain',{'transport_invoked':True,'actual_http_attempts':None}))
            raise
        ledger.finish(Receipt(operation,'done',{'transport_invoked':True,'actual_http_attempts':None}))
        return response
    return send


def accepted_envelope(acceptance, purpose, *, now=None, binding=None):
    """Validate a host-created proof record; this is not a sandbox attestation.

    Root must own the acceptance file/ledger and independently measure each proof.
    Model text or a candidate-generated record cannot be passed as acceptance.
    """
    now = now or datetime.now(timezone.utc)
    try:
        expected_uid = 65533 if purpose=='checker' else 65534
        limits = {'memory_mib':128 if purpose=='checker' else 384,'cpu_percent':50,'swap_bytes':0,
                  'no_new_privileges':True,'capabilities':[]}
        if purpose=='checker': limits.update(tasks=16,runtime_seconds=30)
        return (acceptance['purpose']==purpose and acceptance['mode']=='ACTUAL' and acceptance['verified'] is True
            and type(acceptance['uid']) is int and acceptance['uid']==expected_uid and acceptance['gid']==expected_uid
            and acceptance['limits']==limits and datetime.fromisoformat(acceptance['expires_at'])>now
            and all(acceptance['negative_proofs'].get(k) is True for k in NEGATIVE_PROOFS)
            and all(isinstance(acceptance[k],str) and len(acceptance[k])==64
                    and all(c in '0123456789abcdef' for c in acceptance[k]) for k in ('proof_sha256','envelope_sha256'))
            and all(acceptance['binding'].get(k)==v for k,v in (binding or {}).items()))
    except (KeyError, TypeError, ValueError):
        return False


def run_engine_phase(*, engine, phase, prompt, session, plan_id, deadline, acceptance):
    binding = dict(phase=phase,session_path=str(session.session_path),config_hash=session.config_hash) if session else {}
    if not session or not accepted_envelope(acceptance,'pi',binding=binding):
        return Receipt('phase:unaccepted','blocked',{'reason':'fresh_host_envelope_required','verified':False})
    if phase not in PHASE_TOOLS or session.resume or deadline.tzinfo is None:
        raise ValueError('fresh fixed phase required')
    context = AdministratorContext('local-trial-1',plan_id,'local-trial-1','frozen evidence index')
    result = engine.run_phase(phase=phase,prompt=prompt,context=context,session=session,deadline=deadline,
                              tools=list(PHASE_TOOLS[phase]))
    # PiAdapter's valid receipt still needs independent stopped-session/root checks.
    return Receipt(result.operation_id,result.status,{**result.evidence,'requires_root_reconciliation':True,
        'envelope_sha256':acceptance['envelope_sha256']})


def verify_stopped_phase(broker, receipt, session_bytes, transcript_bytes, *, stopped, source_before, source_after):
    """Root reads frozen files after cgroup exit; authenticate each actual tool row."""
    try:
        e=receipt.evidence
        if (receipt.status!='done' or stopped.get('verified') is not True or stopped.get('mode')!='ACTUAL'
                or stopped.get('pid')!=e.get('owned_pid') or stopped.get('tree_empty') is not True
                or stopped.get('returncode')!=0 or not e.get('session_valid') or not e.get('clear_abort_acknowledged')
                or sha256(session_bytes).hexdigest()!=e.get('session_sha256') or len(session_bytes)>16*1024**2
                or len(transcript_bytes)>16*1024**2):
            raise ValueError('stopped session evidence missing')
        records=[json.loads(line) for line in session_bytes.splitlines()]
        calls={}; results={}; result_positions={}
        for position,record in enumerate(records):
            message=record.get('message',{})
            if message.get('role')=='assistant':
                for block in message.get('content',[]):
                    if block.get('type')=='toolCall':
                        if block['id'] in calls: raise ValueError('duplicate call')
                        calls[block['id']]=block
            if message.get('role')=='toolResult':
                if message['toolCallId'] in results: raise ValueError('duplicate result')
                results[message['toolCallId']]=message
                result_positions[message['toolCallId']]=position
        if set(calls)!=set(results) or sorted(calls)!=e.get('verified_tool_calls'): raise ValueError('incomplete tools')
        successful=set(); successful_rows=[]
        for call_id, call in calls.items():
            result=results[call_id]; actual=result['details']['receipt']
            if not broker.lookup(call_id,call['name'],call['arguments'],actual): raise ValueError('foreign tool evidence')
            if actual['status']=='done':
                successful.add(call['name'])
                successful_rows.append((result_positions[call_id],call,actual))
        required={'propose_plan'} if broker.capability.phase=='plan' else {'apply_patch','run_check'} if broker.capability.phase=='develop' else set()
        if not required<=successful or broker.capability.phase=='develop' and source_before==source_after:
            raise ValueError('missing actual plan/patch/check')
        proposed_plan=None
        if broker.capability.phase=='plan':
            proposals=[(call,results[call_id]['details']['receipt']) for call_id,call in calls.items() if call['name']=='propose_plan']
            if len(proposals)!=1:raise ValueError('exactly one current authenticated proposal required')
            call,actual=proposals[0]
            data=dict(call['arguments']['plan'])
            for key in ('files','slice_ids','guard_metrics','change_types'):
                if key in data:
                    if not isinstance(data[key],list):raise ValueError('Plan arrays required')
                    data[key]=tuple(data[key])
            plan=Plan(**data)
            evidence=actual['evidence'];rules=evidence['rules']
            if (actual['status']!='done' or rules['status']!='done' or rules['evidence'].get('verified') is not True
                    or evidence.get('plan_hash')!=plan.plan_hash or rules['evidence'].get('plan_hash')!=plan.plan_hash
                    or digest(evidence['plan'])!=digest(asdict(plan))):
                raise ValueError('verified current proposal and computed hash required')
            proposed_plan=dict(operation_id=actual['operation_id'],plan=evidence['plan'],plan_hash=plan.plan_hash)
        final_check=None
        if broker.capability.phase=='develop':
            cap=broker.capability
            current_hash=broker.candidate_hash()
            expected=dict(check_id='unit',candidate_hash=current_hash,plan_hash=cap.plan.plan_hash,
                          base=cap.base,candidate_id=cap.candidate_id,generation=cap.generation,
                          source_sha256=source_after,result='passed',verified=True,mode='ACTUAL')
            last_patch=max(position for position,call,_ in successful_rows if call['name']=='apply_patch')
            for position,call,actual in successful_rows:
                check=actual['evidence'].get('check')
                if (call['name']=='run_check' and position>last_patch and isinstance(check,dict)
                        and call['arguments']==dict(check_id='unit',candidate_hash=current_hash,plan_hash=cap.plan.plan_hash)
                        and all(check.get(key)==value for key,value in expected.items())):
                    final_check=actual['operation_id']
            if final_check is None:
                raise ValueError('successful unit check must cover final candidate after its last patch')
        result=dict(verified=True,mode='ACTUAL',session_sha256=sha256(session_bytes).hexdigest(),
            transcript_sha256=sha256(transcript_bytes).hexdigest(),source_before=source_before,source_after=source_after,
            verified_tool_calls=sorted(calls),required_tools=sorted(required),final_check_operation_id=final_check)
        if proposed_plan is not None:result['proposed_plan']=proposed_plan
        return result
    except (ValueError,KeyError,TypeError,AttributeError):
        return dict(verified=False,reason='root_phase_reconciliation_failed')
