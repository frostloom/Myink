"""Real Docker Go templates against a private fake Unix engine, no real daemon."""
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import importlib,json,os,shutil,socketserver,subprocess,tempfile,threading
import pytest


@pytest.mark.parametrize('kind',['container_without_health','image_without_labels'])
def test_real_cli_formats_missing_optional_keys_without_reading_secrets(kind):
    binary=shutil.which('docker');fallback=Path('/Applications/Docker.app/Contents/Resources/bin/docker')
    if binary is None and fallback.is_file():binary=str(fallback)
    if binary is None or not hasattr(socketserver,'UnixStreamServer'):pytest.skip('Docker CLI/Unix sockets unavailable; no daemon used')
    module=importlib.import_module('ops.pi.product_reality');cid='a'*64;iid='sha256:'+'b'*64
    data=dict(Id=cid,Image=iid,State=dict(Running=True,Status='running'),Config=dict(Labels={'com.docker.compose.project':'myink','com.docker.compose.service':'myink-worker'})) if kind=='container_without_health' else dict(Id=iid,Config={})
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_HEAD(self):
            requests.append(self.path);assert self.path=='/_ping';self.send_response(200);self.send_header('API-Version','1.45');self.end_headers()
        def do_GET(self):
            requests.append(self.path)
            if self.path=='/_ping':
                self.send_response(200);self.send_header('API-Version','1.45');self.end_headers();self.wfile.write(b'OK');return
            valid=self.path.endswith('/containers/'+cid+'/json') if kind=='container_without_health' else self.path.endswith('/images/'+iid+'/json')
            raw=json.dumps(data if valid else dict(message='isolated fixture only')).encode();self.send_response(200 if valid else 404);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    class Server(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):daemon_threads=True
    with tempfile.TemporaryDirectory(prefix='pi-format-',dir='/tmp') as name:
        root=Path(name);sock=root/'engine.sock';server=Server(str(sock),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            args=['inspect','--format',module.CONTAINER_FORMAT,cid] if kind=='container_without_health' else ['image','inspect','--format',module.IMAGE_FORMAT,iid]
            r=subprocess.run([binary,'--host','unix://'+str(sock),*args],capture_output=True,text=True,timeout=10,env=dict(PATH=os.environ.get('PATH','/usr/bin:/bin'),HOME=str(root),DOCKER_CONFIG=str(root/'empty-config'),DOCKER_API_VERSION='1.45'))
        finally:server.shutdown();server.server_close();thread.join(timeout=5)
    assert r.returncode==0,r.stderr
    value=json.loads(r.stdout);assert value['healthy'] is None if kind=='container_without_health' else value['revision'] is None
    data_requests=[path for path in requests if path!='/_ping'];assert len(data_requests)==1 and '/v1.45/' in data_requests[0]
