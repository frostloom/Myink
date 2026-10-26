"""Draft packaging is byte freezing, never execution or new authority."""
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from ops.pi.development_inputs import file_hash, read_json, tree_hash


def api():
    return importlib.import_module('ops.pi.task_package')


@pytest.fixture
def package(tmp_path):
    root = tmp_path.resolve()
    root.chmod(0o700)
    source = root/'input'; (source/'src').mkdir(parents=True)
    source_marker, test_marker = root/'source-executed', root/'test-executed'
    (source/'src/a.py').write_text(f"from pathlib import Path\nPath({str(source_marker)!r}).touch()\n")
    (source/'src/dependency.py').write_text('value = 1\n')
    gold = root/'gold.py'
    gold.write_text(f"from pathlib import Path\nPath({str(test_marker)!r}).touch()\n"
                    'import unittest\nclass Case(unittest.TestCase):\n'
                    '    def test_value(self): self.assertEqual(1, 1)\n')
    gold.chmod(0o600)
    request = root/'request.json'
    c = dict(schema='pi-task-package-v1', task_id='small-fix', problem='Existing value is missed',
             source_path=str(source), source_sha256=tree_hash(source), test_path=str(gold),
             test_sha256=file_hash(gold), files=['src/a.py'], root=str(root/'draft'))
    request.write_text(json.dumps(c)); request.chmod(0o600)
    return request, c, source_marker, test_marker


def update(package, **values):
    request, c, *_ = package
    c.update(values); request.write_text(json.dumps(c)); request.chmod(0o600)


def test_default_check_has_no_writes_execution_network_or_processes(package, monkeypatch):
    request, c, sm, tm = package
    before = sorted(str(p) for p in request.parent.rglob('*'))
    def forbidden(*args, **kwargs):
        raise AssertionError('packaging must not launch a process or network call')
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, 'Popen', forbidden)
        patch.setattr(socket, 'socket', forbidden)
        result = api().check(request)
    assert result['ready'] is True and result['mode'] == 'read-only-draft'
    assert result['test_case_hint_count'] == 1
    assert sorted(str(p) for p in request.parent.rglob('*')) == before
    assert not sm.exists() and not tm.exists() and not Path(c['root']).exists()


def test_freeze_preserves_all_bytes_and_private_modes_without_execution(package):
    request, c, sm, tm = package
    original = request.read_bytes(), Path(c['test_path']).read_bytes()
    result = api().freeze(request)
    root = Path(c['root']); draft_path = root/'task-draft.json'
    assert result['frozen'] is True and Path(result['draft_path']) == draft_path
    assert tree_hash(root/'source') == c['source_sha256']
    assert file_hash(root/'test.py') == c['test_sha256']
    assert tree_hash(c['source_path']) == c['source_sha256']
    assert (request.read_bytes(), Path(c['test_path']).read_bytes()) == original
    assert not sm.exists() and not tm.exists()
    for p in (root, *root.rglob('*')):
        assert p.stat().st_mode & 0o777 == (0o700 if p.is_dir() else 0o600)
    draft = read_json(draft_path)
    assert draft['schema'] == 'pi-task-package-draft-v1'
    assert draft['source_path'] == str(root/'source') and draft['test_path'] == str(root/'test.py')
    assert draft['source_sha256'] == c['source_sha256'] and draft['test_sha256'] == c['test_sha256']
    assert draft['test_case_hints'] == ['fixed_development_tests.Case.test_value']
    assert draft['inventory_status'] == 'static_unverified'
    assert draft['requires'] == ['fresh_isolated_baseline', 'fresh_run_identity', 'independent_reviews']
    assert not {'approved', 'verified', 'baseline', 'review_path', 'ledger_path', 'runtime_path'} & draft.keys()
    from ops.pi.development_inputs import prepare_template
    with pytest.raises(ValueError, match='unsupported development config'):
        prepare_template(draft_path)


@pytest.mark.parametrize('field', ['source_sha256', 'test_sha256'])
def test_hash_drift_rejected_before_output(package, field):
    update(package, **{field: '0'*64})
    with pytest.raises(ValueError): api().freeze(package[0])
    assert not Path(package[1]['root']).exists()


@pytest.mark.parametrize('field,value', [
    ('schema', 'pi-development-v1'), ('task_id', '../escape'), ('problem', ' '),
    ('problem', 'x'*2001), ('source_sha256', 'X'*64), ('files', []),
    ('files', ['src/a.py', 'src/a.py']), ('files', ['../secret']),
    ('files', ['src/missing.py']), ('files', ['gold.py']), ('files', [42]),
])
def test_invalid_contract_rejected_without_output(package, field, value):
    update(package, **{field: value})
    with pytest.raises(ValueError): api().freeze(package[0])
    assert not Path(package[1]['root']).exists()


