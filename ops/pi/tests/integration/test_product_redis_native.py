"""Actual Redis authentication stays inside the owned container environment."""
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess,time,uuid
import pytest
pytestmark=pytest.mark.pi_followup_docker


def test_authenticated_redis_lock_census_uses_container_secret_not_host_argv(tmp_path):
    from ops.pi.product_runtime import LinuxProductHost
    assert callable(getattr(LinuxProductHost,'read_redis_locks',None)), 'missing authenticated lock census'
    from ops.pi.product_commands import DockerCommands
    docker=Path('/Users/a1/开发工具/bin/docker')
    if not docker.exists():docker=Path('/usr/bin/docker')
    docker=docker.resolve();nonce=str(uuid.uuid4());cid=None
    def run(*args):return subprocess.check_output([str(docker),*args],stderr=subprocess.PIPE,text=True,timeout=30).strip()
    endpoint=json.loads(run('context','inspect','--format','{{json .Endpoints.docker.Host}}'))
    assert run('--host',endpoint,'info','--format','{{.ID}}')!='0f90c176-9c45-4708-8103-37b5ff2464f1'
    image=json.loads(run('--host',endpoint,'image','inspect','redis:7-alpine'))[0]['Id']
    secret='synthetic-redis-'+nonce
    try:
        cid=run('--host',endpoint,'create','--name','myink-pi-redis-census-'+nonce[:12],'--label','myink.pi.redis-census='+nonce,'--network','none','--read-only','--tmpfs','/data:rw,size=16777216','--memory','64m','--memory-swap','64m','--pids-limit','32','--env','REDIS_PASSWORD='+secret,image,'redis-server','--requirepass',secret,'--save','','--appendonly','no')
        run('--host',endpoint,'start',cid);until=time.monotonic()+15
        def redis(*args):return run('--host',endpoint,'exec',cid,'redis-cli','--no-auth-warning','-a',secret,*args)
        while True:
            try:
                if redis('ping')=='PONG':break
            except subprocess.CalledProcessError:pass
            assert time.monotonic()<until;time.sleep(.2)
        redis('MSET','lock:task:a','1','lock:task:b','1','lock:book:a','1','unrelated','1')
        root=(tmp_path/'operation').resolve();root.mkdir(mode=0o700);commands=root/'commands';commands.mkdir(mode=0o700)
        host=SimpleNamespace(commands=DockerCommands(docker,endpoint,commands),_cid=lambda role:cid)
        def value(args):
            result=host.commands.run(args);return json.loads((commands/result['command_id']/'stdout.bin').read_bytes())
        host._json=value
        assert LinuxProductHost.read_redis_locks(host)==dict(task_locks=2,book_locks=1)
        intents=list(commands.glob('*/intent.json'));assert intents
        assert all(secret.encode() not in p.read_bytes() for p in intents)
    finally:
        if cid:
            info=json.loads(run('--host',endpoint,'inspect',cid))[0]
            assert info['Image']==image and info['Config']['Labels'].get('myink.pi.redis-census')==nonce
            run('--host',endpoint,'rm','--force',cid)
