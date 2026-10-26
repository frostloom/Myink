"""Freeze host-selected bytes into a private draft, never execution authority."""
import argparse
import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat

from .development_inputs import file_hash, path, read_json, tree_hash
from .plans import _path

FIELDS = {'schema', 'task_id', 'problem', 'source_path', 'source_sha256',
          'test_path', 'test_sha256', 'files', 'root'}
REQUIRES = ['fresh_isolated_baseline', 'fresh_run_identity', 'independent_reviews']
MAX_TEST_BYTES = 1048576


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _regular(p):
    mode = p.lstat()
    _require(stat.S_ISREG(mode.st_mode) and mode.st_nlink == 1,
             'regular single-link input required')
    _require(mode.st_size <= MAX_TEST_BYTES, 'input artifact too large')


def _case_hints(raw):
    try:
        module = ast.parse(raw)
    except (SyntaxError, RecursionError, ValueError) as error:
        raise ValueError('parseable static test source required') from error
    cases = sorted('fixed_development_tests.'+node.name+'.'+method.name
        for node in module.body if isinstance(node, ast.ClassDef)
        for method in node.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
        and method.name.startswith('test_'))
    _require(0 < len(cases) <= 1000 and len(set(cases)) == len(cases)
             and all(re.fullmatch(r'fixed_development_tests\.[A-Za-z0-9_.]{1,240}', c) for c in cases),
             'bounded unique static test hints required')
    return cases


def _stable(request, request_sha, c):
    request = path(request, private=True)
    _regular(request)
    gold = path(c['test_path'], private=True)
    _regular(gold)
    source = path(c['source_path'])
    _require(file_hash(request) == request_sha, 'request drift')
    _require(tree_hash(source) == c['source_sha256'], 'source snapshot drift')
    _require(file_hash(gold) == c['test_sha256'], 'test snapshot drift')


def _inspect(request_path):
    request = path(request_path, private=True)
    _regular(request)
    request_sha = file_hash(request)
    c = read_json(request)
    _require(file_hash(request) == request_sha, 'request drift')
    _require(isinstance(c, dict) and set(c) == FIELDS
             and c['schema'] == 'pi-task-package-v1', 'unsupported task package request')
    _require(isinstance(c['task_id'], str)
             and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', c['task_id']), 'bounded task identity required')
    _require(isinstance(c['problem'], str) and c['problem'].strip()
             and len(c['problem']) <= 2000, 'bounded observed problem required')
    _require(all(isinstance(c[k], str) and re.fullmatch('[a-f0-9]{64}', c[k])
                 for k in ('source_sha256', 'test_sha256')), 'frozen input hashes required')
    source = path(c['source_path'])
    gold = path(c['test_path'], private=True)
    root = path(c['root'])
    _regular(gold)
    _require(source.is_dir() and {p.name for p in source.iterdir()} == {'src'}
             and (source/'src').is_dir(), 'closed source root containing src required')
    _require(not root.exists() and root.parent.is_dir()
             and stat.S_IMODE(root.parent.stat().st_mode) == 0o700,
             'new output root in private parent required')
    for value in (source, gold, request):
        _require(root != value and root not in value.parents and value not in root.parents,
                 'output and inputs overlap')
    files = c['files']
    _require(isinstance(files, list) and 0 < len(files) <= 8
             and all(_path(f) and f.startswith('src/') for f in files)
             and len(files) == len(set(files))
             and all((source/f).is_file() for f in files), 'declared existing src files required')
    with gold.open('rb') as stream:
        raw = stream.read(MAX_TEST_BYTES+1)
    _require(len(raw) <= MAX_TEST_BYTES, 'test source too large')
    _require(sha256(raw).hexdigest() == c['test_sha256'], 'test snapshot drift')
    hints = _case_hints(raw)
    _stable(request, request_sha, c)
    draft = dict(schema='pi-task-package-draft-v1', task_id=c['task_id'], problem=c['problem'],
        source_path=str(root/'source'), source_sha256=c['source_sha256'],
        test_path=str(root/'test.py'), test_sha256=c['test_sha256'], files=files,
        test_case_hints=hints, inventory_status='static_unverified', requires=list(REQUIRES),
        origin=dict(request_path=str(request), request_sha256=request_sha,
                    source_path=str(source), test_path=str(gold)))
    return request, request_sha, c, raw, draft


def _summary(c, draft):
    return dict(source_sha256=c['source_sha256'], test_sha256=c['test_sha256'],
                test_case_hint_count=len(draft['test_case_hints']))


def check(request_path):
    """Read-only readiness to freeze a draft; not readiness to execute Pi."""
    _, _, c, _, draft = _inspect(request_path)
    return dict(ready=True, mode='read-only-draft', **_summary(c, draft))


def _write_new(p, raw):
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _publish_new(p, raw):
    pending = p.with_name('.'+p.name+'.pending')
    _write_new(pending, raw)
    # The final name appears atomically only after data is synced and closed.
    # link is exclusive: even a competing marker must never be overwritten.
    os.link(pending, p)
    try:
        pending.unlink()
    except OSError:
        # Publication already committed. Keep the private alias and disclose it.
        return True
    return False


def freeze(request_path):
    """Reserve a fresh private root; failed partial roots are never reused."""
    request, request_sha, c, raw, draft = _inspect(request_path)
    root = Path(c['root'])
    root.mkdir(mode=0o700)
    copied = root/'source'
    shutil.copytree(c['source_path'], copied, symlinks=True)
    _require(tree_hash(copied) == c['source_sha256'], 'copied source drift')
    for p in (copied, *copied.rglob('*')):
        _require(not p.is_symlink(), 'copied source link forbidden')
        p.chmod(0o700 if p.is_dir() else 0o600)
    _write_new(root/'test.py', raw)
    _stable(request, request_sha, c)
    _require(tree_hash(copied) == c['source_sha256']
             and file_hash(root/'test.py') == c['test_sha256'], 'copied snapshot drift')
    # Last marker only: no baseline, approval, budget or runnable config is emitted.
    retained = _publish_new(root/'task-draft.json',
                            json.dumps(draft, sort_keys=True, indent=2).encode()+b'\n')
    return dict(frozen=True, mode='draft-only', draft_path=str(root/'task-draft.json'),
                staging_retained=retained,
                **_summary(c, draft))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = (freeze if args.freeze else check)(args.request)
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps(dict(ready=False, error_class=type(error).__name__)))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
