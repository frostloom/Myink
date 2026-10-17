"""Fixed full regression gates with exact source/cases, structured results and exit proof."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree
import uuid

from .build import HeavyAction, admission, bound, checked_call, outcome, same_source
from .contracts import Receipt

# Never dispatch scripts/ci-local.sh as trusted root or accept candidate-selected gates.
CHECKS = (
    ('python-compile', ('python', '-m', 'compileall', '-q', 'src', 'tests'), '.', False),
    ('ops-compile', ('python', '-m', 'compileall', '-q', 'ops/pi'), '.', False),
    ('catalog', ('python', 'scripts/evaluate.py', 'validate'), '.', False),
    ('init', ('myink', 'init', '--seed'), '.', False),
    ('contract-export', ('myink', 'contract', 'export'), '.', False),
    ('contract-diff', ('trusted-contract-diff', 'spec/api-openapi.json'), '.', False),
    ('python-tests', ('python', '-m', 'pytest', 'tests/', '-q', '-m', 'not pi_lab and not pi_live',
                      '-p', 'no:cacheprovider', '--junitxml=/artifacts/python-tests.xml'), '.', True),
    ('ops-tests', ('python', '-m', 'pytest', 'ops/pi/tests/', '-q', '-m', 'not pi_lab and not pi_live',
                   '-p', 'no:cacheprovider', '--junitxml=/artifacts/ops-tests.xml'), '.', True),
    ('frontend-install', ('npm', 'ci', '--offline'), 'web', False),
    ('frontend-lint', ('npm', 'run', 'lint'), 'web', False),
    ('frontend-tests', ('npm', 'test', '--', '--maxWorkers=1', '--no-file-parallelism',
                        '--reporter=default', '--reporter=junit', '--outputFile=/artifacts/frontend-tests.xml'), 'web', True),
    ('frontend-build', ('npm', 'run', 'build'), 'web', False),
)


def parse_junit(path, required_cases):
    raw = Path(path).read_bytes()
    if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw or len(raw) > 32 * 1024**2:
        raise ValueError('unsafe_junit')
    root = ElementTree.fromstring(raw)
    cases = {}
    for case in root.iter('testcase'):
        name = case.get('classname', '') + '.' + case.get('name', '')
        if name in cases or not case.get('name'):
            raise ValueError('duplicate_or_unnamed_case')
        status = 'SKIP' if case.find('skipped') is not None else (
            'FAIL' if case.find('failure') is not None or case.find('error') is not None else 'PASS')
        cases[name] = status
    if not required_cases or len(set(required_cases)) != len(required_cases):
        raise ValueError('trusted_case_inventory_missing')
    if set(required_cases) - set(cases) or not cases:
        raise ValueError('required_cases_missing')
    # Additional cases may extend coverage, but may not fail/skip either.
    return {'cases': cases, 'pass': sum(v == 'PASS' for v in cases.values()),
            'fail': sum(v == 'FAIL' for v in cases.values()), 'skip': sum(v == 'SKIP' for v in cases.values()),
            'sha256': hashlib.sha256(raw).hexdigest()}


def _artifact(path, root):
    path = Path(path)
    if not path.is_absolute() or not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
        raise ValueError('owned_artifact_missing')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('artifact_escape')
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('artifact_link')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_checks(candidate_sha, lab, executor):
    operation = str(uuid.uuid4())
    receipts = []
    prepared = False
    try:
        root = admission(candidate_sha, lab)
        inventory = lab['required_cases']
        if not callable(executor) or any(not inventory.get(name) for name, _, _, junit in CHECKS if junit):
            raise ValueError('trusted_case_inventory_missing')
        with HeavyAction(lab['lock_path']) as lease:
            common = {'operation_id': operation, 'candidate_sha': candidate_sha,
                      'source_hash': lab['source_hash'], 'deadline': bound(lab)}
            try:
                prepared = True
                prepare = checked_call(executor, 'checks.prepare', common)
                e = prepare.evidence
                if (prepare.status != 'done' or e.get('status') != 'PASS'
                        or not same_source(prepare, candidate_sha, lab)
                        or any(e.get(k) is not True for k in ('sandbox_verified', 'dependency_inventory_verified',
                                                            'resource_limits_verified', 'fixture_identity_verified'))):
                    receipts.append(outcome(operation, 'blocked', e.get('reason', 'checks_sandbox_unverified'),
                                            candidate_sha, lab, facility=asdict(prepare)))
                else:
                    for name, command, cwd, junit in CHECKS:
                        request = {**common, 'check': name, 'command': list(command), 'cwd': cwd, 'junit': junit}
                        result = checked_call(executor, 'checks.run', request)
                        data = result.evidence
                        try:
                            if (result.status != 'done' or not same_source(result, candidate_sha, lab)
                                    or data.get('command') != list(command) or not data.get('version')
                                    or type(data.get('returncode')) is not int):
                                raise ValueError('structured_check_evidence_missing')
                            hashes = {key: _artifact(data[key], root) for key in ('stdout', 'stderr')}
                            parsed = parse_junit(data['junit'], inventory[name]) if junit else None
                            if parsed:
                                hashes['junit'] = _artifact(data['junit'], root)
                            passed = data['returncode'] == 0 and (not parsed or not parsed['fail'] and not parsed['skip'])
                            evidence = {'required': True, 'status': 'PASS' if passed else 'FAIL',
                                'pass': passed, 'fail': not passed, 'skip': bool(parsed and parsed['skip']),
                                'check': name, 'command': list(command), 'version': data['version'],
                                'returncode': data['returncode'], 'junit': parsed, 'artifacts': hashes,
                                'artifact_hash': hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
                                'candidate_sha': candidate_sha, 'source_hash': lab['source_hash']}
                            receipts.append(Receipt(operation, 'done' if passed else 'failed', evidence))
                        except (KeyError, OSError, ValueError, ElementTree.ParseError) as error:
                            receipts.append(outcome(operation, 'blocked', str(error), candidate_sha, lab,
                                                    required=True, check=name, command=list(command)))
                        if receipts[-1].status != 'done':
                            break
            except (OSError, RuntimeError, ValueError, TimeoutError) as error:
                receipts.append(outcome(operation, 'blocked', str(error), candidate_sha, lab))
            finally:
                if prepared:
                    try:
                        cleanup = executor('checks.cleanup', common)
                        if (not isinstance(cleanup, Receipt) or cleanup.status != 'done'
                                or cleanup.evidence.get('owned_exit_verified') is not True
                                or cleanup.evidence.get('source_unchanged') is not True):
                            raise ValueError('cleanup_unconfirmed')
                    except (OSError, RuntimeError, ValueError, TimeoutError):
                        receipts.append(outcome(operation, 'uncertain', 'cleanup_unconfirmed', candidate_sha, lab))
                        lease.uncertain(operation, 'cleanup_unconfirmed')
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        receipts.append(outcome(operation, 'blocked', str(error), candidate_sha, lab))
    return receipts