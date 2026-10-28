"""Durable fixed-phase dispatch and real subprocess cancellation/capture."""
from pathlib import Path
from threading import Event,Thread
import importlib,os,sys,time
import pytest
from ops.pi.development_inputs import file_hash,ledger_snapshot,read_json
from ops.pi.tests.test_autonomy_profile import profile,research_config,diagnosis_config,config_file,configured,proof,write,NOW


def api():return importlib.import_module('ops.pi.autonomy_dispatch')


@pytest.fixture
def stage(profile):
    pp,p,c,context=profile;r=importlib.import_module('ops.pi.autonomy_profile').research(pp,file_hash(pp),c['observation_receipt_path'],clock=lambda:NOW)
    return p,r,c


def envelope(component,mode='SIMULATED'):
    return dict(schema='pi-autonomy-worker-result-v1',component=component,mode=mode,status='done',model_requests=0,outcome=dict(status='fixed-synthetic'))


def test_simulated_phase_is_claimed_once_and_never_replayed(stage):
    p,r,c=stage;calls=[];before=ledger_snapshot(c['ledger_path'])
    def run(component,path,pin,cancel):calls.append(component);return envelope(component)
    value=api().run(p,'investigation',r,r['claim_path'],runner=run)
    assert value['status']=='done' and value['outcome']['status']=='fixed-synthetic' and calls==['investigation']
    assert (Path(r['claim_path'])/'phase-investigation/receipt.json').exists() and ledger_snapshot(c['ledger_path'])==before
    with pytest.raises(ValueError):api().run(p,'investigation',r,r['claim_path'],runner=run)
    assert calls==['investigation']


@pytest.mark.parametrize('fault',['actual_callback','canonical_shadow','component','config_pin','foreign_config','cancelled'])
def test_invalid_dispatch_never_calls_runner_or_claims(stage,fault):
    p,r,c=stage;event=Event();component='investigation';calls=[]
    if fault=='actual_callback':p=dict(p,mode='ACTUAL')
    elif fault=='canonical_shadow':p=dict(p,host=dict(p['host'],ledger_path='/home/ubuntu/myink-pi-managed/state/ledger.sqlite'))
    elif fault=='component':component='shell'
    elif fault=='config_pin':r=dict(r,config_sha256='f'*64)
    elif fault=='foreign_config':r=dict(r,config_path=str(Path(r['claim_path'])/'intent.json'),config_sha256=file_hash(Path(r['claim_path'])/'intent.json'))
    else:event.set()
    with pytest.raises((ValueError,OSError,KeyError,TypeError)):api().run(p,component,r,r['claim_path'],runner=lambda *a:calls.append(a),cancel=event)
    assert not calls and not list(Path(r['claim_path']).glob('phase-*'))


def test_unknown_callback_completion_is_retained_as_uncertain_without_replay(stage):
    p,r,c=stage;calls=[]
    def fail(*args):calls.append(True);raise RuntimeError('synthetic completion loss')
    value=api().run(p,'investigation',r,r['claim_path'],runner=fail)
    assert value['status']=='uncertain' and value['model_requests'] is None and len(calls)==1
    claim=Path(r['claim_path'])/'phase-investigation';assert (claim/'intent.json').exists() and (claim/'failure.json').exists()
    with pytest.raises(ValueError):api().run(p,'investigation',r,r['claim_path'],runner=fail)
    assert len(calls)==1


def test_actual_command_is_fixed_and_environment_excludes_parent_secrets(stage,monkeypatch):
    p,r,c=stage;monkeypatch.setenv('PLATFORM_MODEL_API_KEY','must-not-be-inherited');monkeypatch.setenv('PYTHONPATH','/untrusted')
    argv,env=api().command(dict(p,mode='ACTUAL'),'investigation',r)
    assert argv[:2]==['/usr/bin/setpriv','--reuid=ubuntu'] and '--regid=ubuntu' in argv and '--groups=docker' in argv
    assert '--no-new-privs' in argv and '--bounding-set=-all' in argv and '-I' in argv and '-S' in argv and '-B' in argv
    assert 'PLATFORM_MODEL_API_KEY' not in env and 'PYTHONPATH' not in env and env['PI_OBSERVER_RUNTIME_SHA256']==p['controller_sha256']
    assert argv[-2:]==['--config-sha256',r['config_sha256']]


def test_native_capture_waits_for_real_child_and_retains_private_output(tmp_path):
    tmp_path.chmod(0o700);result=api()._capture([str(Path(sys.executable).resolve()),'-I','-S','-B','-c','print("fixed-result")'],dict(PATH='/usr/bin:/bin'),tmp_path,3,Event(),(os.geteuid(),os.getegid()))
    assert result['returncode']==0 and result['interrupted'] is False and (tmp_path/'stdout-private.log').read_text()=='fixed-result\n'
    assert (tmp_path/'pid.json').exists() and (tmp_path/'stdout-private.log').stat().st_mode&0o777==0o600


def test_native_sigterm_allows_owned_child_cooperative_cleanup(tmp_path):
    tmp_path.chmod(0o700);event=Event();ready=tmp_path/'ready';cleanup=tmp_path/'cleanup'
    script='import signal,time,sys\nfrom pathlib import Path\ndef stop(*args):\n Path(sys.argv[2]).write_text("cleaned")\n raise SystemExit(0)\nsignal.signal(signal.SIGTERM,stop)\nPath(sys.argv[1]).write_text("ready")\nwhile True: time.sleep(.05)\n'
    def cancel():
        until=time.monotonic()+5
        while not ready.exists() and time.monotonic()<until:time.sleep(.01)
        event.set()
    thread=Thread(target=cancel);thread.start()
    result=api()._capture([str(Path(sys.executable).resolve()),'-I','-S','-B','-c',script,str(ready),str(cleanup)],dict(PATH='/usr/bin:/bin'),tmp_path,8,event,(os.geteuid(),os.getegid()));thread.join(timeout=6)
    assert not thread.is_alive() and result['interrupted'] is True and result['reason']=='cancelled' and cleanup.read_text()=='cleaned' and result['returncode']==0


def test_native_capture_limit_stops_and_retains_oversize_output(tmp_path):
    tmp_path.chmod(0o700);result=api()._capture([str(Path(sys.executable).resolve()),'-I','-S','-B','-c','import sys;sys.stdout.write("x"*1100000)'],dict(PATH='/usr/bin:/bin'),tmp_path,3,Event(),(os.geteuid(),os.getegid()))
    assert result['interrupted'] is True and result['reason']=='capture_limit' and (tmp_path/'stdout-private.log').stat().st_size>1048576
