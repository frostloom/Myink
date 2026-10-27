"""Frozen host authority for local development. Preflight performs no mutations."""
from dataclasses import fields
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import stat

from .budget import _effective_trial_limits, _scope_payload
from .container_runtime import verify_source
from .ledger import validate_connection
from .plans import Plan, validate_plan
from .policy import load_policy
from .provider_config import load_credentials

OWNER = 'local-development-controller'
FIELDS = set(('schema run_id root source_path source_sha256 runtime_path runtime_sha256 '
              'ledger_path ledger_sha256 policy_path policy_sha256 credential_path credential_sha256 '
              'plan_path plan_sha256 baseline_path baseline_sha256 review_path review_sha256 '
              'test_path test_sha256 test_cases docker endpoint daemon_id image_id checker_image_id '
              'max_requests max_tools deadline_seconds').split())


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON field')
            result[key] = value
        return result
    raw = Path(path).read_bytes()
    if len(raw) > 1048576:
        raise ValueError('JSON artifact too large')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def path(value, *, private=False):
    p = Path(value)
    if (not p.is_absolute() or '..' in p.parts or any(c in str(p) for c in ',\r\n\0')
            or any(q.is_symlink() for q in (p, *p.parents))):
        raise ValueError('absolute non-link path required')
    if private and (stat.S_IMODE(p.stat().st_mode) != 0o600
                    or stat.S_IMODE(p.parent.stat().st_mode) != 0o700):
        raise ValueError('private file and parent permissions required')
    return p


def file_hash(p):
    return sha256(Path(p).read_bytes()).hexdigest()


