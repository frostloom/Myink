"""Real subprocess coverage for the Linux host's private Docker transport."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time
import uuid

import pytest

pytestmark=pytest.mark.skipif(os.name!='posix',reason='Linux native transport requires POSIX process sessions')


def api():
    assert importlib.util.find_spec('ops.pi.product_commands'), 'missing bounded native product transport'
    from ops.pi.product_commands import DockerCommands, DockerCommandError
    return DockerCommands,DockerCommandError


@pytest.fixture
def command(tmp_path):
    root=(tmp_path/'commands').resolve();root.mkdir(mode=0o700)
    docker=(tmp_path/'docker').resolve()
    body = """import os,sys,time,subprocess,json
args=sys.argv[3:]
if args[0]=='emit':
 os.write(1,b'\\x00\\xffbackup\\x00');os.write(2,b'private diagnostic')
elif args[0]=='mark':
 with open(args[1],'a') as f:f.write('effect\\n')
elif args[0]=='overflow':
 for _ in range(1024):os.write(1,b'x'*65536)
elif args[0]=='stderr-overflow':
 for _ in range(1024):os.write(2,b'x'*65536)
elif args[0]=='hang':
 subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
 sys.exit(0)
elif args[0]=='interrupt-child':
 code="import os,json,time,sys; p=sys.argv[1]; \\nfor n in range(1500):\\n with open(p,'a') as f:f.write(json.dumps([os.getpid(),os.getpgrp(),n])+chr(10))\\n if n==3:os.write(1,b'ready')\\n time.sleep(.02)"
 subprocess.Popen([sys.executable,'-c',code,args[1]])
 sys.exit(0)
elif args[0]=='fail':
 os.write(2,b'private diagnostic');sys.exit(17)
elif args[0]=='environment':
 print(json.dumps({'secret_present':'PRODUCT_TEST_SECRET' in os.environ,'stdin':len(sys.stdin.buffer.read()),'args':args[1:]}))
