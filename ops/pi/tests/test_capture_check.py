"""Trusted checks inspect untrusted transformed bytes; never import candidate."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import pytest


def module():
    assert (Path(__file__).parents[1] / 'capture_check.py').is_file(), 'fixed capture checker missing'
    return importlib.import_module('ops.pi.capture_check')


def fit_cases():
    return [dict(case_id=name, split='holdout' if name=='holdout' else 'development',
        input={'response':{'content':json.dumps({'text':name+'x'*40}), 'tool_calls':[]},
               'messages':[{'role':'user','content':'synthetic-only'}]})
        for name in ('ascii','utf8','escaping','mixed','large_json','holdout')]


def test_host_oracle_rejects_child_pass_claim_and_missing_ids():
    m = module(); cases = m.capture_cases({'cases':fit_cases()})
    assert len(cases) > 20
    report = m.inspect_output(cases, b'{"passed":true}')
    assert report['passed'] is False and report['reason'] == 'invalid_child_output'


def test_root_disclosed_holdout_schema_is_preserved_and_normalized():
    m=module(); fixture={'cases':fit_cases()}; fixture['cases'][-1]['split']='disclosed_holdout'
    cases=m.capture_cases(fixture)
    assert next(c for c in cases if c['id']=='holdout')['split']=='holdout'
    assert fixture['cases'][-1]['split']=='disclosed_holdout'


def test_exact_case_oracle_redaction_caps_mutation_and_prefix():
    m = module()
    case = dict(id='ascii', method='capture_detail', input=fit_cases()[0]['input'], expected=fit_cases()[0]['input']['response']['content'], kind='fit', split='development')
    clean = deepcopy(case['input']); clean['_capture'] = {'truncated':False,'redacted':False,'scope':'telemetry_only'}
    row = {'id':'ascii','result':clean,'input_after':case['input']}
    assert m.inspect_output([case], json.dumps({'rows':[row]}).encode())['passed'] is True
    for fault in ('short','secret','cap','mutation','duplicate'):
        bad = deepcopy(row)
        if fault == 'short': bad['result']['response']['content'] = 'x[TRUNCATED]'
        if fault == 'secret': bad['result']['response']['content'] = 'Bearer GUARD_BEARER_123'
        if fault == 'cap': bad['result']['extra'] = 'x'*65536
        if fault == 'mutation': bad['input_after']['messages'] = []
        rows = [bad, bad] if fault == 'duplicate' else [bad]
        assert m.inspect_output([case], json.dumps({'rows':rows}).encode())['passed'] is False
    assert m.string_expected('x'*16001, 65536) == 'x'*16000+'[TRUNCATED]'
    # Each supplementary codepoint costs 12 escaped bytes, plus quotes and marker.
    assert m.string_expected('\U0001f642'*100, 640) == '\U0001f642'*4+'[TRUNCATED]'


def test_fixed_check_requires_actual_envelope_before_calling_runner(tmp_path):
    m = module(); source = tmp_path/'source.py'; source.write_text('do not execute')
    checker = m.FixedCaptureCheck(source=source, cases=[], harness_sha256='b'*64,
        source_sha256='a'*64, acceptance=None,
        runner=lambda _:pytest.fail('unaccepted runner executed'))
    result = checker(dict(candidate_hash='c'*64,plan_hash='d'*64,base='base',candidate_id='candidate',generation=1,check_id='unit'))
    assert result.status == 'blocked'


def test_pairing_executor_requires_independently_verified_evidence():
    m = module()
    request = dict(source_hash='a'*64, config={}, messages=[], case={'id':'ascii'})
    execute = m.paired_executor({'a'*64:{'verified':False,'case_results':{}}})
    with pytest.raises(ValueError): execute(request)


def test_pairing_keeps_c16_contract_and_independent_severe_veto():
    m=module()
    from ops.pi.evaluate import digest, freeze_pairing
    from ops.pi.tests.test_plans import candidate
    config=dict(model='deterministic',protocol='none',pricing_id='d'*64,budget_scope_id='local-trial-1',
                temperature=0,max_tokens=0,base_url='none')
    before=dict(id='baseline',source_hash='a'*64,config=config,prompt='fixed byte objective')
    after=dict(id='candidate',source_hash='b'*64,config=config,prompt='fixed byte objective')
    cases=[dict(id=r['case_id'],group_id=r['case_id'],source_family=r['case_id'],account_group='synthetic',
        project_id='synthetic-'+r['case_id'],source_kind='synthetic',split=r['split'],label_status='missing',
        holdout_disclosure='local_public_holdout',input=r['input']) for r in fit_cases()]
    plan=candidate(baseline='baseline',baseline_config_hash=digest(config),metric='trace_fidelity',
        guard_metrics=('redaction','encoded_caps','input_immutability'),sample_floor=5,evidence_domain='synthetic')
    frozen=freeze_pairing(before,after,cases,plan,changed_factor='source',rubric={'version':'capture-bytes-v1'})
    reports={s:{'verified':True,'passed':True,'guards_clear':True,'output_sha256':s,
        'case_results':{r['id']:dict(trace_fidelity=int(s=='b'*64),redaction=1,encoded_caps=1,input_immutability=1) for r in cases}}
        for s in ('a'*64,'b'*64)}
    assert hasattr(m,'run_capture_pairing'), 'C16 capture pairing integration missing'
    result=m.run_capture_pairing(before,after,cases,frozen,reports)
    assert result['pairing']['mechanism']['status']=='improved'
    assert result['pairing']['real_model_calls']==0 and result['objective_passed'] is True
    reports['b'*64]['guards_clear']=False
    assert m.run_capture_pairing(before,after,cases,frozen,reports)['objective_passed'] is False


@pytest.mark.parametrize('fault',['ok','source_changed','runtime_hash','envelope','foreign_alias','unbound_snapshot','no_cleanup','leak'])
def test_actual_checker_requires_bound_runtime_and_independent_oracle(tmp_path,fault):
    from datetime import datetime,timedelta,timezone
    from hashlib import sha256
    from ops.pi.contracts import Receipt
    from ops.pi.tools import digest
    from ops.pi.trial_runtime import NEGATIVE_PROOFS
    m=module(); source=tmp_path/'frozen.py'; source.write_bytes(b'never imported by trusted host')
    source_hash=sha256(source.read_bytes()).hexdigest()
    case=dict(id='small',kind='string',method='capture',input='safe',expected='safe',max_bytes=18000)
    binding=dict(source_sha256=source_hash,harness_sha256='b'*64,cases_sha256=digest([case]))
    acceptance=dict(purpose='checker',verified=True,mode='ACTUAL',uid=65533,gid=65533,
        limits={'memory_mib':128,'cpu_percent':50,'swap_bytes':0,'no_new_privileges':True,'capabilities':[],
                'tasks':16,'runtime_seconds':30},negative_proofs={k:True for k in NEGATIVE_PROOFS},
        proof_sha256='e'*64,envelope_sha256='f'*64,binding=binding,
        expires_at=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat())
    if fault=='foreign_alias': acceptance['negative_proofs']['foreign_native_aliases_denied']=False
    snapshot=dict(candidate_hash='c'*64,plan_hash='d'*64,base='base',candidate_id='candidate',generation=1,check_id='unit')
    def runner(request):
        raw=json.dumps({'rows':[{'id':'small','input_after':'safe','result':{
            'data':'GUARD_KEY_123' if fault=='leak' else 'safe','truncated':False,'redacted':False}}]}).encode()
        evidence=dict(verified=True,mode='ACTUAL',binding=binding,snapshot=snapshot,envelope_sha256='f'*64,
            returncode=0,tree_empty=True,timed_out=False,oom_kill=0,stdout_sha256=sha256(raw).hexdigest())
        if fault=='source_changed':source.write_bytes(b'changed')
        if fault=='runtime_hash':evidence['stdout_sha256']='0'*64
        if fault=='envelope':evidence['envelope_sha256']='0'*64
        if fault=='unbound_snapshot':evidence['snapshot']={}
        if fault=='no_cleanup':evidence['tree_empty']=False
        return raw,Receipt('root-checker:1','done',evidence)
    checker=m.FixedCaptureCheck(source=source,cases=[case],source_sha256=source_hash,harness_sha256='b'*64,
                                acceptance=acceptance,runner=runner)
    result=checker(snapshot)
    assert (result.status=='done') is (fault=='ok')
