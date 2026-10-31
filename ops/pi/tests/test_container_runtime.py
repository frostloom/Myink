"""No Docker required: actual local stdio children, loopback HTTP and SQLite."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time

import httpx
import pytest


def api():
    assert importlib.util.find_spec('ops.pi.container_runtime'), 'container runtime bridge missing'
    return importlib.import_module('ops.pi.container_runtime')


@pytest.mark.parametrize('raw',[b'{}',b'{"type":"request","url":"http://foreign"}',b'{"type":"result","result":{}}',
    b'{"type":"request","type":"result"}',b'[]',b'NaN',b'x'*196609],ids=['empty','url','false-result','duplicate','array','nan','oversize'])
def test_untrusted_protocol_frames_fail_closed(raw):
    with pytest.raises(ValueError):api().parse_frame(raw)


def test_exact_http_request_preserves_duplicate_auth_headers():
    frame=dict(type='request',path='/v1/messages?beta=true',headers=[['x-api-key','a'],['x-api-key','b']],body='{}')
    assert api().parse_frame(json.dumps(frame).encode())==frame


@pytest.mark.parametrize('change',[dict(path='http://foreign/v1/messages'),dict(path='/v1/tools'),dict(body='x'*65537),
    dict(headers=[['x-api-key','a\r\nb']]),dict(headers=[['host','foreign']]),dict(method='GET')])
def test_relay_refuses_url_tools_framing_and_header_injection(change):
    frame=dict(type='request',path='/v1/messages',headers=[['x-api-key','a']],body='{}')|change
    with pytest.raises(ValueError):api().parse_frame(json.dumps(frame).encode())


def test_real_child_eof_without_result_is_not_success():
    child=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.readline()'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        with pytest.raises((ValueError,EOFError)):api().exchange(child,{},lambda f,s:None,seconds=.5)
    finally:child.kill();child.wait()


def test_real_child_stall_is_bounded():
    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(3)'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    started=time.monotonic()
    try:
        with pytest.raises(TimeoutError):api().exchange(child,{},lambda f,s:None,seconds=.1)
        assert time.monotonic()-started<1
    finally:child.kill();child.wait()


def test_false_container_success_is_rejected_on_host():
    with pytest.raises(ValueError):api().verify_result(dict(passed=True),{}, {}, {})


def test_synthetic_run_is_fresh_private_and_has_no_provider_network(tmp_path,monkeypatch):
    m=api()
    monkeypatch.setenv('PLATFORM_MODEL_API_KEY','synthetic-never-use')
    run,p,slots,view,report,calls=m.synthetic_run(tmp_path/'new')
    assert len(slots)==30 and len(run.snapshot())==30
    assert not p.live_enabled and p.base_url=='https://provider.invalid'
    assert run.ledger.path.parent==tmp_path/'new'
    assert calls==[]
    with pytest.raises(ValueError):m.synthetic_run(tmp_path/'new')


def test_fixed_worker_imports_without_site_packages():
    path=Path(__file__).parents[1]/'lab/container_runtime_worker.py'
    assert path.is_file(), 'fixed Linux Pi worker missing'
    result=subprocess.run([sys.executable,'-I','-S','-c',
        'import runpy;runpy.run_path('+repr(str(path))+',run_name="import_only")'],capture_output=True,timeout=3)
    assert result.returncode==0,result.stderr.decode()


def test_real_child_full_exchange_preserves_gateway_rejection():
    script='''import sys,json
initial=json.loads(sys.stdin.readline())
print(json.dumps(dict(type='request',path='/v1/messages',headers=[['x-api-key','wrong']],body='{}')),flush=True)
reply=json.loads(sys.stdin.readline())
print(json.dumps(dict(type='result',result=reply,session='',runtime={})),flush=True)
'''
    child=subprocess.Popen([sys.executable,'-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        result=api().exchange(child,{},lambda f,s:dict(status=403,body='denied'),seconds=2)
        assert result['result']['status']==403
    finally:
        child.kill();child.wait();child.stdin.close();child.stdout.close()


def test_actual_gateway_rejects_wrong_token_drift_replay_and_settles_mock(tmp_path):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from ops.pi.budget import totals
    m=api();run,p,slots,view,report,calls=m.synthetic_run(tmp_path/'mock')
    send,client=m.mock_transport(calls)
    token='x'*64
    with ThreadingHTTPServer(('127.0.0.1',0),run.gateway_handler(0,p,send,scope_token=token)) as server:
        worker=Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
        try:
            with httpx.Client(trust_env=False,timeout=2) as http:
                url=f'http://127.0.0.1:{server.server_port}/v1/messages'
                headers={'x-api-key':token,'X-Pi-Scope':'local-trial-1'}
                assert http.post(url,headers=headers|{'x-api-key':'wrong'},json=slots[0]['request']).status_code==403
                assert http.post(url,headers=headers,json=slots[0]['request']|{'model':'foreign'}).status_code==403
                assert totals(run.ledger,'local-trial-1')==(0,0) and calls==[]
                assert http.post(url,headers=headers,json=slots[0]['request']).status_code==200
                assert http.post(url,headers=headers,json=slots[0]['request']).status_code==403
                assert len(calls)==1 and totals(run.ledger,'local-trial-1')==(1,834)
        finally:server.shutdown();worker.join(2);client.close()


@pytest.mark.parametrize('name',['anthropic-dangerous-direct-browser-access','accept-language','sec-fetch-mode'])
def test_pinned_pi_sdk_context_headers_are_supported(name):
    frame=dict(type='request',path='/v1/messages',headers=[[name,'synthetic']],body='{}')
    assert api().parse_frame(json.dumps(frame).encode())==frame


def valid_result(tmp_path):
    m=api();run,p,slots,view,report,calls=m.synthetic_run(tmp_path/'run')
    answer=m.fixture().synthetic_answer()
    session='\n'.join(json.dumps(x) for x in [dict(type='session',id='fresh',cwd='/work/candidate'),
        dict(type='message',message=dict(role='assistant',stopReason='stop',content=[dict(type='text',text=json.dumps(answer))]))])+'\n'
    from hashlib import sha256
    slot=slots[0]
    result={k:slot[k] for k in ('slot_id','request_sha256','system_sha256','prompt_sha256','view_sha256','report_sha256')}
    result.update(engine_status='done',contract_valid=True,analysis=answer,evidence=dict(
        session_valid=True,process_exited=True,clear_abort_acknowledged=True,returncode=0,
        unexpected_tool=False,verified_tool_calls=[],pending_tool_calls=[],session_sha256=sha256(session.encode()).hexdigest()))
    frame=dict(type='result',result=result,session=session,runtime=dict(node='v24.22.0',pi='1.1.0',uid=65534,machine='aarch64',network_denied=True))
    return frame,slot,view,report


def test_host_revalidates_valid_frozen_session(tmp_path):
    frame,slot,view,report=valid_result(tmp_path)
    assert api().verify_result(frame,slot,view,report)['contract_valid'] is True


@pytest.mark.parametrize('change',['analysis','hash','tool','request','runtime'])
def test_host_rejects_container_claim_drift(tmp_path,change):
    frame,slot,view,report=valid_result(tmp_path)
    if change=='analysis':frame['result']['analysis']['hypothesis']['refs'][0]['quote']='invented'
    elif change=='hash':frame['session']+='{}\n'
    elif change=='tool':frame['result']['evidence']['verified_tool_calls']=['fake']
    elif change=='request':frame['result']['request_sha256']='x'*64
    else:frame['runtime']['network_denied']=False
    with pytest.raises(ValueError):api().verify_result(frame,slot,view,report)


def test_runtime_manifest_tracks_mutation_and_refuses_escaping_links(tmp_path):
    m=api();root=tmp_path/'runtime';root.mkdir();(root/'node').mkdir();(root/'pi').mkdir()
    file=root/'node'/'canary';file.write_text('fixed')
    first=m.runtime_fingerprint(root)
    file.write_text('changed');assert m.runtime_fingerprint(root)!=first
    (root/'pi'/'bad').symlink_to('/etc/passwd')
    with pytest.raises(ValueError):m.runtime_fingerprint(root)


@pytest.mark.parametrize('tail',["print('x'*196609,flush=True)","print('{}',flush=True)","print('{\\\"type\\\":\\\"request\\\",\\\"path\\\":\\\"/v1/tools\\\"}',flush=True)"])
def test_exchange_rejects_real_child_invalid_or_overflow_frames(tail):
    child=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.readline();'+tail],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        with pytest.raises(ValueError):api().exchange(child,{},lambda f,s:None,seconds=2)
    finally:child.kill();child.wait();child.stdin.close();child.stdout.close()


def test_insufficient_run_budget_never_calls_mock_transport(tmp_path,monkeypatch):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from ops.pi.analysis_run import AnalysisRun
    from ops.pi.budget import totals
    original=AnalysisRun.bind_budget
    monkeypatch.setattr(AnalysisRun,'bind_budget',lambda self,p,**kw:original(self,p,cap_microyuan=1,deadline=kw['deadline']))
    m=api();run,p,slots,view,report,calls=m.synthetic_run(tmp_path/'low')
    send,client=m.mock_transport(calls)
    with ThreadingHTTPServer(('127.0.0.1',0),run.gateway_handler(0,p,send,scope_token='x'*64)) as server:
        worker=Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
        try:
            with httpx.Client(trust_env=False,timeout=2) as http:
                r=http.post(f'http://127.0.0.1:{server.server_port}/v1/messages',
                    headers={'x-api-key':'x'*64,'X-Pi-Scope':'local-trial-1'},json=slots[0]['request'])
                assert r.status_code==429
            assert totals(run.ledger,'local-trial-1')==(0,0) and calls==[]
            assert run.snapshot()[0]['status']=='UNCERTAIN'
        finally:server.shutdown();worker.join(2);client.close()


def test_bounded_attach_log_keeps_failed_raw_prefix():
    import io
    sink=io.BytesIO()
    child=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.readline();print("untrusted failure",flush=True)'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        with pytest.raises(ValueError):api().exchange(child,{},lambda f,s:None,seconds=2,evidence=sink)
        assert sink.getvalue()==b'untrusted failure\n'
    finally:child.kill();child.wait();child.stdin.close();child.stdout.close()


def source_fixture(tmp_path,monkeypatch):
    import shutil
    m=api();original=tmp_path/'host';(original/'lab').mkdir(parents=True)
    (original/'container_runtime.py').write_text('trusted controller')
    (original/'lab/container_runtime_worker.py').write_text('trusted worker')
    monkeypatch.setattr(m,'__file__',str(original/'container_runtime.py'))
    source=tmp_path/'source';(source/'node/bin').mkdir(parents=True)
    node=bytearray(64);node[:7]=b'\x7fELF\x02\x01\x01'
    node[16:18]=(2).to_bytes(2,'little');node[18:20]=(183).to_bytes(2,'little')
    node[20:24]=(1).to_bytes(4,'little');node[52:54]=(64).to_bytes(2,'little')
    (source/'node/bin/node').write_bytes(node)
    package=source/'pi/node_modules/@earendil-works/pi-coding-agent';(package/'dist/bundle').mkdir(parents=True)
    (package/'package.json').write_text('{"version":"1.1.0"}')
    (package/'dist/bundle/cli.js').write_text('trusted Pi')
    (source/'pi/package-lock.json').write_text('{}')
    shutil.copytree(original,source/'code/ops/pi')
    return source,m.runtime_fingerprint(source)


@pytest.mark.parametrize('extra',['ops/__init__.py','json.py','ops/pi/__pycache__/container_runtime.cpython-312.pyc'])
def test_code_closure_rejects_unhashed_imports_and_bytecode(tmp_path,monkeypatch,extra):
    source,digest=source_fixture(tmp_path,monkeypatch)
    assert api().verify_source(source,digest)['runtime_sha256']==digest
    path=source/'code'/extra;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('untrusted')
    with pytest.raises(ValueError):api().verify_source(source,digest)


@pytest.mark.parametrize('where',['root-file','root-socket','runtime-socket'])
def test_entire_bind_source_rejects_extra_roots_and_host_sockets(tmp_path,monkeypatch,where):
    import socket
    import tempfile
    with tempfile.TemporaryDirectory(prefix='pi-',dir=Path('/tmp').resolve()) as short:
        source,digest=source_fixture(Path(short),monkeypatch)
        assert api().verify_source(source,digest)['runtime_sha256']==digest
        if where=='root-file':
            (source/'private-canary').write_text('must never enter container')
            with pytest.raises(ValueError):api().verify_source(source,digest)
        else:
            endpoint=source/('host.sock' if where=='root-socket' else 'pi/host.sock')
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(endpoint))
                with pytest.raises(ValueError):api().verify_source(source,digest)
