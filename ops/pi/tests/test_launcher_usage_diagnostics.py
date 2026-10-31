"""Real private files, SQLite and host HTTP; only external Docker/provider are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import stat
from threading import Event, Thread
import time

import httpx
import pytest

from ops.pi import analysis_launcher as launcher
from ops.pi.budget import totals
from ops.pi.tests.test_analysis_launcher import setup, install_external_boundaries
from ops.pi.tests.test_analysis_budget import setup_run, bind, http_gateway
from ops.pi.tests.test_budget import ledger, policy
from ops.pi.tests.test_pi_gateway import PiStream


def sink(path, index=0):
    assert importlib.util.find_spec('ops.pi.usage_diagnostics'), 'private usage diagnostic sink missing'
    return importlib.import_module('ops.pi.usage_diagnostics').make_usage_observer(path, slot_index=index)


def record(path):
    assert path.exists(), 'host did not create private usage destination'
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        raw = path.read_text()
        if raw.endswith('\n'):
            rows = raw.splitlines()
            assert len(rows) == 1
            return json.loads(rows[0])
        time.sleep(.01)
    pytest.fail('synthetic diagnostic callback was not delivered')


def test_private_sink_caps_concurrent_writers_without_overwriting(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / 'usage.jsonl'
    observe = sink(path)
    assert path.read_bytes() == b'' and stat.S_IMODE(path.stat().st_mode) == 0o600
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: observe({'parser_reason': 'complete'}), range(24)))
    assert record(path) == dict(schema='pi-usage-diagnostic-v1', slot_index=0,
                               evidence={'parser_reason': 'complete'})
    assert path.stat().st_size <= 8192
    before = path.read_bytes()
    with pytest.raises(FileExistsError): sink(path)
    assert path.read_bytes() == before


def test_oversized_snapshot_is_not_persisted(tmp_path):
    observe = sink(tmp_path / 'usage.jsonl')
    observe({'untrusted': 'x' * 8192})
    assert (tmp_path / 'usage.jsonl').read_bytes() == b''
    observe({'parser_reason': 'complete'})
    assert record(tmp_path / 'usage.jsonl')['evidence'] == {'parser_reason': 'complete'}


@pytest.mark.parametrize('index', [True, -1, 30])
def test_invalid_slot_cannot_create_destination(tmp_path, index):
    path = tmp_path / 'usage.jsonl'
    with pytest.raises(ValueError): sink(path, index)
    assert not path.exists()


@pytest.mark.parametrize('kind', ['parent-mode', 'parent-symlink', 'file-symlink'])
def test_nonprivate_or_linked_initial_destination_is_rejected(tmp_path, kind):
    private = tmp_path / 'private'; private.mkdir(mode=0o700)
    target = private / 'usage.jsonl'
    if kind == 'parent-mode': private.chmod(0o755)
    elif kind == 'parent-symlink':
        alias = tmp_path / 'alias'; alias.symlink_to(private, target_is_directory=True)
        target = alias / 'usage.jsonl'
    else:
        victim = private / 'victim'; victim.write_text('do not change')
        target.symlink_to(victim)
    with pytest.raises((ValueError, OSError)): sink(target)
    assert not (private / 'usage.jsonl').exists() or kind == 'file-symlink'
    if kind == 'file-symlink': assert victim.read_text() == 'do not change'


@pytest.mark.parametrize('kind', ['inode', 'symlink', 'hardlink', 'mode', 'fifo'])
def test_replaced_or_unprotected_destination_never_receives_snapshot(tmp_path, kind):
    path = tmp_path / 'usage.jsonl'; observe = sink(path)
    victim = tmp_path / 'victim'; victim.write_text('private destination')
    if kind == 'inode':
        path.rename(tmp_path / 'original')
        path.write_text('replacement'); path.chmod(0o600)
    elif kind == 'symlink': path.unlink(); path.symlink_to(victim)
    elif kind == 'hardlink': (tmp_path / 'alias').hardlink_to(path)
    elif kind == 'mode': path.chmod(0o644)
    else: path.unlink(); os.mkfifo(path, 0o600)
    with pytest.raises((ValueError, OSError)): observe({'parser_reason': 'complete'})
    assert victim.read_text() == 'private destination'
    if kind == 'inode': assert path.read_text() == 'replacement'
    elif kind in ('mode', 'hardlink'): assert path.read_bytes() == b''


@pytest.mark.parametrize('missing', [False, True])
def test_analysis_http_records_presence_without_refunding_missing_counters(setup_run, tmp_path, missing):
    run, slots, p = setup_run
    bind(run, p)
    path = tmp_path / 'usage.jsonl'
    usage = dict(input_tokens=7, output_tokens=0)
    if not missing: usage.update(cache_read_input_tokens=0, cache_creation_input_tokens=0)
    def send(body, timeout):
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=PiStream(usage))
    handler = run.gateway_handler(0, p, send, scope_token='x'*48, usage_observer=sink(path))
    with http_gateway(handler) as (client, url):
        headers = {'x-api-key': 'x'*48, 'X-Pi-Scope': 'local-trial-1'}
        assert client.post(url, headers=headers | {'x-api-key': 'wrong'}, json=slots[0]['request']).status_code == 403
        assert path.read_bytes() == b''
        response = client.post(url, headers=headers, json=slots[0]['request'])
        assert response.status_code == 200 and 'Reviewed.' in response.text
        evidence = record(path)['evidence']
        start = evidence['raw_usage']['message_start']['dimensions']
        assert start['cache_creation_input_tokens'] == (
            dict(present=False, type='missing', value=None) if missing
            else dict(present=True, type='integer', value=0))
        row = run.ledger.get(evidence['attempt_id'])
        assert row['status'] == ('uncertain' if missing else 'done')
        assert totals(run.ledger, 'local-trial-1') == (1, 18384 if missing else 54)
        before = path.read_bytes()
        assert client.post(url, headers=headers, json=slots[0]['request']).status_code == 403
        assert path.read_bytes() == before


def test_launcher_creates_two_separate_sanitized_slot_records(setup, monkeypatch):
    c, ledger, _, _, _ = setup
    processes, calls, daemon = install_external_boundaries(monkeypatch)
    result = launcher.launch(c, execute=True)
    assert result['status'] == 'completed' and len(calls) == 2
    assert result['usage_diagnostics'] == 'best_effort_private'
    records = [record(Path(c['root']) / f'slot-{i}-usage-private.jsonl') for i in (0, 1)]
    assert [r['slot_index'] for r in records] == [0, 1]
    assert len({r['evidence']['attempt_id'] for r in records}) == 2
    for r in records:
        e = r['evidence']
        assert e['raw_usage']['message_delta']['dimensions']['output_tokens']['value'] == 100
        assert ledger.get(e['attempt_id'])['status'] == 'done'
        encoded = json.dumps(r)
        for secret in ('sk-synthetic', str(ledger.path), 'domains', 'hypothesis', 'x-api-key'):
            assert secret not in encoded
    assert all(p.poll() == 0 for p in processes) and not daemon.objects
    assert 'raw_usage' not in json.dumps(result)


@pytest.mark.parametrize('kind', ['missing-cache', 'secret-extra', 'upstream-error'])
def test_launcher_unknown_usage_stops_and_keeps_safe_diagnostic(setup, monkeypatch, kind):
    c, ledger, _, _, _ = setup
    processes, _, daemon = install_external_boundaries(monkeypatch)
    calls = []
    @contextmanager
    def provider(policy, credentials):
        def send(body, timeout):
            calls.append(body)
            if kind == 'upstream-error': raise OSError('SECRET-UPSTREAM')
            usage = dict(input_tokens=7, output_tokens=0)
            if kind == 'secret-extra':
                usage.update(cache_read_input_tokens=0, cache_creation_input_tokens=0)
                usage['SECRET-FIELD'] = 'SECRET-VALUE'
            return httpx.Response(200, stream=PiStream(usage))
        yield send
    monkeypatch.setattr(launcher, '_provider', provider)
    result = launcher.launch(c, execute=True)
    assert result['status'] == 'blocked' and len(calls) == 1
    assert result['slots'][1]['status'] == 'NOT_RUN'
    evidence = record(Path(c['root']) / 'slot-0-usage-private.jsonl')['evidence']
    row = ledger.get(evidence['attempt_id'])
    assert row['status'] == 'uncertain'
    assert row['evidence']['charged_microyuan'] == row['payload']['reserved_microyuan']
    assert 'SECRET' not in json.dumps(evidence) and 'SECRET' not in json.dumps(result)
    assert not (Path(c['root']) / 'slot-1-usage-private.jsonl').exists()
    assert all(p.poll() is not None for p in processes) and not daemon.objects


def test_sink_setup_failure_prevents_slot_admission(setup, monkeypatch):
    c, ledger, _, _, _ = setup
    processes, calls, daemon = install_external_boundaries(monkeypatch)
    def fail(*a, **kw): raise OSError('PRIVATE-DIAGNOSTIC-PATH')
    monkeypatch.setattr(launcher, 'make_usage_observer', fail, raising=False)
    result = launcher.launch(c, execute=True)
    assert result['status'] == 'blocked' and not processes and not calls and not daemon.objects
    assert {s['status'] for s in result['slots']} == {'NOT_RUN'}
    assert 'PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('kind', ['raise', 'stall'])
def test_callback_failure_or_stall_never_blocks_host_settlement(setup, monkeypatch, kind):
    c, ledger, _, _, _ = setup
    processes, calls, daemon = install_external_boundaries(monkeypatch)
    entered, release, completed, drained = Event(), Event(), Event(), Event()
    seen, results, errors = [], [], []
    def factory(path, *, slot_index):
        def observe(item):
            entered.set()
            if kind == 'stall': release.wait(5)
            seen.append(slot_index)
            if len(seen) == 2: drained.set()
            raise OSError('SECRET-STORAGE')
        return observe
    monkeypatch.setattr(launcher, 'make_usage_observer', factory, raising=False)
    def execute():
        try: results.append(launcher.launch(c, execute=True))
        except Exception as exc: errors.append(exc)
        finally: completed.set()
    caller = Thread(target=execute, daemon=True); caller.start()
    try:
        assert entered.wait(2), 'host must actually dispatch the diagnostic'
        assert completed.wait(2), 'host completion must not await diagnostic storage'
        assert not errors and results[0]['status'] == 'completed'
        if kind == 'stall': assert not release.is_set() and not seen
        assert len(calls) == 2 and all(p.poll() == 0 for p in processes) and not daemon.objects
        with ledger.transaction() as db:
            assert [r[0] for r in db.execute("SELECT status FROM operations WHERE kind='model-attempt'")] == ['done', 'done']
        assert 'SECRET' not in json.dumps(results)
    finally:
        release.set(); caller.join(3)
        assert drained.wait(2)


def retained_descriptor(monkeypatch, path):
    """Capture the actual created OS handle; all file operations remain real."""
    module = importlib.import_module('ops.pi.usage_diagnostics')
    original_open, descriptors = module.os.open, []
    def opened(value, flags, *args, **kwargs):
        fd = original_open(value, flags, *args, **kwargs)
        if Path(value) == path and flags & os.O_EXCL:
            descriptors.append(fd)
        return fd
    monkeypatch.setattr(module.os, 'open', opened)
    return descriptors


def test_unlinked_original_inode_stays_owned_until_callback_decides(tmp_path, monkeypatch):
    path = tmp_path / 'usage.jsonl'
    descriptors = retained_descriptor(monkeypatch, path)
    observe = sink(path)
    original = path.stat(); path.unlink()
    # An open reference pins the unlinked inode so it cannot be reallocated to
    # the replacement. Saving the inode number after closing is insufficient.
    owned = os.fstat(descriptors[0])
    assert owned.st_nlink == 0 and owned.st_ino == original.st_ino and owned.st_dev == original.st_dev
    path.write_text('replacement'); path.chmod(0o600)
    with pytest.raises(ValueError): observe({'parser_reason': 'complete'})
    assert path.read_text() == 'replacement'
    with pytest.raises(OSError): os.fstat(descriptors[0])


@pytest.mark.parametrize('decision', ['discard', 'write', 'write-failure'])
def test_original_descriptor_is_released_on_discard_or_attempt(tmp_path, monkeypatch, decision):
    import gc
    import weakref
    path = tmp_path / 'usage.jsonl'
    descriptors = retained_descriptor(monkeypatch, path)
    observe = sink(path)
    assert os.fstat(descriptors[0]).st_ino == path.stat().st_ino
    if decision == 'write': observe({'parser_reason': 'complete'})
    elif decision == 'write-failure':
        path.chmod(0o644)
        with pytest.raises(ValueError): observe({'parser_reason': 'complete'})
    else:
        reference = weakref.ref(observe)
        del observe
        gc.collect()
        assert reference() is None
    with pytest.raises(OSError): os.fstat(descriptors[0])