def tree_hash(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('closed source directory required')
    entries = {}
    total = 0
    for p in sorted(root.rglob('*')):
        mode = p.lstat().st_mode
        if p.is_symlink() or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError('source link or special file forbidden')
        if p.is_file():
            if p.stat().st_nlink != 1:
                raise ValueError('source hardlink forbidden')
            total += p.stat().st_size
            if len(entries) >= 10000 or total > 64*1024**2:
                raise ValueError('source size limit')
            entries[p.relative_to(root).as_posix()] = file_hash(p)
    if not entries:
        raise ValueError('empty source')
    return digest(entries)


def ledger_snapshot(p):
    p = Path(p)
    if not p.is_file():
        raise ValueError('existing ledger required')
    # Immutable prevents SQLite creating WAL/SHM sidecars during a dry-run.
    # Require a quiescent checkpointed file; never silently ignore live WAL rows.
    wal = p.with_name(p.name+'-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('checkpointed quiescent ledger required')
    before = file_hash(p)
    db = sqlite3.connect(p.absolute().as_uri()+'?mode=ro&immutable=1', uri=True, isolation_level=None, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        validate_connection(db)
        result = {table:[dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY '+order)]
                  for table, order in (('operations','operation_id'),('events','id'))}
        scope = db.execute('SELECT * FROM operations WHERE operation_id=?', ('model-scope:local-trial-1',)).fetchone()
        result['limits'] = _effective_trial_limits(db, _scope_payload(scope)) if scope is not None else None
        result['sha256'] = digest(result)
        if file_hash(p) != before or (wal.exists() and wal.stat().st_size):
            raise ValueError('ledger changed during read')
        return result
    finally:
        db.close()


def authorization_hash(config):
    return digest({k:v for k,v in config.items() if k not in ('review_path','review_sha256')})


def validate_review(review, config, plan_hash, base):
    expected = dict(source='independent_review', verified=True, result='approved',
                    authorization_sha256=authorization_hash(config), plan_hash=plan_hash, base=base,
                    candidate_id=config['run_id'], owner=OWNER, generation=1)
    if (not isinstance(review, dict) or any(type(review.get(k)) is not type(v) or review.get(k) != v for k,v in expected.items())
            or not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip()
            or review['reviewer'] in ('model', OWNER)):
        raise ValueError('independent review binding invalid')


def prepare(config_path):
    """Validate a complete independently reviewed execution contract."""
    return _prepare(config_path, review_required=True)


def prepare_template(config_path):
    """Read-only package check; no independent review or execution approval."""
    return _prepare(config_path, review_required=False)


def _prepare(config_path, *, review_required):
    """Validate without constructing Ledger, touching Docker or output root."""
    config_path = path(config_path, private=True)
    c = read_json(config_path)
    if not isinstance(c, dict) or set(c) != FIELDS or c['schema'] != 'pi-development-v1':
        raise ValueError('unsupported development config')
    if not isinstance(c['run_id'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', c['run_id']):
        raise ValueError('invalid run identity')
    for key, maximum in (('max_requests',100),('max_tools',256),('deadline_seconds',1800)):
        if type(c[key]) is not int or not 0 < c[key] <= maximum:
            raise ValueError('bounded development limits required')
    if c['max_tools'] < 12:
        raise ValueError('development completion RPC budget requires at least12')
    if c['max_requests'] < 7:
        raise ValueError('development completion model budget requires at least7 requests')
    for key in ('image_id','checker_image_id'):
        if not isinstance(c[key],str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',c[key]):
            raise ValueError('immutable image required')
    # Constructor validates local endpoint and identity without executing Docker.
    from .container_probe import ProbeHost
    import uuid
    ProbeHost(docker=path(c['docker']), endpoint=c['endpoint'], daemon_id=c['daemon_id'],
              image_id=c['image_id'], operation_id=str(uuid.uuid4()))
    root = path(c['root'])
    if root.exists() or not root.parent.is_dir() or stat.S_IMODE(root.parent.stat().st_mode) != 0o700:
        raise ValueError('new output root in private parent required')
    for key in ('source_path','runtime_path','ledger_path','policy_path','credential_path',
                'plan_path','baseline_path','review_path','test_path'):
        path(c[key], private=key not in ('source_path','runtime_path')
             and (key != 'review_path' or review_required))
        if root == Path(c[key]) or root in Path(c[key]).parents or Path(c[key]) in root.parents:
            raise ValueError('output and frozen inputs overlap')
    for name in ('policy','credential','plan','baseline','review','test'):
        if name == 'review' and not review_required:
            continue
        if file_hash(c[name+'_path']) != c[name+'_sha256']:
            raise ValueError(name+' artifact drift')
    source = Path(c['source_path'])
    if {p.name for p in source.iterdir()} != {'src'} or tree_hash(source) != c['source_sha256']:
        raise ValueError('source snapshot drift')
    provenance = verify_source(Path(c['runtime_path']), c['runtime_sha256'])
    ledger = ledger_snapshot(c['ledger_path'])
    if ledger['sha256'] != c['ledger_sha256']:
        raise ValueError('ledger checkpoint drift')
    policy = load_policy(Path(c['policy_path']))
    if policy.live_enabled or policy.server_daily_enabled or not policy.input_bound_calibrated:
        raise ValueError('closed calibrated policy required')
    limits = ledger['limits']
    if (limits is None or limits['max_attempts'] != policy.max_attempts
            or limits['budget_microyuan'] != policy.budget_microyuan):
        raise ValueError('policy and original scope approval mismatch')
    load_credentials(c['credential_path'], policy)
    raw_plan = read_json(c['plan_path'])
    if not isinstance(raw_plan,dict) or set(raw_plan) != {f.name for f in fields(Plan)}:
        raise ValueError('strict Plan required')
    for key in ('guard_metrics','files','slice_ids','change_types'):
        if not isinstance(raw_plan[key],list):
            raise ValueError('Plan arrays required')
        raw_plan[key] = tuple(raw_plan[key])
    plan = Plan(**raw_plan)
    baseline = read_json(c['baseline_path'])
    if (validate_plan(plan,baseline,policy).status != 'done' or plan.call_estimate > c['max_requests']
            or plan.time_estimate > c['deadline_seconds']):
        raise ValueError('approved Plan limits invalid')
    if any(not (source/f).is_file() for f in plan.files):
        raise ValueError('declared source missing')
    cases = c['test_cases']
    if (not isinstance(cases,list) or not cases or len(cases)>1000 or len(set(cases))!=len(cases)
            or any(not isinstance(v,str) or not re.fullmatch(r'fixed_development_tests\.[A-Za-z0-9_.]+',v) for v in cases)):
        raise ValueError('exact fixed unittest inventory required')
    from .source_locator import source_index
    source_index(source, plan.files, plan.behavior)
    review = None
    if review_required:
        review = read_json(c['review_path'])
        validate_review(review,c,plan.plan_hash,c['source_sha256'])
    return c, policy, plan, baseline, review, ledger, provenance


def check(config_path):
    c, *_ = prepare(config_path)
    return dict(ready=True, mode='read-only', authorization_sha256=authorization_hash(c),
                fixed_cases=len(c['test_cases']))
