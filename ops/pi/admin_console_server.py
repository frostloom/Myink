"""Local authenticated operator bridge; never an internet or model endpoint."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from hashlib import sha256
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import hmac
import os
import socket
import socketserver
import stat
import struct

from .admin_console import Console, request, _uuid
from .audit import KINDS, _path, _plain, encoded, hash_value, name, require, strict_json
from .nightly_gate import BASE

RUNTIME=Path('/run/myink-pi-console')


def load_config(path,pin):
    path=_path(path)
    require(os.geteuid()==0 and path==BASE/'config/admin-console.json' and hash_value(pin),'fixed root console configuration required')
    _plain(path);info=path.stat();require(info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o640 and info.st_size<=65536,'private root console configuration required')
    raw=path.read_bytes();require(sha256(raw).hexdigest()==pin,'console configuration drift');value=strict_json(raw)
    require(set(value)=={'schema','mode','socket_path','token_file','allowed_uid','publication_config_sha256'} and value['schema']=='pi-admin-console-v1' and value['mode']=='ACTUAL','closed actual console configuration required')
    require(value['socket_path']==str(RUNTIME/'control.sock') and value['token_file']==str(BASE/'config/admin-console-token') and type(value['allowed_uid']) is int and value['allowed_uid']==10001,'fixed local console identity required')
    require(value['publication_config_sha256'] is None or hash_value(value['publication_config_sha256']),'explicit publication enablement required')
    return value


def _executor(console):
    if console.gate.mode!='ACTUAL':return dict(service_state='simulated',timer_state='simulated',last_result=None,next_check=None)
    import subprocess
    def read(unit,keys):
        result=subprocess.run(['/usr/bin/systemctl','show',unit,*['--property='+k for k in keys]],capture_output=True,text=True,timeout=3,check=True)
        require(len(result.stdout)<=4096,'bounded scheduler state required')
        return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    try:
        service=read('myink-pi-nightly.service',('ActiveState','SubState','Result'));timer=read('myink-pi-nightly.timer',('ActiveState','SubState','NextElapseUSecRealtime'))
        return dict(service_state=service['ActiveState']+'/'+service['SubState'],timer_state=timer['ActiveState']+'/'+timer['SubState'],last_result=service.get('Result'),next_check=timer.get('NextElapseUSecRealtime') or None)
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):return dict(service_state='unavailable',timer_state='unavailable',last_result=None,next_check=None)


def make_server(path,token,console,*,allowed_uid=None):
    path=_path(path)
    require(isinstance(token,str) and 32<=len(token)<=256 and token.isascii() and not any(c.isspace() for c in token),'private service credential required')
    if console.gate.mode=='ACTUAL':
        require(isinstance(console,Console) and os.geteuid()==0 and path==RUNTIME/'control.sock' and allowed_uid==10001,'fixed root console socket required')
    require(path.parent.is_dir() and not stat.S_IMODE(path.parent.stat().st_mode)&0o022 and not path.exists(),'private new console socket required')
    workers=ThreadPoolExecutor(max_workers=1,thread_name_prefix='pi-human-publication')
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def address_string(self):return 'local-console'
        def setup(self):super().setup();self.connection.settimeout(5)
        def _send(self,status,payload):
            raw=encoded(payload)
            if len(raw)>8388608:status=503;raw=encoded(dict(error='unavailable'))
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Connection','close');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.close_connection=True
            try:self.wfile.write(raw)
            except OSError:pass
        def _auth(self):
            values=self.headers.get_all('X-Pi-Console-Token') or []
            if len(values)!=1 or not values[0].isascii() or not hmac.compare_digest(values[0],token):self._send(401,dict(error='unauthorized'));return False
            return True
        def _query(self,parsed,allowed):
            values=parse_qs(parsed.query,keep_blank_values=True,max_num_fields=8)
            require(set(values)<=set(allowed) and all(len(v)==1 for v in values.values()),'invalid console query')
            q={k:v[0] for k,v in values.items()}
            for key,default in (('limit',25),('offset',0)):
                if key in allowed:
                    q[key]=int(q.get(key,default));require((1<=q[key]<=100) if key=='limit' else 0<=q[key]<=1000000,'invalid pagination')
            if 'day' in q:require(date.fromisoformat(q['day']).isoformat()==q['day'],'invalid audit date')
            if 'run_id' in q:require(name(q['run_id']),'invalid run identifier')
            if 'kind' in q:require(q['kind'] in KINDS,'invalid event kind')
            return q
        def do_GET(self):
            if not self._auth():return
            parsed=urlsplit(self.path);route=parsed.path
            allowed={'/v1/status':(),'/v1/runs':('limit','offset','day'),'/v1/events':('run_id','limit','offset','kind'),'/v1/daily':('day',),'/v1/enhancements':('limit','offset')}
            operation=route.startswith('/v1/operations/')
            if route not in allowed and not operation:self._send(404,dict(error='not_found'));return
            try:
                q=self._query(parsed,() if operation else allowed[route])
                if route=='/v1/events':require('run_id' in q,'run identifier required')
                if route=='/v1/daily':require('day' in q,'audit date required')
                if operation:_uuid(route.removeprefix('/v1/operations/'))
            except (ValueError,TypeError):self._send(400,dict(error='invalid_request'));return
            try:
                if route=='/v1/status':payload=dict(console.status(),mode=console.gate.mode,executor=_executor(console))
                elif operation:payload=console.operation(route.removeprefix('/v1/operations/'))
                else:
                    from myink.pi_audit import AuditReader
                    reader=AuditReader(console.export_root)
                    method={'/v1/runs':reader.runs,'/v1/events':reader.events,'/v1/daily':reader.daily,'/v1/enhancements':reader.enhancements}[route]
                    payload=method(**q)
                self._send(200,payload)
            except LookupError:self._send(404,dict(error='not_found'))
            except Exception:self._send(503,dict(error='unavailable'))
        def do_POST(self):
            if not self._auth():return
            if self.path!='/v1/decisions':self._send(404,dict(error='not_found'));return
            try:
                require(self.headers.get('Transfer-Encoding') is None and self.headers.get('Content-Type','').split(';')[0].strip()=='application/json','JSON body required')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=4096:self._send(413,dict(error='invalid_request'));return
                packet=request(strict_json(self.rfile.read(length)))
            except (ValueError,TypeError,OSError):self._send(400,dict(error='invalid_request'));return
            try:
                result=console.submit(packet)
                if result['status']=='queued':workers.submit(console.process,result['request_id'])
                self._send(202,result)
            except ValueError:self._send(409,dict(error='conflict'))
            except Exception:self._send(503,dict(error='unavailable'))
    class Server(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):
        daemon_threads=True
        def verify_request(self,connection,address):
            if allowed_uid is None:return True
            if not hasattr(socket,'SO_PEERCRED'):return False
            _,uid,_=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            return uid in (0,allowed_uid)
        def server_close(self):
            super().server_close();workers.shutdown(wait=True,cancel_futures=True)
            if path.exists() and path.lstat().st_ino==self.socket_inode:path.unlink()
    try:
        server=Server(str(path),Handler);os.chmod(path,0o660);server.socket_inode=path.lstat().st_ino
    except BaseException:workers.shutdown(wait=False,cancel_futures=True);raise
    return server


def write_client_token(path,token):
    """Atomically expose only the service credential to the API's read-only mount."""
    import tempfile
    from .product_commands import _sync
    path=_path(path);require(path.parent.stat().st_uid==os.geteuid() and not stat.S_IMODE(path.parent.stat().st_mode)&0o022,'owned private credential directory required')
    require(isinstance(token,str) and token.isascii() and 32<=len(token)<=256 and not any(c.isspace() for c in token),'bounded service credential required')
    if path.exists():_plain(path);require(path.stat().st_uid==os.geteuid(),'owned credential required')
    fd,temporary=tempfile.mkstemp(prefix='.client-token-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(token.encode('ascii'));os.fchmod(stream.fileno(),0o640);os.fchown(stream.fileno(),os.geteuid(),path.parent.stat().st_gid);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path);_sync(path.parent)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def serve(config_path,pin):
    import signal
    from threading import Thread
    from .nightly_gate import ApprovalGate
    config=load_config(config_path,pin);secret=Path(config['token_file']);_plain(secret);info=secret.stat()
    require(info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o600 and info.st_size<=256,'private root service credential required')
    token=secret.read_text(encoding='ascii').strip()
    require(RUNTIME.stat().st_uid==0 and RUNTIME.stat().st_gid==10001 and stat.S_IMODE(RUNTIME.stat().st_mode)==0o750,'fixed service runtime directory required')
    gate=ApprovalGate(BASE/'state/nightly-approval.sqlite',BASE/'state/actual-manager.sqlite',BASE/'state/ledger.sqlite',mode='ACTUAL')
    console=Console(gate,BASE/'nightly',BASE/'audit/state/events.sqlite',BASE/'audit/export',BASE/'state/admin-console.sqlite',publication_pin=config['publication_config_sha256'])
    write_client_token(RUNTIME/'client-token',token)
    server=make_server(Path(config['socket_path']),token,console,allowed_uid=config['allowed_uid'])
    previous={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
    def stop(*args):Thread(target=server.shutdown,daemon=True).start()
    try:
        for sig in previous:signal.signal(sig,stop)
        server.serve_forever(poll_interval=.25)
    finally:
        server.server_close()
        for sig,handler in previous.items():signal.signal(sig,handler)
    return dict(status='stopped',model_requests=0)
