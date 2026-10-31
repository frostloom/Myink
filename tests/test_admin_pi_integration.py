"""Real JWT/DB roles and real Unix transport, with SIMULATED host effects."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from myink.api import routes_admin_pi as routes
from myink.api.main import app
from myink.db import new_session
from myink.models import AdminAccessLog, User
from test_admin import admin_data, bearer
from ops.pi.tests.test_admin_console import console_case, bundle_case, finished, stopped, completed, config_file

PREFIX='/api/v1/admin/pi'
TOKEN='integration-console-private-token-more-than-32-bytes'

@pytest.fixture
def connected_console(console_case, monkeypatch):
    from ops.pi.admin_console_server import make_server
    console,packet,publisher,case=console_case
    with TemporaryDirectory(prefix='pi-api-') as directory:
        root=Path(directory).resolve();socket=root/'control.sock';secret=root/'token'
        secret.write_text(TOKEN);secret.chmod(0o600)
        server=make_server(socket,TOKEN,console)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        monkeypatch.setattr(routes,'settings',replace(routes.settings,pi_console_socket=str(socket),pi_console_token_file=str(secret)))
        try:
            with TestClient(app,raise_server_exceptions=False) as client:
                yield client,console,{k:v for k,v in packet.items() if k!='actor_id'},publisher
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

@pytest.mark.parametrize('identity,status',[('missing',401),('forged',401),('user',403),('admin',200)])
def test_real_roles_gate_socket_and_decisions(admin_data,connected_console,identity,status):
    users,*_=admin_data;client,console,packet,publisher=connected_console
    headers={} if identity=='missing' else {'X-Myink-User':str(users[0].id)} if identity=='forged' else bearer(users[identity=='user'])
    response=client.get(PREFIX+'/status',headers=headers)
    assert response.status_code==status,response.text
    assert response.headers['cache-control']=='no-store'
    packet['decision']='defer'
    decision=client.post(PREFIX+'/decisions',headers=headers,json=packet)
    assert decision.status_code==(202 if status==200 else status),decision.text
    assert publisher.calls==[] and console.gate.status()['phase']=='awaiting_approval'
    if status==200:
        assert decision.json()['actor_id']==str(users[0].id)
        runs=client.get(PREFIX+'/runs',headers=headers).json()
        assert runs['total']==1
        events=client.get(PREFIX+'/events',params={'run_id':'admin-'+packet['request_id']},headers=headers)
        assert events.status_code==200 and events.json()['total']==1
        assert str(console.root) not in events.text
        with new_session() as db:
            rows=list(db.scalars(select(AdminAccessLog).where(AdminAccessLog.actor_id==users[0].id)))
            assert any(row.action=='admin.pi.decision' and packet['request_id'] in row.target for row in rows)


def test_real_role_demotion_and_session_revocation_prevent_host_effects(admin_data,connected_console):
    users,*_=admin_data;client,console,packet,publisher=connected_console;headers=bearer(users[0])
    assert client.get(PREFIX+'/status',headers=headers).status_code==200
    with new_session() as db:
        db.get(User,users[0].id).role='user';db.commit()
    assert client.post(PREFIX+'/decisions',headers=headers,json=packet).status_code==403
    with new_session() as db:
        user=db.get(User,users[0].id);user.role='admin';user.auth_version+=1;db.commit()
    assert client.post(PREFIX+'/decisions',headers=headers,json=packet).status_code==401
    assert publisher.calls==[]
    with pytest.raises(LookupError):console.operation(packet['request_id'])


def test_real_socket_rejects_stale_candidate_and_audit_failure_before_publication(admin_data,connected_console,monkeypatch):
    client,console,packet,publisher=connected_console;headers=bearer(admin_data[0][0])
    stale=dict(packet,package_sha256='0'*64)
    assert client.post(PREFIX+'/decisions',headers=headers,json=stale).status_code==409
    def unavailable(*args,**kwargs):raise OSError('private audit failure')
    monkeypatch.setattr(routes,'write_access_log',unavailable)
    result=client.post(PREFIX+'/decisions',headers=headers,json=packet)
    assert result.status_code==503 and 'private audit failure' not in result.text
    assert publisher.calls==[] and console.gate.status()['phase']=='awaiting_approval'
