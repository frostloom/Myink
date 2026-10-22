"""Fixed Linux Pi runner and reverse loopback relay. No provider/client secrets."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler


def prepare_initial(initial):
    """Only trusted bounded frozen inputs, never provider or ledger settings."""
    import math
    import time
    from ops.pi.container_runtime import fixture, FRAME_LIMIT
    from ops.pi.analysis_execution import MODEL, prepare_contract_slots, _hash
    from ops.pi.analysis_trial import GROUPS
    if (not isinstance(initial,dict) or type(initial.get('slot_index')) is not int
            or not 0<=initial['slot_index']<30 or not isinstance(initial.get('token'),str)
            or len(initial['token'])!=64 or any(not 33<=ord(c)<=126 for c in initial['token'])
            or len(json.dumps(initial,ensure_ascii=True,allow_nan=False).encode())+1>FRAME_LIMIT):
        raise ValueError('bounded frozen slot required')
    if set(initial)=={'slot_index','token'} and initial['slot_index'] in (0,1):
        view,report=fixture().synthetic_inputs()
        deadline=time.time()+45
        slot=prepare_contract_slots({g:view for g in GROUPS},report,model=MODEL,cwd=Path('/work/candidate'))[initial['slot_index']]
    elif set(initial)=={'slot_index','token','slot','view','report','deadline'}:
        view,report,deadline,slot=(initial[k] for k in ('view','report','deadline','slot'))
        if (type(deadline) not in (int,float) or not math.isfinite(deadline)
                or not 0<deadline-time.time()<=90):
            raise ValueError('bounded absolute worker deadline required')
        expected=prepare_contract_slots({g:view for g in GROUPS},report,model=MODEL,cwd=Path('/work/candidate'))[initial['slot_index']]
        if _hash(expected)!=_hash(slot):raise ValueError('frozen worker input drift')
    else:raise ValueError('fixed worker fields required')
    return dict(initial,slot=slot,view=view,report=report,deadline=deadline,model=MODEL)


def main():
    sys.path.insert(0,'/source/code')
    from ops.pi.container_runtime import fixture, parse_frame, strict_json, FRAME_LIMIT
    from ops.pi.analysis_execution import MODEL, prepare_contract_slots, run_contract_slot
    from ops.pi.analysis_trial import GROUPS
    from ops.pi.pi_config import make_pi_config
    from ops.pi.pi_rpc import PiAdapter
    from ops.pi.engine import EngineSession
    from ops.pi.writing_analysis import SYSTEM_PROMPT
    from ops.pi.lab.container_probe_worker import network_denied
    from types import SimpleNamespace

    initial=prepare_initial(strict_json(sys.stdin.buffer.readline(FRAME_LIMIT+1)))
    def emit(value):
        raw=json.dumps(value,ensure_ascii=True,allow_nan=False)
        if len(raw.encode())>FRAME_LIMIT:raise ValueError('bounded relay frame required')
        print(raw,flush=True)
    class Relay(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.connection.settimeout(10)
            try:
                lengths=self.headers.get_all('Content-Length',[])
                if (len(lengths)!=1 or not lengths[0].isdigit() or not 0<int(lengths[0])<=65536
                        or self.headers.get('Transfer-Encoding')):
                    raise ValueError('bounded HTTP body required')
                body=self.rfile.read(int(lengths[0]))
                if len(body)!=int(lengths[0]):raise ValueError('truncated HTTP body')
                headers=[[k,v] for k,v in self.headers.raw_items() if k.lower() not in ('host','content-length')]
                frame=dict(type='request',path=self.path,headers=headers,body=body.decode())
                parse_frame(json.dumps(frame).encode());emit(frame)
                reply=strict_json(sys.stdin.buffer.readline(FRAME_LIMIT+1))
                if (not isinstance(reply,dict) or set(reply)!={'status','body'} or type(reply['status']) is not int
                        or reply['status'] not in (200,400,403,429,502) or not isinstance(reply['body'],str)
                        or len(reply['body'].encode())>65536):
                    raise ValueError('bounded gateway reply required')
                raw=reply['body'].encode()
                self.send_response(reply['status'])
                self.send_header('Content-Type','text/event-stream' if reply['status']==200 else 'text/plain')
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            except (ValueError,OSError,KeyError,TypeError) as exc:
                print('relay rejected: '+type(exc).__name__+': '+str(exc),file=sys.stderr,flush=True)
                self.send_error(400)
            finally:self.close_connection=True
    root=Path('/work');cwd=root/'candidate';cwd.mkdir()
    view,report=initial['view'],initial['report']
    index=initial['slot_index'];slot=initial['slot']
    server=HTTPServer(('127.0.0.1',0),Relay)
    thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    opener=build_opener(ProxyHandler({}))
    def negative(body,token):
        request=Request(base+'/v1/messages?beta=true',data=json.dumps(body).encode(),
            headers={'Content-Type':'application/json','x-api-key':token,'X-Pi-Scope':'local-trial-1'})
        try:
            with opener.open(request,timeout=10) as reply:return reply.status
        except HTTPError as exc:return exc.code
    try:
        if negative(slot['request'],'wrong')!=403 or negative(slot['request']|{'model':'foreign'},initial['token'])!=403:
            raise ValueError('gateway negative control failed')
        config=make_pi_config(root,dict(base_url=base,scope_token=initial['token']),SimpleNamespace(model=MODEL,max_tokens=2048))
        config['args']+=['--system-prompt',SYSTEM_PROMPT]
        for k,v in config['env'].items():
            if k not in ('PI_TELEMETRY','PI_OFFLINE','SCOPED_GATEWAY_TOKEN'):Path(v).mkdir(parents=True,exist_ok=True)
        agent=Path(config['env']['PI_CODING_AGENT_DIR'])
        for name,key in (('settings.json','settings'),('models.json','models')):(agent/name).write_text(json.dumps(config[key]))
        env=config['env']|{'PATH':'/source/node/bin:/usr/bin:/bin','LANG':'C.UTF-8',
            'NODE_DISABLE_COMPILE_CACHE':'1','NODE_OPTIONS':'--max-old-space-size=192'}
        env.pop('NODE_COMPILE_CACHE')
        digest=sha256(json.dumps({k:v for k,v in config.items() if k!='env'},sort_keys=True).encode()).hexdigest()
        cli=Path('/source/pi/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js')
        command=['/source/node/bin/node',str(cli),*config['args']]
        session=root/'sessions'/'analysis.jsonl'
        engine=PiAdapter(command,cwd=cwd,env=env,config_hash=digest)
        result=run_contract_slot(slot_index=index,slot=slot,view=view,report=report,engine=engine,
            session=EngineSession('pi',digest,'analysis',session),model=MODEL,cwd=cwd,
            deadline=datetime.fromtimestamp(initial['deadline'],timezone.utc))
        if result['engine_status']=='done':
            replay=negative(slot['request'],initial['token'])
            if replay!=403:raise ValueError('replay status '+str(replay))
        emit(dict(type='result',result=result,session=session.read_text() if session.exists() else '',
            runtime=dict(node=subprocess.check_output(['/source/node/bin/node','--version'],timeout=3).decode().strip(),
                pi=json.loads((cli.parents[2]/'package.json').read_text())['version'],uid=os.getuid(),
                machine=platform.machine(),network_denied=network_denied())))
    finally:server.shutdown();server.server_close();thread.join(2)


if __name__=='__main__':main()