@pytest.mark.parametrize('extra', ['approved', 'ledger_path', 'review_path'])
def test_authority_fields_cannot_enter_request(package, extra):
    update(package, **{extra: True})
    with pytest.raises(ValueError): api().check(package[0])
    assert not Path(package[1]['root']).exists()


def test_duplicate_json_key_rejected(package):
    request, c, *_ = package
    request.write_text(request.read_text()[:-1]+',"task_id":"replacement"}')
    with pytest.raises(ValueError, match='duplicate'): api().freeze(request)
    assert not Path(c['root']).exists()


@pytest.mark.parametrize('change', ['request', 'test', 'parent'])
def test_private_permissions_required(package, change):
    request, c, *_ = package
    target = request if change == 'request' else Path(c['test_path']) if change == 'test' else request.parent
    target.chmod(0o755 if change == 'parent' else 0o644)
    with pytest.raises(ValueError): api().freeze(request)
    assert not Path(c['root']).exists()


@pytest.mark.parametrize('change', ['source_link', 'source_hardlink', 'test_link', 'test_hardlink', 'extra_root'])
def test_links_and_open_source_root_refused(package, change):
    request, c, *_ = package
    source, gold = Path(c['source_path']), Path(c['test_path'])
    if change == 'source_link': (source/'src/link.py').symlink_to('a.py')
    elif change == 'source_hardlink': os.link(source/'src/a.py', source/'src/link.py')
    elif change == 'test_link':
        alias = request.parent/'alias.py'; alias.symlink_to(gold); update(package, test_path=str(alias))
    elif change == 'test_hardlink':
        alias = request.parent/'alias.py'; os.link(gold, alias); update(package, test_path=str(alias))
    else:
        (source/'not-src.txt').write_text('extra')
        update(package, source_sha256=tree_hash(source))
    with pytest.raises(ValueError): api().freeze(request)
    assert not Path(c['root']).exists()


@pytest.mark.parametrize('root', ['source', 'inside_source', 'test', 'request', 'relative'])
def test_output_cannot_overlap_inputs_or_use_relative_path(package, root):
    request, c, *_ = package
    choices = dict(source=c['source_path'], inside_source=str(Path(c['source_path'])/'src/new'),
                   test=c['test_path'], request=str(request), relative='relative-output')
    update(package, root=choices[root])
    before = request.read_bytes(), Path(c['test_path']).read_bytes()
    with pytest.raises(ValueError): api().freeze(request)
    assert (request.read_bytes(), Path(c['test_path']).read_bytes()) == before


def test_existing_output_is_never_overwritten_or_replayed(package):
    request, c, *_ = package
    api().freeze(request); root = Path(c['root'])
    marker = root/'user-data'; marker.write_bytes(b'preserve')
    before = (root/'task-draft.json').read_bytes()
    with pytest.raises(ValueError): api().freeze(request)
    assert marker.read_bytes() == b'preserve' and (root/'task-draft.json').read_bytes() == before


@pytest.mark.parametrize('text', ['class:', 'value=1\n',
    'class Case:\n def test_x(self): pass\nclass Case:\n def test_x(self): pass\n'])
def test_unusable_static_inventory_is_rejected(package, text):
    gold = Path(package[1]['test_path']); gold.write_text(text)
    update(package, test_sha256=file_hash(gold))
    with pytest.raises(ValueError): api().freeze(package[0])
    assert not Path(package[1]['root']).exists()


def test_static_hints_do_not_claim_inherited_or_dynamic_runtime_inventory(package):
    gold = Path(package[1]['test_path'])
    gold.write_text('import unittest\nclass Base(unittest.TestCase):\n def test_base(self): pass\n'
                    'class Child(Base): pass\n')
    update(package, test_sha256=file_hash(gold)); api().freeze(package[0])
    draft = read_json(Path(package[1]['root'])/'task-draft.json')
    assert draft['test_case_hints'] == ['fixed_development_tests.Base.test_base']
    assert draft['inventory_status'] == 'static_unverified'
    assert 'fresh_isolated_baseline' in draft['requires']


def test_oversized_gold_rejected_before_copy(package):
    gold = Path(package[1]['test_path']); gold.write_bytes(b'#'*(1048576+1))
    update(package, test_sha256=file_hash(gold))
    with pytest.raises(ValueError): api().freeze(package[0])
    assert not Path(package[1]['root']).exists()


@pytest.mark.parametrize('changed', ['source', 'test', 'request'])
def test_copy_time_drift_never_publishes_complete_draft(package, monkeypatch, changed):
    request, c, *_ = package
    import shutil
    original = shutil.copytree
    def drift(*args, **kwargs):
        result = original(*args, **kwargs)
        if changed == 'source': (Path(c['source_path'])/'src/a.py').write_text('external = True\n')
        elif changed == 'test': Path(c['test_path']).write_text('external = True\n')
        else: request.write_text(request.read_text()+' ')
        return result
    monkeypatch.setattr(shutil, 'copytree', drift)
    with pytest.raises(ValueError): api().freeze(request)
    assert Path(c['root']).is_dir() and not (Path(c['root'])/'task-draft.json').exists()


