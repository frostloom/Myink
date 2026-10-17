"""Actual installed Pi text RPC proof, loopback Anthropic substitute, zero paid HTTP."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from ops.pi.engine import AdministratorContext, EngineSession
from ops.pi.pi_config import make_pi_config
from ops.pi.pi_rpc import PiAdapter


def main():
    root=Path(sys.argv[1]).resolve()
    node=Path('/Users/a1/项目/Myink/myink-pi/runtime/node/node-v24.16.0-linux-x64/bin/node')
    cli=Path('/Users/a1/项目/Myink/myink-pi/runtime/pi-project/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js')
    assert os.getuid()!=0 and root.parts[:3]==('/','mnt','e')
    wire=[]
    attempts=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            size=int(self.headers['Content-Length']); assert 0<size<=65536
            body=json.loads(self.rfile.read(size))
            attempts.append({'path':self.path,'header_names':sorted(self.headers.keys()),'api_key_matches':self.headers.get('x-api-key')=='mock-only-scope','scope_matches':self.headers.get('X-Pi-Scope')=='local-trial-1','payload':body})
            (root/'mock-request-diagnostic.json').write_text(json.dumps(attempts,indent=2)+'\n')
            assert self.path=='/v1/messages?beta=true' and attempts[-1]['api_key_matches']
            assert self.headers.get('X-Pi-Scope')=='local-trial-1'
            assert body['model']=='mock-model' and body['thinking']=={'type':'disabled'}
            assert body['stream'] is True and 'cache_control' not in json.dumps(body)
            assert not set(body)-{'model','max_tokens','messages','system','stream','thinking','temperature','top_p','top_k','stop_sequences'}
            wire.append(body)
            (root/'mock-wire.json').write_text(json.dumps(wire,indent=2)+'\n')
            self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.send_header('Connection','close'); self.end_headers()
            text='C14 actual installed Pi mock RPC ready.'
            events=[{'type':'message_start','message':{'id':'msg_c14mock','type':'message','role':'assistant','model':'mock-model','content':[],'stop_reason':None,'stop_sequence':None,'usage':{'input_tokens':17,'output_tokens':0,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}},
                {'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}},
                {'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':text}},
                {'type':'content_block_stop','index':0},
                {'type':'message_delta','delta':{'stop_reason':'end_turn','stop_sequence':None},'usage':{'output_tokens':9}},
                {'type':'message_stop'}]
            for event in events:
                self.wfile.write(('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n').encode()); self.wfile.flush()
            self.close_connection=True
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    config=make_pi_config(root,{'base_url':f'http://127.0.0.1:{server.server_port}','scope_token':'mock-only-scope','mock':True},SimpleNamespace(model='mock-model',max_tokens=64))
    for name,value in config['env'].items():
        if name not in ('PI_TELEMETRY','PI_OFFLINE','SCOPED_GATEWAY_TOKEN'): Path(value).mkdir(parents=True,exist_ok=True)
    agent=Path(config['env']['PI_CODING_AGENT_DIR'])
    (agent/'settings.json').write_text(json.dumps(config['settings']))
    (agent/'models.json').write_text(json.dumps(config['models']))
    cwd=root/'candidate'; cwd.mkdir()
    env={**config['env'],'PATH':str(node.parent)+':/usr/bin:/bin','LANG':'C.UTF-8'}
    help_result=subprocess.run([str(node),str(cli),'--help'],env=env,cwd=cwd,capture_output=True,timeout=20)
    (root/'installed-help.txt').write_bytes(help_result.stdout)
    assert help_result.returncode==0 and b'--no-context-files' in help_result.stdout and b'--no-builtin-tools' in help_result.stdout
    guard=Path(__file__).parent/'pi-wire-guard.mjs'
    config_hash=hashlib.sha256(json.dumps({k:v for k,v in config.items() if k!='env'},sort_keys=True).encode()+guard.read_bytes()).hexdigest()
    command=[str(node),str(cli),*config['args'],'-e',str(guard)]
    if '--diagnose' in sys.argv:
        try:
            diagnostic=subprocess.run(command+['--session-dir',str(root/'sessions'),'--session',str(root/'sessions'/'analysis.jsonl')],input=b'',env=env,cwd=cwd,capture_output=True,timeout=30)
        except subprocess.TimeoutExpired as error:
            diagnostic=SimpleNamespace(returncode=None,stderr=error.stderr or b'',stdout=error.stdout or b'')
        result={'status':'diagnostic_only','returncode':diagnostic.returncode,'paid_http_requests':0,'mock_http_requests':len(wire),
            'stderr':diagnostic.stderr[:8192].decode(errors='replace').replace('mock-only-scope','[scoped-token]'),
            'stdout':diagnostic.stdout[:8192].decode(errors='replace').replace('mock-only-scope','[scoped-token]')}
        (root/'diagnostic.json').write_text(json.dumps(result,indent=2)+'\n')
        server.shutdown(); server.server_close(); print(json.dumps(result)); return 0
    cgroup=Path('/proc/self/cgroup').read_text().strip()
    group=Path('/sys/fs/cgroup')/cgroup.split(':',2)[2].lstrip('/')
    envelope={'uid':os.getuid(),'gid':os.getgid(),'pid':os.getpid(),'cgroup':cgroup,'node':str(node),'cli':str(cli),'node_version':subprocess.check_output([str(node),'--version'],env=env).decode().strip(),
        'memory.max':(group/'memory.max').read_text().strip(),'memory.swap.max':(group/'memory.swap.max').read_text().strip(),'cpu.max':(group/'cpu.max').read_text().strip()}
    (root/'runtime-envelope.json').write_text(json.dumps(envelope,indent=2)+'\n')
    context=AdministratorContext('local-trial-1','c14-mock-analysis','local-trial-1','Trusted mock startup and read-only analysis proof')
    session=EngineSession('pi',config_hash,'analysis',root/'sessions'/'analysis.jsonl')
    adapter=PiAdapter(command,cwd=cwd,env=env,config_hash=config_hash)
    receipt=adapter.run_phase(phase='analysis',prompt='Reply with one short readiness statement. No tools, no file changes.',context=context,session=session,deadline=datetime.now(timezone.utc)+timedelta(seconds=60),tools=[])
    server.shutdown(); server.server_close()
    output={'status':receipt.status,'evidence':receipt.evidence,'mock_http_requests':len(wire),'mock_http_attempts':len(attempts),'paid_http_requests':0,'envelope':envelope}
    (root/'mock-receipt.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output))
    return 0 if receipt.status=='done' and len(wire)==1 else 1

if __name__=='__main__': raise SystemExit(main())
