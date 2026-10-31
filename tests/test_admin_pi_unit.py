"""Console route authorization/auditing, without a database or provider call."""
from copy import deepcopy
from types import SimpleNamespace
import uuid
import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from myink.api.main import app
from myink.api.auth import require_admin
from myink.api import routes_admin_pi as routes
from ops.pi.tests.test_admin_console import console_case, bundle_case, finished, stopped, completed, config_file

PREFIX='/api/v1/admin/pi'


@pytest.fixture
def api_console(console_case,monkeypatch):
    console,packet,publisher,case=console_case;actor=uuid.uuid4();calls=[];state={'revoked':False,'audit_broken':False,'host_broken':False}
    def authenticate(request:Request):
        value=request.headers.get('Authorization')
        if value!='Bearer unit-admin':raise HTTPException(403 if value else 401,'FORBIDDEN')
        if state['revoked']:raise HTTPException(403,'FORBIDDEN')
        return SimpleNamespace(id=actor)
    def log(actor_id,action,target):
        if state['audit_broken']:raise OSError('audit unavailable')
        calls.append(('audit',str(actor_id),action,target))
    class Host:
        def call(self,method,path,*,params=None,body=None):
            calls.append(('host',method,path,params,deepcopy(body)))
            if state['host_broken']:
                from myink.pi_console import PiConsoleUnavailable
                raise PiConsoleUnavailable()
            if path=='/v1/status':return dict(console.status(),mode='SIMULATED',executor=dict(service_state='simulated',timer_state='simulated',last_result=None,next_check=None))
            if path=='/v1/decisions':
                from myink.pi_console import PiConsoleConflict
                try:return console.submit(body)
                except ValueError as error:raise PiConsoleConflict() from error
            if path.startswith('/v1/operations/'):return console.operation(path.rsplit('/',1)[-1])
            return {'items':[],'total':0,'limit':params.get('limit',25),'offset':params.get('offset',0)}
    monkeypatch.setattr(routes,'write_access_log',log);monkeypatch.setattr(routes,'_console',lambda:Host());app.dependency_overrides[require_admin]=authenticate
    client=TestClient(app,raise_server_exceptions=False)
    try:yield client,console,{k:v for k,v in packet.items() if k!='actor_id'},actor,calls,state
    finally:client.close();app.dependency_overrides.pop(require_admin,None)


@pytest.mark.parametrize('header,status',[({},401),({'Authorization':'Bearer unit-user'},403)])
@pytest.mark.parametrize('method,path',[('get','/status'),('post','/decisions')])
def test_authorization_precedes_any_console_data_or_command(api_console,header,status,method,path):
    client,console,body,actor,calls,state=api_console;response=getattr(client,method)(PREFIX+path,headers=header,**({'json':body} if method=='post' else {}))
    assert response.status_code==status and response.headers['cache-control']=='no-store' and calls==[]


def test_admin_status_is_audited_and_excludes_private_files(api_console):
    client,console,body,actor,calls,state=api_console;response=client.get(PREFIX+'/status',headers={'Authorization':'Bearer unit-admin'})
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert response.json()['phase']=='awaiting_approval' and response.json()['candidate']['evaluation']['online_improvement_proven'] is False
    assert calls[0][0]=='audit' and calls[1][0]=='host' and str(console.root) not in response.text


def test_defer_uses_verified_actor_and_audits_candidate_request_ids(api_console):
    client,console,body,actor,calls,state=api_console;body['decision']='defer';response=client.post(PREFIX+'/decisions',json=body,headers={'Authorization':'Bearer unit-admin'})
    assert response.status_code==202 and response.json()['status']=='deferred'
    assert calls[0][0]=='audit' and body['cycle_id'] in calls[0][3] and body['request_id'] in calls[0][3]
    assert calls[1][4]['actor_id']==str(actor) and console.gate.status()['phase']=='awaiting_approval'


def test_body_cannot_supply_actor_paths_or_arbitrary_commands(api_console):
    client,console,body,actor,calls,state=api_console
    response=client.post(PREFIX+'/decisions',json=dict(body,actor_id=str(uuid.uuid4()),command='arbitrary'),headers={'Authorization':'Bearer unit-admin'})
    assert response.status_code==422 and not any(c[0]=='host' for c in calls)


def test_audit_failure_prevents_even_status_calls(api_console):
    client,console,body,actor,calls,state=api_console;state['audit_broken']=True
    for method,path in [('get','/status'),('post','/decisions')]:
        response=getattr(client,method)(PREFIX+path,headers={'Authorization':'Bearer unit-admin'},**({'json':body} if method=='post' else {}));assert response.status_code==503
    assert not any(c[0]=='host' for c in calls)


def test_host_unavailable_is_never_an_empty_success(api_console):
    client,console,body,actor,calls,state=api_console;state['host_broken']=True;response=client.get(PREFIX+'/status',headers={'Authorization':'Bearer unit-admin'})
    assert response.status_code==503 and 'PI_CONSOLE' in response.json()['detail'] and response.headers['cache-control']=='no-store'


def test_old_candidate_requires_refresh_instead_of_an_approval(api_console):
    client,console,body,actor,calls,state=api_console;body['package_sha256']='0'*64;response=client.post(PREFIX+'/decisions',json=body,headers={'Authorization':'Bearer unit-admin'})
    assert response.status_code==409 and console.gate.status()['phase']=='awaiting_approval'


@pytest.mark.parametrize('suffix',['/runs?limit=101','/runs?offset=-1','/daily?day=not-a-date','/operations/not-a-uuid','/events?run_id=valid&kind=arbitrary'])
def test_invalid_filter_values_are_rejected_without_host_calls(api_console,suffix):
    client,console,body,actor,calls,state=api_console;response=client.get(PREFIX+suffix,headers={'Authorization':'Bearer unit-admin'})
    assert response.status_code==422 and not any(c[0]=='host' for c in calls)


def test_role_revocation_is_checked_again_before_returning_previous_data(api_console):
    client,console,body,actor,calls,state=api_console;headers={'Authorization':'Bearer unit-admin'};assert client.get(PREFIX+'/status',headers=headers).status_code==200;calls.clear();state['revoked']=True
    assert client.get(PREFIX+'/status',headers=headers).status_code==403 and calls==[]