"""
    docker.write_text('#!'+sys.executable+'\n'+body);docker.chmod(0o700)
    return docker,root


def test_binary_stdout_and_both_private_receipts_are_preserved(command):
    docker,root=command;runner=api()[0](docker,'unix:///tmp/product-test.sock',root)
    result=runner.run(['emit'],timeout=10,output_limit=1024)
    folder=root/result['command_id']
    assert result['status']=='done' and result['returncode']==0
    assert (folder/'stdout.bin').read_bytes()==b'\x00\xffbackup\x00'
    assert (folder/'stderr.bin').read_bytes()==b'private diagnostic'
    assert json.loads((folder/'intent.json').read_bytes())['argv']==[str(docker),'--host','unix:///tmp/product-test.sock','emit']
    assert json.loads((folder/'receipt.json').read_bytes())==result
    for path in folder.iterdir():assert stat.S_IMODE(path.stat().st_mode)==0o600
    assert stat.S_IMODE(folder.stat().st_mode)==0o700


def test_same_command_identity_never_dispatches_twice(command,tmp_path):
    docker,root=command;runner,error=api();runner=runner(docker,'unix:///tmp/product-test.sock',root)
    marker=tmp_path/'effects';identity=str(uuid.uuid4())
    runner.run(['mark',str(marker)],command_id=identity,timeout=10)
    with pytest.raises(error):runner.run(['mark',str(marker)],command_id=identity,timeout=10)
    assert marker.read_text()=='effect\n'


@pytest.mark.parametrize('kind',['overflow','stderr-overflow'])
def test_output_overflow_is_bounded_durable_and_terminal(command,kind):
    docker,root=command;runner,error=api();runner=runner(docker,'unix:///tmp/product-test.sock',root)
    with pytest.raises(error) as caught:runner.run([kind],timeout=10,output_limit=1024)
    receipt=caught.value.receipt;folder=root/receipt['command_id']
    assert receipt['status']=='uncertain' and receipt['reason']=='output_limit'
    assert (folder/'stdout.bin').stat().st_size<=1024
    assert (folder/'stderr.bin').stat().st_size<=65536
    assert json.loads((folder/'receipt.json').read_bytes())==receipt


def test_deadline_reaps_own_cli_and_descendant_pipes(command):
    docker,root=command;runner,error=api();runner=runner(docker,'unix:///tmp/product-test.sock',root)
    started=time.monotonic()
    with pytest.raises(error) as caught:runner.run(['hang'],timeout=.2)
    assert time.monotonic()-started<3
    assert caught.value.receipt['reason']=='deadline' and caught.value.receipt['status']=='uncertain'


def test_nonzero_exit_retains_private_diagnostics_without_exposing_them(command):
    docker,root=command;runner,error=api();runner=runner(docker,'unix:///tmp/product-test.sock',root)
    with pytest.raises(error) as caught:runner.run(['fail'],timeout=10)
    assert caught.value.receipt['returncode']==17 and caught.value.receipt['status']=='uncertain'
    assert 'private diagnostic' not in str(caught.value)
    assert (root/caught.value.receipt['command_id']/'stderr.bin').read_bytes()==b'private diagnostic'


def test_no_shell_inherited_secrets_or_stdin(command,tmp_path,monkeypatch):
    docker,root=command;runner=api()[0](docker,'unix:///tmp/product-test.sock',root)
    monkeypatch.setenv('PRODUCT_TEST_SECRET','synthetic-private-value')
    marker=tmp_path/'shell-effect';argument='$(touch '+str(marker)+')'
    result=runner.run(['environment',argument],timeout=10)
    value=json.loads((root/result['command_id']/'stdout.bin').read_bytes())
    assert value==dict(secret_present=False,stdin=0,args=[argument]) and not marker.exists()


@pytest.mark.parametrize('limit',[0,-1,True,536870913])
def test_invalid_limits_never_launch(command,tmp_path,limit):
    docker,root=command;runner=api()[0](docker,'unix:///tmp/product-test.sock',root)
    marker=tmp_path/'effect'
    with pytest.raises(ValueError):runner.run(['mark',str(marker)],output_limit=limit)
    assert not marker.exists() and list(root.iterdir())==[]


def test_symlink_output_root_is_rejected(command,tmp_path):
    docker,root=command;link=tmp_path/'linked';link.symlink_to(root,target_is_directory=True)
    with pytest.raises(ValueError):api()[0](docker,'unix:///tmp/product-test.sock',link)


def test_interruption_after_cli_exit_kills_remaining_session_and_keeps_intent(command,tmp_path,monkeypatch):
    import signal
    import ops.pi.product_commands as transport
    docker,root=command;runner=api()[0](docker,'unix:///tmp/product-test.sock',root)
    heartbeat=tmp_path/'child-heartbeat';read=os.read
    def interrupted_read(fd,size):
        data=read(fd,size)
        if data==b'ready':raise KeyboardInterrupt()
        return data
    monkeypatch.setattr(transport.os,'read',interrupted_read)
    identity=str(uuid.uuid4());group=None
    try:
        with pytest.raises(KeyboardInterrupt):runner.run(['interrupt-child',str(heartbeat)],command_id=identity,timeout=10)
        lines=heartbeat.read_text().splitlines();group=json.loads(lines[-1])[1]
        before=len(lines);time.sleep(.12)
        assert len(heartbeat.read_text().splitlines())==before,'interrupted command left its descendant running'
        assert (root/identity/'intent.json').exists() and not (root/identity/'receipt.json').exists()
        with pytest.raises(api()[1]):runner.run(['emit'],command_id=identity,timeout=10)
    finally:
        if group is None and heartbeat.exists():group=json.loads(heartbeat.read_text().splitlines()[-1])[1]
        if group is not None:
            try:os.killpg(group,signal.SIGKILL)
            except ProcessLookupError:pass


def test_only_explicit_private_artifact_is_supplied_to_stdin(command,tmp_path):
    from hashlib import sha256
    docker,root=command;runner=api()[0](docker,'unix:///tmp/product-test.sock',root)
    data=b'owned SQL artifact\x00';source=tmp_path/'restore-input.bin';source.write_bytes(data);source.chmod(0o600)
    result=runner.run(['environment'],stdin_path=source,timeout=10)
    folder=root/result['command_id'];intent=json.loads((folder/'intent.json').read_bytes())
    assert intent['stdin']==dict(path='restore-input.bin',bytes=len(data),sha256=sha256(data).hexdigest())
    assert json.loads((folder/'stdout.bin').read_bytes())['stdin']==len(data)


def test_stdin_outside_operation_root_never_starts(command,tmp_path):
    docker,root=command;runner=api()[0](docker,'unix:///tmp/product-test.sock',root)
    marker=tmp_path/'effect';outside=tmp_path.parent/('outside-'+uuid.uuid4().hex);outside.write_bytes(b'no');outside.chmod(0o600)
    try:
        with pytest.raises(ValueError):runner.run(['mark',str(marker)],stdin_path=outside,timeout=10)
        assert not marker.exists() and list(root.iterdir())==[]
    finally:outside.unlink()


def test_linked_or_public_stdin_artifact_never_starts(command,tmp_path):
    docker,root=command;runner=api()[0](docker,'unix:///tmp/product-test.sock',root)
    marker=tmp_path/'effect';source=tmp_path/'input';source.write_bytes(b'no');source.chmod(0o644)
    with pytest.raises(ValueError):runner.run(['mark',str(marker)],stdin_path=source,timeout=10)
    source.chmod(0o600);alias=tmp_path/'alias';os.link(source,alias)
    with pytest.raises(ValueError):runner.run(['mark',str(marker)],stdin_path=alias,timeout=10)
    assert not marker.exists() and list(root.iterdir())==[]