def test_cli_default_is_readonly_and_freeze_requires_explicit_flag(package):
    request, c, *_ = package
    result = subprocess.run([sys.executable, '-m', 'ops.pi.task_package', '--request', str(request)],
                            capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)['mode'] == 'read-only-draft'
    assert not Path(c['root']).exists()
    result = subprocess.run([sys.executable, '-m', 'ops.pi.task_package', '--request', str(request), '--freeze'],
                            capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)['frozen'] is True
    assert (Path(c['root'])/'task-draft.json').is_file()


def test_oversized_request_is_rejected_before_whole_file_hash(package, monkeypatch):
    request, c, *_ = package
    request.write_bytes(b' '*(1048576+1))
    module = api(); original = module.file_hash
    def bounded(p):
        if Path(p) == request:
            raise AssertionError('oversized request must be rejected before reading all bytes')
        return original(p)
    monkeypatch.setattr(module, 'file_hash', bounded)
    with pytest.raises(ValueError): module.check(request)
    assert not Path(c['root']).exists()


@pytest.mark.parametrize('changed', ['test_link', 'test_mode', 'request_mode'])
def test_copy_time_input_privacy_drift_is_rejected(package, monkeypatch, changed):
    request, c, *_ = package
    import shutil
    original = shutil.copytree
    def drift(*args, **kwargs):
        result = original(*args, **kwargs)
        gold = Path(c['test_path'])
        if changed == 'test_link' and not gold.is_symlink():
            saved = request.parent/'saved-gold'; saved.write_bytes(gold.read_bytes()); saved.chmod(0o600)
            gold.unlink(); gold.symlink_to(saved)
        elif changed == 'test_mode': gold.chmod(0o644)
        elif changed == 'request_mode': request.chmod(0o644)
        return result
    monkeypatch.setattr(shutil, 'copytree', drift)
    with pytest.raises(ValueError): api().freeze(request)
    assert not (Path(c['root'])/'task-draft.json').exists()


@pytest.mark.parametrize('phase', ['write', 'fsync'])
def test_failed_metadata_io_never_publishes_completion_marker(package, monkeypatch, phase):
    request, c, *_ = package
    original_open, original_sync = os.fdopen, os.fsync
    opened, synced = 0, 0
    class FailedWrite:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def write(self, raw):
            self.stream.write(raw[:len(raw)//2])
            raise OSError(28, 'injected metadata write failure')
    def open_stream(*args, **kwargs):
        nonlocal opened
        opened += 1
        stream = original_open(*args, **kwargs)
        return FailedWrite(stream) if phase == 'write' and opened == 2 else stream
    def sync(fd):
        nonlocal synced
        synced += 1
        if phase == 'fsync' and synced == 2: raise OSError(28, 'injected metadata sync failure')
        return original_sync(fd)
    monkeypatch.setattr(os, 'fdopen', open_stream)
    monkeypatch.setattr(os, 'fsync', sync)
    with pytest.raises(OSError): api().freeze(request)
    assert (Path(c['root'])/'test.py').is_file()
    assert not (Path(c['root'])/'task-draft.json').exists()


def test_completion_marker_creation_race_never_overwrites_existing_bytes(package, monkeypatch):
    request, c, *_ = package
    marker = Path(c['root'])/'task-draft.json'; original = os.fsync; count = 0
    def sync(fd):
        nonlocal count
        count += 1
        result = original(fd)
        if count == 2: marker.write_bytes(b'other writer marker')
        return result
    monkeypatch.setattr(os, 'fsync', sync)
    with pytest.raises(FileExistsError): api().freeze(request)
    assert marker.read_bytes() == b'other writer marker'


def test_optional_alias_cleanup_cannot_turn_committed_draft_into_false_failure(package, monkeypatch):
    request, c, *_ = package
    original = Path.unlink
    def unlink(p, *args, **kwargs):
        if p.name == '.task-draft.json.pending': raise OSError('injected private alias cleanup failure')
        return original(p, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', unlink)
        result = api().freeze(request)
    assert result['frozen'] is True and result['staging_retained'] is True
    root = Path(c['root'])
    assert read_json(root/'task-draft.json')['inventory_status'] == 'static_unverified'
    assert (root/'.task-draft.json.pending').read_bytes() == (root/'task-draft.json').read_bytes()
    assert (root/'.task-draft.json.pending').stat().st_mode & 0o777 == 0o600
