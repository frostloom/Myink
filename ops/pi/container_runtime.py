"""Fixed synthetic Linux Pi acceptance, never a provider or paid-run launcher.

The container has no external network. Bounded stdio frames carry only model
HTTP requests to a trusted host-selected loopback gateway with mock transport.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
from http.server import ThreadingHTTPServer
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import select
import stat
import subprocess
from threading import Thread
import time
import uuid

from .analysis_execution import MODEL, _hash, prepare_contract_slots
from .analysis_run import AnalysisRun
from .analysis_trial import GROUPS, score_contract_output
from .container_probe import ProbeHost, _path, _write, verify_inspect
from .ledger import Ledger

FRAME_LIMIT = 196608
INITIAL_FRAME_LIMIT = 524288  # One full trusted host report, including newline.
HEADER_NAMES = {'x-api-key','x-pi-scope','content-type','anthropic-version','anthropic-beta',
    'accept','accept-encoding','connection','user-agent','x-app','x-stainless-arch',
    'anthropic-dangerous-direct-browser-access','accept-language','sec-fetch-mode',
    'x-stainless-lang','x-stainless-os','x-stainless-package-version','x-stainless-retry-count',
    'x-stainless-runtime','x-stainless-runtime-version','x-stainless-timeout'}


def strict_json(raw):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out: raise ValueError('duplicate field')
            out[key]=value
        return out
    def invalid(_): raise ValueError('nonfinite JSON')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)


def parse_frame(raw):
    if not 0 < len(raw) <= FRAME_LIMIT: raise ValueError('bounded frame required')
    f=strict_json(raw)
    if not isinstance(f,dict): raise ValueError('object frame required')
    if f.get('type')=='request':
        if (set(f)!={'type','path','headers','body'} or f['path'] not in ('/v1/messages','/v1/messages?beta=true')
                or not isinstance(f['body'],str) or not 0<len(f['body'].encode())<=65536
                or not isinstance(f['headers'],list) or not 1<=len(f['headers'])<=32):
            raise ValueError('fixed bounded model route required')
        for pair in f['headers']:
            if (not isinstance(pair,list) or len(pair)!=2 or any(not isinstance(v,str) for v in pair)
                    or pair[0].lower() not in HEADER_NAMES or len(pair[1])>4096
                    or any(ord(c)<32 or ord(c)>126 for c in ''.join(pair))):
                raise ValueError('invalid relay header')
    elif f.get('type')=='result':
        if set(f)!={'type','result','session','runtime'} or not isinstance(f['result'],dict) or not isinstance(f['session'],str) or not isinstance(f['runtime'],dict):
            raise ValueError('complete private result required')
    else: raise ValueError('unknown frame')
    return f


def exchange(process, initial, route, *, seconds, evidence=None):
    """One bounded attach lifetime. Caller must stop the container in finally."""
    if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<seconds<=90:
        raise ValueError('bounded execution deadline required')
    deadline=time.monotonic()+seconds
    def remaining():
        n=deadline-time.monotonic()
        if n<=0: raise TimeoutError('container execution expired')
        return n
    def write(value, limit=FRAME_LIMIT):
        raw=json.dumps(value,ensure_ascii=True,allow_nan=False).encode()+b'\n'
        if len(raw)>limit: raise ValueError('bounded reply required')
        offset=0
        while offset<len(raw):
            _,ready,_=select.select([],[process.stdin],[],remaining())
            if not ready: raise TimeoutError('container input stalled')
            offset+=os.write(process.stdin.fileno(),raw[offset:offset+4096])
    os.set_blocking(process.stdin.fileno(),False)
    os.set_blocking(process.stdout.fileno(),False)
    write(initial, INITIAL_FRAME_LIMIT)
    pending=bytearray(); total=0; requests=0; final=None
    while True:
        ready,_,_=select.select([process.stdout],[],[],remaining())
        if not ready: raise TimeoutError('container output stalled')
        chunk=os.read(process.stdout.fileno(),4096)
        if not chunk: break
        if evidence is not None: evidence.write(chunk[:max(0,1048576-total)])
        pending.extend(chunk); total+=len(chunk)
        if total>1048576: raise ValueError('container output overflow')
        while b'\n' in pending:
            line,_,rest=pending.partition(b'\n');pending=bytearray(rest)
            f=parse_frame(line)
            if final is not None: raise ValueError('output after result')
            if f['type']=='request':
                requests+=1
                if requests>4: raise ValueError('relay request limit')
                response=route(f,remaining())
                remaining()
                write(response)
            else: final=f
        if len(pending)>FRAME_LIMIT: raise ValueError('container frame overflow')
    if pending or final is None: raise ValueError('incomplete container result')
    try: code=process.wait(timeout=remaining())
    except subprocess.TimeoutExpired: raise TimeoutError('container attach did not exit') from None
    if code!=0: raise ValueError('container process failed')
    return final


def fixture():
    path=Path(__file__).parent/'lab/pi-analysis-contract-probe.py'
    spec=importlib.util.spec_from_file_location('synthetic_contract_fixture',path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def synthetic_run(root):
    """Fresh isolated mock ledger only; no caller policy, ledger or transport."""
    from dataclasses import replace
    from .policy import load_policy
    from . import budget
    from .trial_runtime import ensure_phase_fence
    root=_path(root)
    if root.exists(): raise ValueError('new synthetic ledger directory required')
    root.mkdir(mode=0o700)
    p=replace(load_policy(Path(__file__).with_name('policy.example.json')),schema_version=2,
        max_attempts=None,budget_microyuan=20000000,base_url='https://provider.invalid',model=MODEL,
        live_enabled=False,input_token_bound=1000,input_bound_source='synthetic only',
        input_bound_calibrated=False,max_tokens=2048,timeout_seconds=60,
        price_source='synthetic only',prices=dict(input='2',output='8',cache_read='0.2',cache_write='3'))
    ledger=Ledger(root/'ledger.sqlite')
    ledger.intent('model-scope:local-trial-1','model-scope',dict(max_attempts=100,budget_microyuan=10000000))
    ensure_phase_fence(ledger)
    budget.amend_local_trial_budget(ledger,'local-trial-1',operation_id='synthetic-amendment',
        expected_original_microyuan=10000000,expected_effective_microyuan=10000000,
        budget_microyuan=20000000,authorization_reference='synthetic-fixture-only',approved=True)
    budget.amend_local_trial_budget_v2(ledger,'local-trial-1',operation_id='synthetic-fee-only',
        expected_original_microyuan=10000000,expected_effective_microyuan=20000000,
        expected_effective_max_attempts=100,budget_microyuan=20000000,max_attempts=None,
        phase_allocations=None,authorization_reference='synthetic-fixture-only',approved=True)
    view,report=fixture().synthetic_inputs()
    slots=prepare_contract_slots({g:view for g in GROUPS},report,model=MODEL,cwd=Path('/work/candidate'))
    run=AnalysisRun.create(ledger,'synthetic-container',slots,source_sha256=_hash(view),config_sha256=_hash(slots))
    run.bind_budget(p,cap_microyuan=100000,deadline=time.time()+180)
    return run,p,slots,view,report,[]


def mock_transport(calls):
    import httpx
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            answer=json.dumps(fixture().synthetic_answer(),ensure_ascii=False)
            events=[dict(type='message_start',message=dict(id='synthetic-container',type='message',
                role='assistant',model=MODEL,content=[],stop_reason=None,stop_sequence=None,
                usage=dict(input_tokens=17,output_tokens=0,cache_read_input_tokens=0,cache_creation_input_tokens=0))),
                dict(type='content_block_start',index=0,content_block=dict(type='text',text='')),
                dict(type='content_block_delta',index=0,delta=dict(type='text_delta',text=answer)),
                dict(type='content_block_stop',index=0),
                dict(type='message_delta',delta=dict(stop_reason='end_turn',stop_sequence=None),usage=dict(output_tokens=100)),
                dict(type='message_stop')]
            for e in events: yield ('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n').encode()
    def handler(req):
        calls.append(sha256(req.content).hexdigest())
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())
    client=httpx.Client(transport=httpx.MockTransport(handler),trust_env=False)
    def send(body,timeout):
        request=client.build_request('POST','https://provider.invalid/v1/messages',json=body,timeout=timeout)
        return client.send(request,stream=True)
    return send,client


def verify_result(frame, slot, view, report):
    """Host validates private session bytes and analysis, not a worker passed flag."""
    r=frame.get('result',{});e=r.get('evidence',{})
    if (r.get('engine_status')!='done' or r.get('contract_valid') is not True
            or any(r.get(k)!=slot.get(k) for k in ('slot_id','request_sha256','system_sha256','prompt_sha256','view_sha256','report_sha256'))
            or any(e.get(k) is not True for k in ('session_valid','process_exited','clear_abort_acknowledged'))
            or e.get('returncode')!=0 or e.get('unexpected_tool') is not False
            or e.get('verified_tool_calls')!=[] or e.get('pending_tool_calls')!=[]):
        raise ValueError('invalid engine evidence')
    score_contract_output(r['analysis'],view,slot['domain'])
    raw=frame['session'].encode()
    if not 0<len(raw)<=65536 or sha256(raw).hexdigest()!=e.get('session_sha256'):
        raise ValueError('session fingerprint mismatch')
    rows=[strict_json(line) for line in raw.splitlines()]
    if rows[0].get('type')!='session' or rows[0].get('cwd')!='/work/candidate' or not isinstance(rows[0].get('id'),str):
        raise ValueError('fresh session identity required')
    assistants=[]
    for row in rows:
        message=row.get('message',{})
        if message.get('role')=='toolResult': raise ValueError('tools forbidden')
        if message.get('role')=='assistant':
            content=message.get('content',[])
            if not content or any(b.get('type')!='text' for b in content): raise ValueError('pure text required')
            assistants.append(message)
    if len(assistants)!=1 or assistants[0].get('stopReason')!='stop' or strict_json(''.join(b['text'] for b in assistants[0]['content']))!=r['analysis']:
        raise ValueError('analysis/session mismatch')
    runtime=frame['runtime']
    if (runtime.get('node')!='v24.22.0' or runtime.get('pi')!='1.1.0' or runtime.get('uid')!=65534
            or runtime.get('machine')!='aarch64' or runtime.get('network_denied') is not True):
        raise ValueError('runtime boundary mismatch')
    return dict(slot_id=slot['slot_id'],contract_valid=True,session_sha256=e['session_sha256'],
                session_id=rows[0]['id'],process_exited=True,returncode=0,request_sha256=slot['request_sha256'],runtime=runtime)


def runtime_fingerprint(source):
    source=_path(source)
    entries={}
    for folder in (source/'node',source/'pi'):
        if not folder.is_dir() or folder.is_symlink(): raise ValueError('fixed runtime directories required')
        for path in sorted(folder.rglob('*')):
            if len(entries)>50000: raise ValueError('runtime file limit')
            key=path.relative_to(source).as_posix()
            mode=path.lstat().st_mode
            if not any(test(mode) for test in (stat.S_ISREG,stat.S_ISDIR,stat.S_ISLNK)):
                raise ValueError('special runtime file forbidden')
            if path.is_symlink():
                if (not path.resolve().is_relative_to(source.resolve())
                        or not (path.resolve().is_file() or path.resolve().is_dir())):
                    raise ValueError('escaping or special runtime link')
                entries[key]={'link':os.readlink(path)}
            elif path.is_file(): entries[key]=sha256(path.read_bytes()).hexdigest()
    return _hash(entries)


def verify_source(source, expected):
    if not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected):
        raise ValueError('trusted runtime fingerprint required')
    if {p.name for p in source.iterdir()}!={'node','pi','code'}:
        raise ValueError('closed bind source root required')
    actual=runtime_fingerprint(source)
    if actual!=expected: raise ValueError('runtime dependency drift')
    original=Path(__file__).parent
    def files(root):
        return {p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not p.is_symlink()
            and 'tests' not in p.relative_to(root).parts and '__pycache__' not in p.relative_to(root).parts}
    code=_path(source/'code')
    copied=_path(code/'ops'/'pi')
    paths=list(code.rglob('*'))
    if (not copied.is_dir() or any(not (p.is_file() or p.is_dir()) or p.is_symlink() or p.suffix in ('.pyc','.pyo')
            or '__pycache__' in p.parts for p in paths)):
        raise ValueError('closed source tree without links or bytecode required')
    # sys.path contains code, so its entire import closure is pinned, including
    # namespace package parents and modules that could shadow standard imports.
    code_files={p.relative_to(code).as_posix():sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
    expected={'ops/pi/'+key:value for key,value in files(original).items()}
    if code_files!=expected: raise ValueError('controller source snapshot drift')
    node=(source/'node/bin/node').read_bytes()
    if node[:4]!=b'\x7fELF' or int.from_bytes(node[18:20],'little')!=183:
        raise ValueError('Linux ARM64 Node required')
    package=source/'pi/node_modules/@earendil-works/pi-coding-agent'
    if json.loads((package/'package.json').read_text()).get('version')!='1.1.0':
        raise ValueError('fixed Pi version required')
    return dict(runtime_sha256=actual,node_sha256=sha256(node).hexdigest(),
        lock_sha256=sha256((source/'pi/package-lock.json').read_bytes()).hexdigest(),
        pi_cli_sha256=sha256((package/'dist/bundle/cli.js').read_bytes()).hexdigest(),
        code_sha256=_hash(code_files),controller_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        worker_sha256=sha256((original/'lab/container_runtime_worker.py').read_bytes()).hexdigest())


def run_probe(root, source, *, docker, endpoint, daemon_id, image_id, runtime_sha256):
    import httpx
    from .budget import totals
    root,source=_path(root),_path(source)
    if root.exists(): raise ValueError('new evidence root required')
    provenance=verify_source(source,runtime_sha256)
    root.mkdir(mode=0o700)
    run,p,slots,view,report,calls=synthetic_run(root/'synthetic-ledger')
    host=ProbeHost(docker=docker,endpoint=endpoint,daemon_id=daemon_id,image_id=image_id,operation_id=str(uuid.uuid4()))
    result=dict(status='blocked',operation_id=host.operation_id,daemon_id=daemon_id,image_id=image_id,
        paid_requests=0,production_ready=False,automatic_execution=False,pi_runtime_verified=False,
        canonical_ledger_modified=False,provenance=provenance,planned_slots=30,selected_probe_slots=2,cases=[],cleanup=[],failure_class=None)
    send,provider=mock_transport(calls)
    try:
        for index,slot in enumerate(slots[:2]):
            row=dict(slot_index=index,slot_id=slot['slot_id'],passed=False,http_statuses=[])
            result['cases'].append(row)
            token=uuid.uuid4().hex+uuid.uuid4().hex
            handler=run.gateway_handler(index,p,send,scope_token=token)
            with ThreadingHTTPServer(('127.0.0.1',0),handler) as server:
                server.daemon_threads=True
                thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
                process=None
                try:
                    cid=host.create('isolation',worker=Path(__file__).parent/'lab/container_runtime_worker.py',
                        source=source,foreign=root/'not-mounted',interactive=True)
                    if not verify_inspect(host.inspect(cid)): raise ValueError('container hardening mismatch')
                    process=subprocess.Popen(host.command+['start','-a','-i',cid],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT)
                    with httpx.Client(trust_env=False,follow_redirects=False) as client:
                        def route(f,remaining):
                            with client.stream('POST',f'http://127.0.0.1:{server.server_port}'+f['path'],
                                    headers=f['headers'],content=f['body'].encode(),timeout=remaining) as reply:
                                body=bytearray()
                                for chunk in reply.iter_bytes():
                                    body.extend(chunk)
                                    if len(body)>65536: raise ValueError('gateway reply overflow')
                                row['http_statuses'].append(reply.status_code)
                                return dict(status=reply.status_code,body=body.decode())
                        with (root/f'slot-{index}-attach-private.log').open('xb') as evidence:
                            frame=exchange(process,dict(slot_index=index,token=token),route,seconds=60,evidence=evidence)
                    _write(root/f'slot-{index}-private.json',frame)
                    row.update(verify_result(frame,slot,view,report))
                    if row['http_statuses']!=[403,403,200,403] or totals(run.ledger,'local-trial-1')[0]!=index+1:
                        raise ValueError('single metered request or rejection mismatch')
                    with run.ledger.transaction() as db:
                        attempts=list(db.execute("SELECT status FROM operations WHERE kind='model-attempt'"))
                        if any(r['status']!='done' for r in attempts): raise ValueError('unknown mock settlement')
                    cleaned=host.cleanup(cid);result['cleanup'].append(cleaned)
                    if cleaned['exit_code']!=0: raise ValueError('container did not exit cleanly')
                    run.finish(index,status='done');row['passed']=True
                finally:
                    if process is not None:
                        try:
                            if process.poll() is None: host.stop(cid)
                        finally:
                            if process.poll() is None: process.kill()
                            process.wait(timeout=3)
                            process.stdin.close();process.stdout.close()
                    server.shutdown();thread.join(2)
            # One fixed purpose per operation identity; exact cleanup completed before reuse.
        if len({c['session_id'] for c in result['cases']})!=2: raise ValueError('sessions not fresh')
        result['status']='passed';result['pi_runtime_verified']=True
    except Exception as exc:
        result['failure_class']=type(exc).__name__
        _write(root/'failure-private.json',dict(error=str(exc)))
    finally:
        try:host.reconcile()
        except Exception as exc:result['failure_class']=type(exc).__name__
        for name,mode in host.pending.items():
            result['cleanup'].append(dict(name=name,mode=mode,removed=False,operation_id=host.operation_id))
        for cid in list(host.owned):
            try:result['cleanup'].append(host.cleanup(cid))
            except Exception as exc:result['cleanup'].append(dict(container_id=cid,removed=False,failure_class=type(exc).__name__))
        if any(not c.get('removed') for c in result['cleanup']):result['status']='blocked'
        result.update(slots=run.snapshot(),mock_attempts=totals(run.ledger,'local-trial-1')[0],
            mock_accounted_microyuan=totals(run.ledger,'local-trial-1')[1],mock_transport_calls=len(calls))
        if result['status']!='passed':result['pi_runtime_verified']=False
        provider.close()
        _write(root/'receipt.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','source','docker'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('endpoint','daemon-id','image-id','runtime-sha256'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    result=run_probe(**vars(args));print(json.dumps(result));return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
