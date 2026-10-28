"""Diagnosis has frozen dependencies and a finite once-only service boundary."""
from pathlib import Path
from types import SimpleNamespace
import subprocess,sys
from ops.pi.tests.test_followup_deploy import unit,ROOT,DEPLOY
from ops.pi.tests.test_observer_entry import module


def test_diagnosis_entry_verifies_before_import_and_adds_only_frozen_vendor(monkeypatch,tmp_path):
    monkeypatch.setattr(sys,'path',list(sys.path))
    value=module();calls=[];code=tmp_path/'code';code.mkdir();(tmp_path/'vendor').mkdir()
    monkeypatch.setattr(value,'verify_release',lambda *a:calls.append('verified') or code)
    monkeypatch.setitem(sys.modules,'ops.pi.diagnosis_supervisor',SimpleNamespace(run=lambda p,h:calls.append(('diagnosis',p,h)) or dict(status='no_permit')))
    monkeypatch.setattr(sys,'argv',['entry','--component','diagnosis','--config','/fixed/registry','--config-sha256','a'*64])
    assert value.main()==0 and calls==['verified',('diagnosis','/fixed/registry','a'*64)]
    assert str(tmp_path/'vendor') in sys.path


def test_diagnosis_service_cannot_write_release_sources_or_manager():
    s=unit('myink-pi-diagnosis.service')['Service']
    assert s['User']=='ubuntu' and s['Restart']=='no' and int(s['TimeoutStartSec'])<=180
    assert '-I -S -B' in s['ExecStart'] and '--component diagnosis' in s['ExecStart']
    assert ROOT+'/releases' in s['ReadOnlyPaths'].split() and ROOT+'/jobs' in s['ReadOnlyPaths'].split()
    assert ROOT+'/state/credentials' in s['ReadOnlyPaths'].split()
    assert ROOT+'/state/actual-manager.sqlite' in s['ReadOnlyPaths'].split()
    assert s['NoNewPrivileges']=='yes' and s['ProtectSystem']=='strict' and s['KillMode']=='control-group'
    assert 'AF_UNIX' in s['RestrictAddressFamilies'] and 'AF_INET' in s['RestrictAddressFamilies']
    assert unit('myink-pi-diagnosis.timer')['Timer']['OnUnitInactiveSec']=='15min'


def test_frozen_vendor_supports_provider_import_without_site_packages(tmp_path):
    from ops.pi.deploy.build_runtime import build
    root=tmp_path/'runtime';result=build(root,'a'*40)
    assert result['dependency_versions']['httpx'] and (root/'vendor/httpx/__init__.py').exists()
    probe="import sys;sys.path[:0]=[sys.argv[1]+'/code',sys.argv[1]+'/vendor'];import ops.pi.diagnosis_launcher;import httpx;assert httpx.__file__.startswith(sys.argv[1]+'/vendor/');assert all('site-packages' not in p for p in sys.path)"
    subprocess.run([sys.executable,'-I','-S','-B','-c',probe,str(root)],check=True,capture_output=True)
    assert (root/'code/src/myink/pi_audit.py').exists()
    assert list((root/'vendor').glob('*.dist-info/licenses/*'))


def test_built_runtime_contains_real_no_tool_guard_and_exact_guest_code(tmp_path):
    from ops.pi.deploy.build_runtime import build
    root=tmp_path/'runtime';build(root,'a'*40)
    probe="""import sys,shutil,json
from pathlib import Path
sys.path[:0]=[sys.argv[1]+'/code',sys.argv[1]+'/vendor']
from ops.pi.pi_config import make_pi_config
from ops.pi.policy import load_policy
from ops.pi.container_runtime import verify_source,runtime_fingerprint
root=Path(sys.argv[1]);policy=load_policy(root/'code/ops/pi/policy.example.json')
config=make_pi_config(root/'private',dict(base_url='http://127.0.0.1:1234',scope_token='synthetic'),policy)
assert '-e' in config['args'] and Path(config['args'][-1]).is_file()
guest=root/'guest';(guest/'node/bin').mkdir(parents=True);(guest/'pi/node_modules/@earendil-works/pi-coding-agent/dist/bundle').mkdir(parents=True)
elf=bytearray(64);elf[:7]=b'\\x7fELF\\x02\\x01\\x01';elf[16:18]=(2).to_bytes(2,'little');elf[18:20]=(183).to_bytes(2,'little');elf[20:24]=(1).to_bytes(4,'little');elf[52:54]=(64).to_bytes(2,'little');(guest/'node/bin/node').write_bytes(elf)
pkg=guest/'pi/node_modules/@earendil-works/pi-coding-agent';(pkg/'package.json').write_text(json.dumps(dict(version='1.1.0')));(pkg/'dist/bundle/cli.js').write_text('synthetic');(guest/'pi/package-lock.json').write_text('{}')
shutil.copytree(root/'code/ops/pi',guest/'code/ops/pi')
assert verify_source(guest,runtime_fingerprint(guest))['machine']=='aarch64'
"""
    subprocess.run([sys.executable,'-I','-S','-B','-c',probe,str(root)],check=True,capture_output=True)
