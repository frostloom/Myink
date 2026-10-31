"""Fixed one-session bridge: network-none Pi; all authority remains in host broker."""
import json, os, sys, time, threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen, build_opener, ProxyHandler
from datetime import datetime, timezone
from dataclasses import asdict
sys.path.insert(0,'/source/code')
from ops.pi.pi_config import make_pi_config
from ops.pi.pi_rpc import PiAdapter
from ops.pi.engine import AdministratorContext, EngineSession
from ops.pi.lab.container_probe_worker import network_denied
from types import SimpleNamespace
initial=json.loads(sys.stdin.buffer.readline(262145))
lock=threading.Lock()
def relay(path,headers,body):
    with lock:
        print(json.dumps(dict(type='request',path=path,headers=headers,body=body)),flush=True)
        raw=sys.stdin.buffer.readline(1048577)
        value=json.loads(raw)
        if set(value)!={'status','body'} or len(value['body'].encode())>524288:
            raise ValueError('invalid relay response')
        return value
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def do_POST(self):
        try:
            n=self.headers.get('Content-Length','')
            if not n.isdigit() or not 0<int(n)<=65536 or self.headers.get('Transfer-Encoding'):
                raise ValueError('invalid request length')
            self.connection.settimeout(70)
            raw=self.rfile.read(int(n))
            if len(raw)!=int(n): raise ValueError('short request')
            headers=[[k,v] for k,v in self.headers.raw_items() if k.lower() not in ('host','content-length')]
            value=relay(self.path,headers,raw.decode())
            self.send_response(value['status']);self.send_header('Content-Length',str(len(value['body'].encode())))
            self.send_header('Content-Type','text/event-stream' if self.path.startswith('/v1/messages') else 'application/json')
            self.end_headers();self.wfile.write(value['body'].encode());self.wfile.flush()
        except Exception:
            self.send_error(400)
        self.close_connection=True
root=Path('/work');cwd=root/'candidate';cwd.mkdir()
server=HTTPServer(('127.0.0.1',0),Handler)
thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
base=f'http://127.0.0.1:{server.server_port}'
profile=dict(initial['profile'],broker_url=base)
config=make_pi_config(root,dict(base_url=base,scope_token=initial['model_token']),
    SimpleNamespace(model=initial['model'],max_tokens=initial['max_tokens']),controlled_tools=profile)
config['args']+=['--system-prompt',initial['system']]
for k,v in config['env'].items():
    if k not in ('PI_TELEMETRY','PI_OFFLINE','SCOPED_GATEWAY_TOKEN','PI_TOOL_PHASE','PI_TOOL_BROKER_URL','PI_TOOL_SCOPE_TOKEN'):
        Path(v).mkdir(parents=True,exist_ok=True)
for name,key in (('settings.json','settings'),('models.json','models')):
    (Path(config['env']['PI_CODING_AGENT_DIR'])/name).write_text(json.dumps(config[key]))
env=config['env']|{'PATH':'/source/node/bin:/usr/bin:/bin','LANG':'C.UTF-8','NODE_DISABLE_COMPILE_CACHE':'1','NODE_OPTIONS':'--max-old-space-size=192'}
env.pop('NODE_COMPILE_CACHE')
def verify(call_id,name,args,receipt):
    result=relay('/host/verify',[],json.dumps(dict(call_id=call_id,name=name,args=args,receipt=receipt)))
    return result['status']==200 and json.loads(result['body'])=={'verified':True}
cli='/source/pi/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js'
config_hash=initial['config_hash'];session=EngineSession('pi',config_hash,'develop',root/'sessions/develop.jsonl')
adapter=PiAdapter(['/source/node/bin/node',cli,*config['args']],cwd=cwd,env=env,config_hash=config_hash,
    authorized_tools=tuple(initial['tools']),tool_verifier=verify)
try:
    result=adapter.run_phase(phase='develop',prompt=initial['prompt'],
        context=AdministratorContext('local-trial-1',initial['plan_hash'],'local-trial-1','host frozen development contract'),
        session=session,deadline=datetime.fromtimestamp(initial['deadline'],timezone.utc),tools=initial['tools'])
    rpc=list(session.session_path.parent.glob('*.rpc.jsonl'))
    if len(rpc)!=1: raise ValueError('one authenticated RPC transcript required')
    print(json.dumps(dict(type='result',receipt=asdict(result),session=session.session_path.read_text(),
        transcript=rpc[0].read_text(),network_denied=network_denied())),flush=True)
finally:
    server.shutdown();server.server_close();thread.join(2)
