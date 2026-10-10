"""Real private-daemon isolation acceptance; no dependency skips."""
import json
from pathlib import Path
import subprocess
import time
import pytest
from ops.pi.resources import sample_resources, verify_limits

pytestmark = pytest.mark.pi_lab


def docker(*args, check=True):
    result = subprocess.run(['docker', '--host', 'unix:///var/run/docker.sock', *args],
                            capture_output=True, text=True, timeout=120)
    if check:
        assert result.returncode == 0, result.stderr
    return result


def test_actual_group_membership_and_limits(lab_identity):
    for group in ('agent', 'heavy'):
        proof = sample_resources(group)
        assert verify_limits(proof, group), proof
    runner = Path('/proc/self/cgroup').read_text()
    assert '/myinkpi.slice/myinkpi-heavy.slice/' in runner
    for name in lab_identity['test_containers']:
        info = json.loads(docker('inspect', name).stdout)[0]
        for mount in info['Mounts']:
            if mount['Type']=='volume':
                volume=json.loads(docker('volume','inspect',mount['Name']).stdout)[0]
                assert volume['Labels']['myink.pi.lab']==lab_identity['lab_uuid']
        pid = info['State']['Pid']
        assert '/myinkpi.slice/myinkpi-heavy.slice/' in Path(f'/proc/{pid}/cgroup').read_text()
    sandbox = json.loads(docker('inspect', lab_identity['sandbox']).stdout)[0]
    assert sandbox['Config']['User'] == '65534:65534'
    assert sandbox['HostConfig']['ReadonlyRootfs'] is True
    assert sandbox['HostConfig']['CapDrop'] == ['ALL']
    assert sandbox['HostConfig']['MemorySwap'] == sandbox['HostConfig']['Memory']


def test_direct_nested_network_and_protected_files_denied(lab_identity):
    sandbox = lab_identity['sandbox']
    # Controlled endpoint is alive and reachable from trusted test-fixture peer.
    positive = docker('exec', lab_identity['gateway'], 'python', '-c',
                      "import urllib.request;print(urllib.request.urlopen('http://172.29.220.20:8080',timeout=3).status)")
    assert positive.stdout.strip() == '200'
    result = docker('exec', sandbox, 'python', '/policy/probe.py')
    evidence = json.loads(result.stdout)
    assert evidence['authenticated_mock'] == 200
    assert evidence['wrong_token'] == 403
    assert evidence['denied_urls'] == 6
    assert evidence['nested_python_denied'] is True
    assert evidence['nested_curl_denied'] is True
    assert evidence['file_denials'] == 9
    import socket
    assert socket.getaddrinfo('example.com',80)
    assert evidence['external_dns_denied'] is True
    assert evidence['nonroot'] is True
    assert evidence['no_caps'] is True
    Path(lab_identity['evidence_dir'], 'sandbox-probes.json').write_text(json.dumps(evidence, indent=2))


def test_actual_cpu_throttling_and_memory_cap(lab_identity):
    before = sample_resources('agent')
    command = "import multiprocessing,time; p=[multiprocessing.Process(target=lambda:exec('while True: pass')) for _ in range(2)];[x.start() for x in p];time.sleep(3);[x.terminate() for x in p];[x.join() for x in p]"
    docker('exec', lab_identity['sandbox'], 'python', '-c', command)
    after = sample_resources('agent')
    throttled = lambda p: int(dict(line.split() for line in p['cpu.stat'].splitlines())['nr_throttled'])
    assert throttled(after) > throttled(before)
    result = docker('exec', lab_identity['sandbox'], 'python', '-c',
                    "import subprocess; r=subprocess.run(['python','-c','a=bytearray(500*1024**2);print(len(a))']);print(r.returncode)")
    assert result.stdout.strip() == '-9'
    assert int(sample_resources('agent')['memory.peak']) <= 384 * 1024**2
    assert 'oom_kill 0' not in sample_resources('agent')['memory.events']


def test_whole_heavy_group_aggregate_cap(lab_identity):
    names = []
    try:
        for i in range(2):
            name = f"{lab_identity['project']}-memory-{i}"
            names.append(name)
            docker('run', '-d', '--name', name, '--label', f"myink.pi.lab={lab_identity['lab_uuid']}",
                   '--cgroup-parent', 'myinkpi-heavy.slice', '--network', 'none', '--memory-swap', '-1',
                   lab_identity['python_image'], 'python', '-c',
                   'import time;a=bytearray(900*1024**2);time.sleep(10)')
        time.sleep(4)
        states = [json.loads(docker('inspect', name).stdout)[0]['State'] for name in names]
        assert any(state['OOMKilled'] for state in states), states
        assert int(sample_resources('heavy')['memory.peak']) <= 1536 * 1024**2
        assert sample_resources('heavy')['memory.swap.max'] == str(256 * 1024**2)
    finally:
        for name in names:
            docker('rm', '-f', name, check=False)


def test_heavy_mutex_and_runner_descendants(lab_identity):
    import sys
    result=subprocess.run(['flock','-n','/opt/myink-pi-lab/heavy.lock','true'],capture_output=True)
    assert result.returncode == 1
    child=subprocess.run([sys.executable,'-c',"from pathlib import Path;print(Path('/proc/self/cgroup').read_text())"],capture_output=True,text=True,check=True)
    assert '/myinkpi.slice/myinkpi-heavy.slice/' in child.stdout


def test_controlled_guest_and_windows_hosts_denied(lab_identity):
    import urllib.request
    hosts=json.loads(Path('/mnt/e/tools/myink-pi/evidence/b7-host-reachability.json').read_text())
    assert hosts['trusted_windows_host_status']==200
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for url in ('http://172.29.220.1:8080',hosts['url']):
        assert opener.open(url,timeout=3).status==200
        code="import urllib.request;urllib.request.build_opener(urllib.request.ProxyHandler({})).open("+repr(url)+",timeout=2)"
        denied=docker('exec',lab_identity['sandbox'],'python','-c',code,check=False)
        assert denied.returncode!=0 and any(reason in denied.stderr for reason in ('timed out','Network is unreachable'))
    wrongscope="import urllib.request,urllib.error; r=urllib.request.Request('http://172.29.220.2:8765/mock',headers={'Authorization':'Bearer synthetic-b7-token','X-Pi-Scope':'foreign'});\ntry: urllib.request.urlopen(r,timeout=2)\nexcept urllib.error.HTTPError as e: print(e.code)"
    result=docker('exec',lab_identity['sandbox'],'python','-c',wrongscope)
    assert result.stdout.strip()=='403'
