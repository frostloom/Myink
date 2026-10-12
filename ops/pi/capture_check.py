"""Trusted byte oracle and fixed-check receipt boundary; never loads candidate code."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import time

from .contracts import Receipt
from .tool_proof import strict_json
from .tools import digest
from .trial_runtime import accepted_envelope

OUTPUT_CAP = 4 * 1024**2
FIXTURE_SHA256 = 'd073e3d0ceee233b58564002e12311f2d88b23e67632e249ba18d4ad262343d8'
CONTROLS = frozenset(('plan','plan_attempt','writing_mode','audit_verdict'))
SECRETS = ('GUARD_BEARER_123','GUARD_INLINE_123','GUARD_URL_123','sk-GUARDKEY123456789','GUARD_KEY_123')


def encoded(value):
    return json.dumps(value,ensure_ascii=True,allow_nan=False).encode('ascii')


def load_capture_fixture(path):
    raw=Path(path).read_bytes()
    if sha256(raw).hexdigest()!=FIXTURE_SHA256: raise ValueError('frozen fixture bytes changed')
    return strict_json(raw)


def string_expected(value, max_bytes):
    """Linear escaped-codepoint accounting, independent of candidate prefix search."""
    room=min(max_bytes,65536)-512-64
    if len(value)<=16000 and len(encoded(value))<=room: return value
    used=len(encoded('[TRUNCATED]')); prefix=[]
    for char in value[:16000]:
        cost=len(encoded(char))-2
        if used+cost>room: break
        prefix.append(char); used+=cost
    return ''.join(prefix)+'[TRUNCATED]'


def capture_cases(fixture):
    """Five frozen fit families + disclosed H, each with finite deterministic guards."""
    rows=deepcopy(fixture['cases'])
    for row in rows:
        if row['split']=='disclosed_holdout': row['split']='holdout'
    if len(rows)!=6 or sum(r['split']=='development' for r in rows)!=5 or sum(r['split']=='holdout' for r in rows)!=1:
        raise ValueError('five development families and one disclosed holdout required')
    cases=[]
    for row in rows:
        name=row['case_id']; source=deepcopy(row['input'])
        cases.append(dict(id=name,kind='fit',method='capture_detail',input=source,
            expected=source['response']['content'],split=row['split']))
        for suffix,text,cap in (('maxtext','x'*16001,65536),('supplementary','\U0001f642'*2000,18000),
                                ('boundary','a\u6c49\U0001f680"\n'*1000,18000),('surrogate','x\ud800y',18000)):
            cases.append(dict(id=name+'-'+suffix,kind='string',method='capture',input=text,max_bytes=cap,
                expected=string_expected(text,cap),split=row['split']))
        # Before/across/after the former 2901-character clipping boundary.
        for offset in (12,2885,3200):
            unsafe='Bearer GUARD_BEARER_123 | api_key=GUARD_INLINE_123 | postgres://alice:GUARD_URL_123@db/a | sk-GUARDKEY123456789'
            safe='[REDACTED] | api_key=[REDACTED] | postgres://[REDACTED]@db/a | [REDACTED]'
            raw='a'*offset+unsafe+'z'*30
            cases.append(dict(id=name+'-redaction-'+str(offset),kind='redaction',method='capture',input=raw,
                max_bytes=18000,expected=string_expected('a'*offset+safe+'z'*30,18000),split=row['split']))
    cases.extend([
        dict(id='secret-keys',kind='keys',method='capture',input={'auth_token':'GUARD_KEY_123',
             'sessionToken':'GUARD_KEY_123','password_hash':'GUARD_KEY_123','input_tokens':2,'output_tokens':3,
             'url':'https://example.com/a'},max_bytes=65536),
        dict(id='inherited-controls',kind='controls',method='capture_detail',input={
             'plan':'p'*70000,'plan_attempt':3,'writing_mode':'manual','audit_verdict':'v'*70000,
             'response':{'content':'kept','tool_calls':[]},'messages':['x'*16000]*80,
             'tool_trace':['y'*16000]*80,'_capture':{'truncated':True,'redacted':True}}),
        dict(id='cycle',kind='cycle',method='capture',input={},special='cycle',max_bytes=65536),
        dict(id='unknown',kind='unknown',method='capture',input=None,special='unknown',max_bytes=65536),
    ])
    if len({c['id'] for c in cases})!=len(cases): raise ValueError('duplicate frozen case')
    return cases


def child_request(cases):
    # Oracle answers and split labels remain outside the candidate interpreter.
    return {'cases':[{k:deepcopy(c[k]) for k in ('id','method','input','max_bytes','special') if k in c} for c in cases]}


def inspect_output(cases, raw):
    failures=[]; results={}; severe=[]
    try:
        if not isinstance(raw,bytes) or len(raw)>OUTPUT_CAP: raise ValueError('bounded output required')
        body=strict_json(raw)
        if not isinstance(body,dict) or set(body)!={'rows'} or not isinstance(body['rows'],list): raise ValueError('rows required')
        if len(body['rows'])!=len(cases) or [r.get('id') for r in body['rows']]!=[c['id'] for c in cases]:
            raise ValueError('exact ordered case set required')
        for case,row in zip(cases,body['rows']):
            if set(row)!={'id','result','input_after'}: raise ValueError('strict child row required')
            result=row['result']; kind=case['kind']; name=case['id']; guards=[]
            if not isinstance(result,dict): raise ValueError('capture object required')
            if case.get('special') is None and row['input_after']!=case['input']: guards.append('input_mutation')
            telemetry={k:v for k,v in result.items() if k not in CONTROLS}
            cap=case.get('max_bytes',65536)
            if len(encoded(telemetry))>min(cap,65536): guards.append('encoded_cap')
            if any(s in encoded(telemetry).decode('ascii') for s in SECRETS): guards.append('credential_leak')
            if case['method']=='capture_detail':
                content=(result.get('response') or {}).get('content') if isinstance(result.get('response'),dict) else None
                meta=result.get('_capture',{})
                if len(encoded(result.get('response')))>17488: guards.append('response_cap')
            else:
                content=result.get('data'); meta=result
                if len(encoded(content))>min(cap,65536)-512: guards.append('data_reserve')
            objective=True
            if kind in ('fit','string','redaction'):
                objective=type(content) is str and content==case['expected']
                expected_truncated=case['expected'].endswith('[TRUNCATED]')
                if kind!='fit' and meta.get('truncated') is not expected_truncated: guards.append('truncation_flag')
                if kind=='fit' and meta.get('truncated') is not False: objective=False
                if kind=='redaction' and meta.get('redacted') is not True: guards.append('redaction_flag')
            elif kind=='keys':
                expected={'auth_token':'[REDACTED]','sessionToken':'[REDACTED]','password_hash':'[REDACTED]',
                          'input_tokens':2,'output_tokens':3,'url':'https://example.com/a'}
                if content!=expected or meta.get('redacted') is not True: guards.append('key_redaction_or_public_value')
            elif kind=='controls':
                if any(result.get(k)!=case['input'][k] for k in CONTROLS): guards.append('lossless_controls')
                if not all(meta.get(k) is True for k in ('truncated','redacted')): guards.append('inherited_flags')
                if content!='kept': guards.append('response_lost_to_messages')
            elif kind=='unknown':
                if content!='[UNAVAILABLE]' or meta.get('truncated') is not True: guards.append('unknown_not_fail_closed')
            elif kind=='cycle':
                if meta.get('truncated') is not True or '[TRUNCATED]' not in encoded(content).decode('ascii'):
                    guards.append('cycle_not_bounded')
            if not objective: failures.append(name+':byte_fidelity')
            severe.extend(name+':'+g for g in guards)
            results[name]=dict(trace_fidelity=int(objective),redaction=int(not any('redact' in g or 'credential' in g for g in guards)),
                encoded_caps=int(not any('cap' in g or 'reserve' in g for g in guards)),input_immutability=int('input_mutation' not in guards))
        return dict(verified=True,passed=not failures and not severe,guards_clear=not severe,
            failures=failures,severe=severe,case_results=results,output_sha256=sha256(raw).hexdigest())
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,UnicodeError):
        return dict(verified=False,passed=False,guards_clear=False,reason='invalid_child_output',case_results={})


class FixedCaptureCheck:
    def __init__(self, *, source, cases, harness_sha256, source_sha256, acceptance, runner):
        self.source=Path(source); self.cases=deepcopy(cases); self.harness_hash=harness_sha256
        self.source_hash=source_sha256; self.acceptance=deepcopy(acceptance); self.runner=runner

    def __call__(self, snapshot):
        binding=dict(source_sha256=self.source_hash,harness_sha256=self.harness_hash,cases_sha256=digest(self.cases))
        operation='capture-check:'+digest(dict(snapshot=snapshot,**binding))
        evidence=dict(**snapshot,**binding,verified=False,mode='ACTUAL',result='blocked',semantic_quality='unknown')
        try:
            if (set(snapshot)!={'candidate_hash','plan_hash','base','candidate_id','generation','check_id'}
                    or snapshot['check_id']!='unit' or not self.cases
                    or not accepted_envelope(self.acceptance,'checker',binding=binding)):
                raise ValueError('fresh isolated checker acceptance required')
            if sha256(self.source.read_bytes()).hexdigest()!=self.source_hash: raise ValueError('source changed')
            deadline=time.monotonic()+30
            # Runner is a fixed host-created closure. Nothing here accepts shell/argv.
            raw, runtime = self.runner(dict(request=child_request(self.cases),binding=binding,
                snapshot=deepcopy(snapshot),deadline_monotonic=deadline,output_cap=OUTPUT_CAP))
            if (time.monotonic()>=deadline or not isinstance(runtime,Receipt) or runtime.status!='done'
                    or runtime.evidence.get('verified') is not True or runtime.evidence.get('mode')!='ACTUAL'
                    or runtime.evidence.get('binding')!=binding or runtime.evidence.get('snapshot')!=snapshot
                    or runtime.evidence.get('envelope_sha256')!=self.acceptance['envelope_sha256']
                    or runtime.evidence.get('returncode')!=0 or runtime.evidence.get('tree_empty') is not True
                    or runtime.evidence.get('timed_out') is not False or runtime.evidence.get('oom_kill')!=0
                    or runtime.evidence.get('stdout_sha256')!=sha256(raw).hexdigest()
                    or sha256(self.source.read_bytes()).hexdigest()!=self.source_hash):
                raise ValueError('source/exit/deadline/resource proof missing')
            report=inspect_output(self.cases,raw)
            evidence.update(report=report,runtime_operation_id=runtime.operation_id,verified=report['verified'])
            evidence['result']='passed' if report['passed'] else 'failed'
            return Receipt(operation,'done' if report['passed'] else 'blocked',evidence)
        except (ValueError,TypeError,KeyError,OSError,TimeoutError):
            return Receipt(operation,'blocked',{**evidence,'reason':'fixed_check_unverified'})


def paired_executor(reports):
    """Consume only host-verified checker reports; C16 owns pairing/comparison."""
    frozen=deepcopy(reports)
    def execute(request):
        record=frozen[request['source_hash']]
        if record.get('verified') is not True or not record.get('output_sha256'):
            raise ValueError('independently verified checker report required')
        values=record['case_results'][request['case']['id']]
        from .evaluate import digest as eval_digest
        return dict(execution='completed',actual_http_attempts=0,
            executed_messages_sha256=eval_digest(request['messages']),executed_config_sha256=eval_digest(request['config']),
            mechanism_measurements={k:dict(value=v,availability='measured',assessment_kind='deterministic',
                evidence_sha256=record['output_sha256']) for k,v in values.items()},semantic_quality='unknown',
            severe_guard_clear=record.get('guards_clear') is True)
    return execute


def run_capture_pairing(baseline, candidate, cases, frozen, reports):
    """C16 source-factor pairing plus the independent absolute guard veto.

    Freeze the exact candidate before collecting its disclosed holdout output.
    Reports are host-verified records; no candidate code executes in this process.
    """
    from .evaluate import run_paired
    if frozen.get('changed_factor')!='source': raise ValueError('pre-execution source-factor freeze required')
    bundle=run_paired(baseline,candidate,cases,frozen,paired_executor(reports))
    report=reports[candidate['source_hash']]
    veto=report.get('guards_clear') is not True
    return dict(pairing=bundle,severe_guard_veto=veto,
        objective_passed=not veto and report.get('passed') is True and bundle['mechanism']['status']=='improved',
        released=False,semantic_quality='unknown',holdout_disclosure='local_public_holdout')
