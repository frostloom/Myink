"""Trusted export source contracts; no DB/model and no native POSIX acceptance."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
from importlib.util import find_spec
import json
from pathlib import Path
import stat
from types import SimpleNamespace
from uuid import UUID

import pytest

WINDOW = dict(start='2020-01-01T00:00:00+00:00', end='2020-01-02T00:00:00+00:00')


def api():
    assert find_spec('ops.pi.feedback_export') is not None, 'trusted feedback export entry is missing'
    return importlib.import_module('ops.pi.feedback_export')


@pytest.fixture
def host(monkeypatch, tmp_path):
    """Controlled Windows test adapter: POSIX metadata is simulated, not accepted."""
    export = api()
    monkeypatch.setattr(export, '_PLATFORM', 'posix')
    original = export._check_private
    def simulated(info):
        mode = (stat.S_IFDIR | 0o700) if stat.S_ISDIR(info.st_mode) else (stat.S_IFREG | 0o600)
        original(SimpleNamespace(st_uid=export._current_uid(), st_mode=mode))
    monkeypatch.setattr(export, '_check_private', simulated)
    engines, requests = [], []
    class Engine:
        disposed = 0
        def dispose(self):
            self.disposed += 1
    def factory(dsn, **kwargs):
        engines.append(Engine())
        return engines[-1]
    monkeypatch.setattr(export, 'create_engine', factory)
    monkeypatch.setenv('PI_FEEDBACK_DATABASE_URL', 'postgresql+psycopg://readonly:synthetic@localhost/synthetic')
    rows = [dict(id=UUID(int=1), category='bug', description='保存失败 API_KEY=synthetic-private', status='open',
                 created_at=datetime(2020, 1, 1, tzinfo=timezone.utc), updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc))]
    def read(collector, request):
        collector._validate_request(request)
        requests.append(request)
        return deepcopy(rows)
    monkeypatch.setattr(export.SnapshotCollector, '_read', read)
    return SimpleNamespace(api=export, engines=engines, requests=requests, rows=rows, output=tmp_path/'feedback.json')


def test_export_uses_trusted_collector_and_roundtrips_sanitized_snapshot(host):
    result = host.api.export_feedback(**WINDOW, output=host.output)
    raw = host.output.read_bytes()
    assert b'synthetic-private' not in raw
    assert result['file_sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['row_count'] == 1 and result['has_more'] is False
    from ops.pi.feedback import load_feedback_snapshot
    data = load_feedback_snapshot(host.output, result['file_sha256'], trusted_root=host.output.parent)
    assert data['admin_scope'] is True and data['rows'][0]['redacted'] is True
    assert data['rows'][0]['untrusted_body_text'] is True
    assert data['window'] == WINDOW
    assert host.requests[0]['read_only'] is True and host.requests[0]['params']['limit'] == 51
    assert set(data['rows'][0]).isdisjoint({'contact','user_id','attachments','page_url','user_agent'})
    assert host.engines[0].disposed == 1


@pytest.mark.parametrize('start,end', [
    ('2020-01-01T00:00:00','2020-01-02T00:00:00+00:00'),
    ('2020-01-01T00:00:00+08:00','2020-01-02T00:00:00+00:00'),
    ('2020-01-02T00:00:00+00:00','2020-01-01T00:00:00+00:00'),
    ('2099-01-01T00:00:00+00:00','2099-01-02T00:00:00+00:00'),
])
def test_invalid_window_fails_before_engine_or_output(host,start,end):
    with pytest.raises(ValueError): host.api.export_feedback(start=start,end=end,output=host.output)
    assert not host.engines and not host.output.exists()


@pytest.mark.parametrize('dsn',[None,'','sqlite:///synthetic.db','https://model.invalid','postgresql://bad\nvalue'])
def test_missing_or_nonpostgres_dsn_never_creates_engine(host,monkeypatch,dsn):
    if dsn is None: monkeypatch.delenv('PI_FEEDBACK_DATABASE_URL')
    else: monkeypatch.setenv('PI_FEEDBACK_DATABASE_URL',dsn)
    with pytest.raises(ValueError): host.api.export_feedback(**WINDOW,output=host.output)
    assert not host.engines and not host.output.exists()


def test_windows_entry_is_blocked_before_database(host,monkeypatch):
    monkeypatch.setattr(host.api,'_PLATFORM','nt')
    with pytest.raises(ValueError): host.api.export_feedback(**WINDOW,output=host.output)
    assert not host.engines and not host.output.exists()


@pytest.mark.parametrize('fault',['existing','relative','symlink','parent_symlink'])
def test_output_is_fresh_absolute_and_unlinked(host,tmp_path,fault,monkeypatch):
    output=host.output
    if fault=='existing': output.write_bytes(b'existing')
    elif fault=='relative': output=Path('feedback.json')
    else:
        # Controlled link metadata: Windows lacks link-creation privilege.
        link=output if fault=='symlink' else tmp_path/'link'
        if fault=='parent_symlink':output=link/'out.json'
        original=Path.is_symlink
        monkeypatch.setattr(Path,'is_symlink',lambda p:p==link or original(p))
    with pytest.raises((ValueError,OSError)): host.api.export_feedback(**WINDOW,output=output)
    assert not host.engines
    if fault=='existing':assert output.read_bytes()==b'existing'


def test_privacy_predicate_rejects_other_owner_or_public_permissions(monkeypatch):
    export=api();uid=export._current_uid()
    for info in [SimpleNamespace(st_uid=uid+1,st_mode=stat.S_IFREG|0o600),
                 SimpleNamespace(st_uid=uid,st_mode=stat.S_IFREG|0o644),
                 SimpleNamespace(st_uid=uid,st_mode=stat.S_IFDIR|0o755)]:
        with pytest.raises(ValueError): export._check_private(info)
    export._check_private(SimpleNamespace(st_uid=uid,st_mode=stat.S_IFREG|0o600))


def test_valid_cursor_is_host_bound_and_applied_to_query(host,tmp_path):
    from ops.pi.feedback import make_feedback_snapshot
    cursor=make_feedback_snapshot(host.rows,WINDOW)['next_cursor'];p=tmp_path/'cursor.json';p.write_text(json.dumps(cursor),encoding='utf-8')
    host.rows.clear()
    result=host.api.export_feedback(**WINDOW,output=host.output,cursor_file=p)
    assert result['row_count']==0
    assert '(updated_at, id)' in host.requests[0]['sql']
    assert host.requests[0]['params']['cursor_id']=='00000000-0000-0000-0000-000000000001'
    assert host.engines[0].disposed==1


@pytest.mark.parametrize('fault',['foreign_window','duplicate_json','oversize','symlink'])
def test_invalid_cursor_never_reaches_database(host,tmp_path,fault,monkeypatch):
    p=tmp_path/'cursor.json'
    if fault=='foreign_window':p.write_text(json.dumps(dict(scope='admin',window_sha256='0'*64,updated_at=WINDOW['start'],id='00000000-0000-0000-0000-000000000001')))
    elif fault=='duplicate_json':p.write_text('{"scope":"admin","scope":"admin"}')
    elif fault=='oversize':p.write_bytes(b' '*8193)
    else:
        original=Path.is_symlink
        monkeypatch.setattr(Path,'is_symlink',lambda item:item==p or original(item))
    with pytest.raises((ValueError,OSError)):host.api.export_feedback(**WINDOW,output=host.output,cursor_file=p)
    assert not host.engines and not host.output.exists()


def test_snapshot_failure_disposes_engine_without_file(host):
    host.rows[0]['contact']='forbidden'
    with pytest.raises(ValueError):host.api.export_feedback(**WINDOW,output=host.output)
    assert host.engines[0].disposed==1 and not host.output.exists()


def test_snapshot_tamper_is_rejected_before_write(host,monkeypatch):
    original=host.api.SnapshotCollector.collect_feedback
    def corrupt(*args,**kwargs):
        value=original(*args,**kwargs);value['snapshot_sha256']='0'*64;return value
    monkeypatch.setattr(host.api.SnapshotCollector,'collect_feedback',corrupt)
    with pytest.raises(ValueError):host.api.export_feedback(**WINDOW,output=host.output)
    assert host.engines[0].disposed==1 and not host.output.exists()


def test_write_failure_disposes_engine_and_cleans_partial_file(host,monkeypatch):
    def denied(fd,raw):raise OSError('synthetic write failure')
    monkeypatch.setattr(host.api.os,'write',denied)
    with pytest.raises(OSError):host.api.export_feedback(**WINDOW,output=host.output)
    assert host.engines[0].disposed==1 and not host.output.exists()


def test_snapshot_size_bound_rejects_before_creation(host):
    with pytest.raises(ValueError):host.api._write_snapshot(host.output,b'x'*(512*1024+1))
    assert not host.output.exists()


def test_cli_errors_do_not_echo_dsn_exception_or_feedback(host,monkeypatch,capsys):
    def broken(*args,**kwargs):raise RuntimeError('synthetic-password sensitive-body')
    monkeypatch.setattr(host.api,'export_feedback',broken)
    assert host.api.main(['--start',WINDOW['start'],'--end',WINDOW['end'],'--output',str(host.output)])==1
    captured=capsys.readouterr();assert captured.out=='' and 'synthetic-password' not in captured.err and 'sensitive-body' not in captured.err
    assert host.api.main(['--dsn','postgresql://secret-password'])==2
    captured=capsys.readouterr();assert 'secret-password' not in captured.err and not host.engines


def test_cli_success_prints_metadata_only(host,capsys):
    assert host.api.main(['--start',WINDOW['start'],'--end',WINDOW['end'],'--output',str(host.output)])==0
    captured=capsys.readouterr();result=json.loads(captured.out)
    assert result['row_count']==1 and captured.err==''
    assert 'description' not in captured.out and 'synthetic' not in captured.out
