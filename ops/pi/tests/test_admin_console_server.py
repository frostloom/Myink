"""Real local Unix HTTP transport; all publishing effects remain SIMULATED."""
from pathlib import Path
from threading import Thread
import json
import time
import tempfile
import httpx
import pytest
from ops.pi.tests.test_admin_console import console_case, bundle_case, finished, stopped, completed, config_file

TOKEN='console-fixture-token-with-at-least-32-characters'


@pytest.fixture
def local_console(console_case,tmp_path):
    from ops.pi.admin_console_server import make_server
    console,request,publisher,case=console_case;temporary=tempfile.TemporaryDirectory(prefix='pi-console-');path=Path(temporary.name).resolve()/'console.sock';server=make_server(path,TOKEN,console);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    with httpx.Client(transport=httpx.HTTPTransport(uds=str(path)),base_url='http://console',headers={'X-Pi-Console-Token':TOKEN}) as client:
        try:yield client,console,request,publisher
        finally:server.shutdown();server.server_close();thread.join(timeout=5);temporary.cleanup()


def test_local_socket_requires_service_auth_before_any_data_or_action(local_console):
    client,console,request,publisher=local_console
    response=client.get('/v1/status',headers={'X-Pi-Console-Token':'wrong'})
    assert response.status_code==401 and 'candidate' not in response.text and publisher.calls==[]
    assert client.post('/v1/decisions',headers={'X-Pi-Console-Token':'wrong'},json=request).status_code==401


def test_status_and_defer_use_real_local_transport_and_only_export_safe_audit(local_console):
    client,console,request,publisher=local_console
    status=client.get('/v1/status');assert status.status_code==200 and status.json()['mode']=='SIMULATED'
    result=client.post('/v1/decisions',json=dict(request,decision='defer'));assert result.status_code==202 and result.json()['status']=='deferred'
    runs=client.get('/v1/runs?limit=1');assert runs.status_code==200 and runs.json()['total']==1
    events=client.get('/v1/events',params={'run_id':'admin-'+request['request_id']});assert events.status_code==200 and events.json()['total']==1
    assert client.get('/v1/daily?day=2026-10-31').json()['authority']=='audit_only' and not publisher.calls
    assert str(console.root) not in status.text+events.text


def test_publish_receipt_is_polled_until_physical_fixture_confirmation(local_console):
    client,console,request,publisher=local_console
    result=client.post('/v1/decisions',json=request);assert result.status_code==202
    for _ in range(100):
        operation=client.get('/v1/operations/'+request['request_id']).json()
        if operation['status']=='succeeded':break
        time.sleep(.02)
    assert operation['status']=='succeeded' and publisher.calls==['prepare','publish']
    assert client.post('/v1/decisions',json=request).json()['status']=='succeeded' and publisher.calls==['prepare','publish']


@pytest.mark.parametrize('suffix',['/v1/runs?limit=101','/v1/runs?offset=-1','/v1/daily?day=not-a-date','/v1/status?host_path=/etc/passwd','/v1/runs?limit=1&limit=2'])
def test_invalid_or_extra_query_values_are_rejected(local_console,suffix):
    client,*_=local_console;assert client.get(suffix).status_code==400


def test_extra_command_fields_and_oversized_payloads_cannot_reach_publisher(local_console):
    client,console,request,publisher=local_console
    assert client.post('/v1/decisions',json=dict(request,command='docker anything')).status_code==400
    assert client.post('/v1/decisions',content=b'x'*5000,headers={'Content-Type':'application/json'}).status_code==413
    assert publisher.calls==[]


def test_corrupt_export_is_unavailable_and_never_an_empty_success(local_console):
    client,console,request,publisher=local_console;client.post('/v1/decisions',json=dict(request,decision='defer'));(console.export_root/'manifest.json').write_text('{}')
    response=client.get('/v1/runs');assert response.status_code==503 and response.json()=={'error':'unavailable'}


def test_actual_socket_rejects_nonfixed_path_or_peer_before_binding(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from ops.pi.admin_console_server import make_server
    with pytest.raises(ValueError):make_server(tmp_path/'bad.sock',TOKEN,SimpleNamespace(gate=SimpleNamespace(mode='ACTUAL')),allowed_uid=501)
    assert not (tmp_path/'bad.sock').exists()


def test_installed_console_config_never_accepts_nonfixed_paths(tmp_path,monkeypatch):
    from ops.pi.admin_console_server import load_config
    import os
    monkeypatch.setattr(os,'geteuid',lambda:0)
    with pytest.raises(ValueError):load_config(tmp_path/'arbitrary.json','0'*64)


def test_non_ascii_service_credentials_are_rejected_without_handler_failure(local_console):
    client,console,request,publisher=local_console
    response=client.get('/v1/status',headers={b'X-Pi-Console-Token':b'\xff'})
    assert response.status_code==401 and publisher.calls==[]


def test_runtime_service_credential_is_atomic_private_and_rotatable(tmp_path):
    from ops.pi.admin_console_server import write_client_token
    import os,stat
    path=tmp_path/'client-token';write_client_token(path,TOKEN)
    assert path.read_text()==TOKEN and stat.S_IMODE(path.stat().st_mode)==0o640 and path.stat().st_uid==os.geteuid()
    write_client_token(path,TOKEN+'-rotated');assert path.read_text()==TOKEN+'-rotated'
    assert list(tmp_path.iterdir())==[path]


def test_runtime_service_credential_cannot_follow_a_symlink(tmp_path):
    from ops.pi.admin_console_server import write_client_token
    target=tmp_path/'other';target.write_text('untouched');path=tmp_path/'client-token';path.symlink_to(target)
    with pytest.raises(ValueError):write_client_token(path,TOKEN)
    assert target.read_text()=='untouched'


def test_closed_entry_routes_console_without_triggering_nightly_or_models(tmp_path,monkeypatch):
    import sys
    from ops.pi.tests.test_observer_entry import module
    from ops.pi import admin_console_server
    entry=module();(tmp_path/'vendor').mkdir();seen=[];old=list(sys.path)
    monkeypatch.setattr(entry,'verify_release',lambda *a:tmp_path/'code')
    monkeypatch.setattr(admin_console_server,'serve',lambda *a:seen.append(a) or {'status':'stopped'},raising=False)
    monkeypatch.setattr(sys,'argv',['entry.py','--component','console','--config','/fixed/config.json','--config-sha256','a'*64])
    try:assert entry.main()==0
    finally:sys.path[:]=old
    assert seen==[('/fixed/config.json','a'*64)]
