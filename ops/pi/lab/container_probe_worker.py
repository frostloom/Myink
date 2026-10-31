"""Fixed synthetic Linux canaries, run as PID1 in an unprivileged probe container."""
import errno
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
from threading import Thread
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler


CGROUP=Path('/sys/fs/cgroup')
TARGETS=('192.0.2.1','198.51.100.1','172.17.0.1')


def denied_read(path):
    try: Path(path).read_bytes()
    except (PermissionError,FileNotFoundError,IsADirectoryError): return True
    return False


def denied_write(path):
    try:
        with Path(path).open('ab') as f: f.write(b'x')
    except OSError as exc: return exc.errno in (errno.EROFS,errno.EACCES,errno.ENOENT)
    return False


def network_denied():
    for target in TARGETS:
        try:
            with socket.create_connection((target,8765),timeout=.3): return False
        except OSError: pass
    # No default route, including Docker Desktop host aliases via DNS.
    routes=Path('/proc/net/route').read_text().splitlines()[1:]
    if any(row.split()[0]!='lo' for row in routes): return False
    for name in ('host.docker.internal','gateway.docker.internal'):
        try:
            addresses=socket.getaddrinfo(name,8765,type=socket.SOCK_STREAM)
        except OSError: continue
        for _,_,_,_,address in addresses:
            try:
                with socket.create_connection(address[:2],timeout=.3): return False
            except OSError: pass
    return True


def isolation(foreign):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            self.send_response(200 if self.path=='/mock' and self.headers.get('x-api-key')=='synthetic-only-token' else 403)
            self.end_headers()
    server=HTTPServer(('127.0.0.1',0),Handler)
    worker=Thread(target=server.serve_forever,daemon=True); worker.start()
    opener=build_opener(ProxyHandler({}))
    try:
        url=f'http://127.0.0.1:{server.server_port}/mock'
        with opener.open(Request(url,headers={'x-api-key':'synthetic-only-token'}),timeout=1) as r: authenticated=r.status
        try: opener.open(Request(url,headers={'x-api-key':'wrong'}),timeout=1)
        except HTTPError as exc: wrong=exc.code
        else: wrong=200
    finally: server.shutdown(); server.server_close(); worker.join(1)
    status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    Path('/work/positive').write_text('synthetic-write-ok')
    nested=subprocess.run([sys.executable,'-I','-S',__file__,'nested',foreign],capture_output=True,text=True,timeout=4)
    env_denied=not any(k in os.environ for k in ('PLATFORM_MODEL_API_KEY','OPENAI_API_KEY','AWS_SECRET_ACCESS_KEY',
        'ANTHROPIC_API_KEY','DATABASE_URL','ADMIN_DATABASE_URL','DOCKER_HOST','SCOPED_GATEWAY_TOKEN'))
    return dict(uid=os.getuid(),gid=os.getgid(),no_new_privileges=status['NoNewPrivs'].strip()=='1',
        no_capabilities=int(status['CapEff'].strip(),16)==0,
        positive_source_read=Path('/source/canary').read_text()=='synthetic-source-canary\n',
        positive_tmp_write=Path('/work/positive').read_text()=='synthetic-write-ok',
        authenticated_mock=authenticated,wrong_token=wrong,
        source_write_denied=denied_write('/source/canary'),harness_write_denied=denied_write(__file__),
        foreign_files_denied=denied_read(foreign),
        foreign_native_aliases_denied=all(denied_read(p) for p in ('/source/foreign-alias','/proc/1/root'+foreign,'/host_mnt'+foreign)),
        ledger_credentials_sessions_denied=env_denied and all(denied_read(p) for p in
            ('/Users/a1/项目/Myink/myink-pi/state','/root/.ssh','/Users/a1/.ssh','/Users/a1/.pi/agent/auth.json')),
        host_sockets_denied=all(not Path(p).exists() for p in ('/var/run/docker.sock','/run/docker.sock','/Users/a1/.docker/run/docker.sock')),
        network_denied=network_denied(),nested_network_denied=nested.returncode==0 and json.loads(nested.stdout).get('denied') is True)


def value(name): return int((CGROUP/name).read_text().strip())
def counter(name,key): return int(dict(line.split() for line in (CGROUP/name).read_text().splitlines())[key])


def resources():
    available=int(dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())['MemAvailable'].split()[0])*1024
    if available<512*1024**2: raise RuntimeError('insufficient guest headroom')
    result=dict(memory_max=value('memory.max'),swap_max=value('memory.swap.max'),
        cpu_max=(CGROUP/'cpu.max').read_text().strip(),pids_max=value('pids.max'),guest_available_before=available)
    if (result['memory_max'],result['swap_max'],result['cpu_max'],result['pids_max'])!=(402653184,0,'50000 100000',64):
        raise RuntimeError('kernel limits mismatch')
    before=counter('cpu.stat','nr_throttled')
    code='import time;end=time.monotonic()+2\nwhile time.monotonic()<end: pass'
    workers=[subprocess.Popen([sys.executable,'-I','-S','-c',code]) for _ in range(2)]
    for child in workers: child.wait(timeout=5)
    result['throttled_delta']=counter('cpu.stat','nr_throttled')-before
    before=counter('memory.events','oom_kill')
    child=subprocess.run([sys.executable,'-I','-S','-c','a=bytearray(420*1024**2)'],timeout=5)
    result.update(memory_child_returncode=child.returncode,memory_peak=value('memory.peak'),
                  oom_kills_delta=counter('memory.events','oom_kill')-before)
    sleepers=[]; denied=False
    try:
        for _ in range(65):
            try: sleepers.append(subprocess.Popen(['/bin/sleep','20']))
            except OSError as exc:
                if exc.errno!=errno.EAGAIN: raise
                denied=True; break
        peak=value('pids.current')
    finally:
        for child in sleepers: child.kill()
        for child in sleepers: child.wait(timeout=3)
    result.update(pids_denied=denied,pids_peak=peak)
    return result


def descendants():
    reader,writer=os.pipe()
    child=os.fork()
    if child==0:
        os.close(reader); os.setsid()
        grandchild=os.fork()
        if grandchild==0:
            os.close(writer); os.setsid(); signal.signal(signal.SIGTERM,signal.SIG_IGN)
            while True: time.sleep(10)
        os.write(writer,str(grandchild).encode()+b'\n'); os.close(writer)
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        while True: time.sleep(10)
    os.close(writer)
    grandchild=int(os.read(reader,64)); os.close(reader)
    return dict(detached_descendants_ready=True,parent_pid=os.getpid(),child_pid=child,grandchild_pid=grandchild)


def main():
    mode,foreign=sys.argv[1:]
    if mode=='nested': proof={'denied':network_denied() and denied_read(foreign) and denied_write('/probe/worker.py')}
    elif mode=='isolation': proof=isolation(foreign)
    elif mode=='resources': proof=resources()
    elif mode in ('timeout','overflow'):
        print(json.dumps(descendants()),flush=True)
        if mode=='overflow':
            while True: os.write(1,b'x'*4096)
        while True: time.sleep(10)
    else: raise ValueError('fixed probe mode required')
    print(json.dumps(proof,sort_keys=True),flush=True)


if __name__=='__main__': main()
