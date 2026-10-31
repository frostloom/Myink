"""Fixed followup component, root registry and non-provider service scopes."""
from pathlib import Path
from configparser import ConfigParser
from types import SimpleNamespace
import sys
import pytest
from ops.pi.tests.test_observer_entry import module

DEPLOY=Path(__file__).parents[1]/'deploy'
ROOT='/home/ubuntu/myink-pi-managed'


def unit(name):
    parser=ConfigParser(interpolation=None,strict=False);parser.optionxform=str
    with (DEPLOY/name).open() as stream:parser.read_file(stream)
    return parser


def test_fixed_followup_component_imports_only_after_closed_verification(monkeypatch,tmp_path):
    value=module();calls=[]
    monkeypatch.setattr(value,'verify_release',lambda *a:calls.append('verified') or tmp_path)
    monkeypatch.setitem(sys.modules,'ops.pi.followup',SimpleNamespace(run_due=lambda p,h:calls.append(('followup',p,h)) or dict(status='planned')))
    monkeypatch.setattr(sys,'argv',['entry','--component','followup','--config','/fixed/registry','--config-sha256','a'*64])
    assert value.main()==0 and calls==['verified',('followup','/fixed/registry','a'*64)]


def test_failed_runtime_never_imports_or_invokes_followup(monkeypatch):
    value=module();calls=[]
    monkeypatch.setattr(value,'verify_release',lambda *a:(_ for _ in ()).throw(ValueError()))
    monkeypatch.setitem(sys.modules,'ops.pi.followup',SimpleNamespace(run_due=lambda *a:calls.append(1)))
    monkeypatch.setattr(sys,'argv',['entry','--component','followup','--config','/fixed/registry','--config-sha256','a'*64])
    assert value.main()==1 and calls==[]


def test_service_is_once_bounded_and_has_no_provider_or_source_writes():
    u=unit('myink-pi-followup.service');s=u['Service'];text=(DEPLOY/'myink-pi-followup.service').read_text()
    assert s['User']=='ubuntu' and s['SupplementaryGroups']=='docker' and s['Type']=='oneshot'
    assert s['PrivateNetwork']=='yes' and s['RestrictAddressFamilies']=='AF_UNIX' and s['ProtectSystem']=='strict'
    assert s['Restart']=='no' and int(s['TimeoutStartSec'])<=330
    assert '-I -S -B' in s['ExecStart'] and '--component followup' in s['ExecStart']
    assert '--config '+ROOT+'/config/followup-registry.json' in s['ExecStart']
    assert s['EnvironmentFile']==ROOT+'/config/followup.env'
    assert set(s['ReadWritePaths'].split())=={ROOT+'/followups',ROOT+'/audit/state',ROOT+'/audit/export'}
    assert {ROOT+'/jobs',ROOT+'/state',ROOT+'/config',ROOT+'/releases',ROOT+'/control/maintenance.lock'}<=set(s['ReadOnlyPaths'].split())
    assert ROOT+'/state/credentials' in s['InaccessiblePaths'].split() and 'platform-model.json' not in text
    assert 'flock ' not in s['ExecStart']  # Worker itself owns the shared lock.


def test_timer_cannot_override_real_due_time_or_replay_policy():
    timer=unit('myink-pi-followup.timer')['Timer']
    assert timer['OnUnitInactiveSec']=='5min' and timer['Unit']=='myink-pi-followup.service'
