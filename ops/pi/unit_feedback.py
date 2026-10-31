"""Fixed, finite failure metadata; never send arbitrary trace/source/attribute text."""
import json
import re

REPORT_FIELDS = {'tests','cases','failures','errors','skipped','passed','failed_cases',
                 'error_cases','diagnostics','load_error'}
ERROR_TYPES = {'AssertionError','AttributeError','SyntaxError','IndentationError','NameError',
               'UnboundLocalError','TypeError','ValueError','ImportError','ModuleNotFoundError',
               'RuntimeError','KeyError','IndexError','ZeroDivisionError','NotImplementedError'}
# This host-owned allowlist is frozen with the controller. Unknown names carry no text.
ATTRIBUTES = {'content','statement','summary','project_id','source_chapter','confirm_status',
              'valid_from','valid_to','realm_order','realm_pos','status','unknown_attribute'}


def diagnostic(case, trace):
    last = trace.strip().splitlines()[-1] if trace.strip() else ''
    name = last.split(':',1)[0]
    category = name if name in ERROR_TYPES else 'RuntimeError'
    attribute = None
    if category == 'AttributeError':
        match = re.search(r"has no attribute '([A-Za-z_][A-Za-z0-9_]{0,63})'",last)
        value = match.group(1) if match else None
        attribute = value if value in ATTRIBUTES else 'unknown_attribute'
    return dict(case=case,category=category,attribute=attribute)


def _require(value):
    if not value:
        raise ValueError('invalid fixed unittest report')


def validate_report(raw,returncode,expected):
    _require(isinstance(raw,dict) and set(raw)==REPORT_FIELDS)
    _require(isinstance(expected,list) and 0<len(expected)<=1000
             and all(isinstance(v,str) and re.fullmatch(r'fixed_development_tests\.[A-Za-z0-9_.]{1,180}',v) for v in expected)
             and len(set(expected))==len(expected))
    _require(type(raw['passed']) is bool and type(raw['load_error']) is bool
             and type(returncode) is int and returncode in (0,1))
    for key in ('tests','failures','errors','skipped'):
        _require(type(raw[key]) is int and 0<=raw[key]<=1000)
    for key in ('cases','failed_cases','error_cases','diagnostics'):
        _require(isinstance(raw[key],list) and len(raw[key])<=1000)
    _require(raw['skipped']==0)
    for key in ('failed_cases','error_cases'):
        _require(all(isinstance(v,str) and v in expected for v in raw[key])
                 and len(raw[key])==len(set(raw[key])))
    # Multiple failures/errors for one case, class setup and subTest forms are
    # unsupported, not silently deduplicated into a misleading success report.
    _require(not set(raw['failed_cases']) & set(raw['error_cases']))
    _require(raw['failures']==len(raw['failed_cases']))
    if raw['load_error']:
        _require(raw['cases']==[] and raw['tests']==0 and raw['failures']==0
                 and raw['errors']==1 and raw['error_cases']==[] and len(raw['diagnostics'])==1)
        diag_cases=[None]
    else:
        _require(raw['cases']==expected and raw['tests']==len(expected)
                 and raw['errors']==len(raw['error_cases']))
        diag_cases=raw['error_cases']
    _require(len(raw['diagnostics'])==len(diag_cases))
    for row,case in zip(raw['diagnostics'],diag_cases):
        _require(isinstance(row,dict) and set(row)=={'case','category','attribute'}
                 and row['case']==case and isinstance(row['category'],str) and row['category'] in ERROR_TYPES)
        attr=row['attribute']
        _require(attr is None or isinstance(attr,str) and attr in ATTRIBUTES)
        _require((row['category']=='AttributeError') == (attr is not None))
    passed=not raw['load_error'] and raw['failures']==raw['errors']==0
    _require(raw['passed'] is passed and returncode==int(not passed))
    return raw


def project_feedback(result,snapshot,test_sha256,expected_cases):
    from .tools import digest
    e=result.evidence
    _require(isinstance(test_sha256,str) and re.fullmatch(r'[0-9a-f]{64}',test_sha256))
    _require(result.operation_id=='development-check:'+digest(snapshot) and result.status=='blocked'
             and isinstance(e,dict) and set(e)==set(snapshot)|{'result','verified','mode','test_sha256','report'}
             and all(type(e.get(k)) is type(v) and e.get(k)==v for k,v in snapshot.items())
             and e['verified'] is True and e['mode']=='ACTUAL' and e['result']=='failed'
             and e['test_sha256']==test_sha256 and snapshot.get('check_id')=='unit')
    raw=e['report']
    _require(isinstance(raw,dict) and not raw.get('passed',True)
             and len(json.dumps(e,ensure_ascii=True,allow_nan=False).encode())<=32768)
    validate_report(raw,1,expected_cases)
    failed=sorted(raw['failed_cases']+raw['error_cases'])
    _require(len(failed)<=128)
    return dict(check_feedback={**snapshot,'result':'failed','verified':True,'mode':'ACTUAL',
                'test_sha256':test_sha256,'failed_cases':failed,'diagnostics':raw['diagnostics'],
                'load_error':raw['load_error'],'remediation_codes':['fixed_unittest_failed']},
                check_operation_id=result.operation_id)
