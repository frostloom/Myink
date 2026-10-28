"""The scheduled reader has no provider or original-state write capability."""
from configparser import ConfigParser
from hashlib import sha256
import subprocess
import sys
from pathlib import Path
import pytest
from ops.pi.tests.test_live_observer import configured,update,api,Rows,NOW

ROOT='/home/ubuntu/myink-pi-managed'
DEPLOY=Path(__file__).parents[1]/'deploy'


def unit(name):
    parser=ConfigParser(interpolation=None,strict=False);parser.optionxform=str
    with (DEPLOY/name).open() as stream:parser.read_file(stream)
    return parser


def test_actual_source_requires_pinned_config_before_default_transport(configured,monkeypatch):
    path=update(configured,mode='ACTUAL');module=api();calls=[]
    def reader(config,run=None):
        if run is None:raise AssertionError('unapproved actual source must not start')
        return Rows()
    monkeypatch.setattr(module,'PsqlMetricsReader',reader)
    with pytest.raises(ValueError,match='pinned'):module.observe(path,clock=lambda:NOW)
    assert not Path(configured[1]['audit_path']).exists()


def test_wrong_pin_cannot_start_source_and_correct_pin_uses_default_only(configured,monkeypatch):
    path=update(configured,mode='ACTUAL');module=api();used=[]
    def reader(config,run=None):
        if run is None:used.append(config)
        return Rows(20)
    monkeypatch.setattr(module,'PsqlMetricsReader',reader)
    with pytest.raises(ValueError,match='config'):module.observe(path,clock=lambda:NOW,expected_config_sha256='0'*64)
    assert used==[]
    pin=sha256(path.read_bytes()).hexdigest()
    result=module.observe(path,clock=lambda:NOW,expected_config_sha256=pin)
    assert len(used)==1 and result['mode']=='ACTUAL'
    # This is only a mocked branch-selection test, not production evidence.


def test_cli_declares_expected_config_hash():
    result=subprocess.run([sys.executable,'-m','ops.pi.live_observer','--help'],capture_output=True,text=True,timeout=10)
    assert result.returncode==0 and '--config-sha256' in result.stdout


def test_unit_locks_fixed_tick_and_does_not_load_provider_keys():
    source=unit('myink-pi-observer.service');service=source['Service']
    assert service['Type']=='oneshot' and service['User']=='ubuntu' and service['SupplementaryGroups']=='docker'
    assert service['PrivateNetwork']=='yes' and service['RestrictAddressFamilies']=='AF_UNIX'
    assert service['ProtectSystem']=='strict' and service['ProtectHome']=='read-only'
    assert service['NoNewPrivileges']=='yes' and service['CapabilityBoundingSet']==''
    assert service['Restart']=='no' and int(service['TimeoutStartSec'])<=120
    assert '--nonblock --no-fork' in service['ExecStart']
    assert '--config-sha256 ${PI_OBSERVER_CONFIG_SHA256}' in service['ExecStart']
    assert service['EnvironmentFile']==ROOT+'/config/observer.env'
    text=(DEPLOY/'myink-pi-observer.service').read_text()
    assert 'SCOPED_GATEWAY_TOKEN' not in text and 'platform-model.json' not in text


def test_unit_keeps_original_ledgers_readonly_and_credentials_inaccessible():
    service=unit('myink-pi-observer.service')['Service']
    assert ROOT+'/state' in service['ReadOnlyPaths'].split()
    assert ROOT+'/state/credentials' in service['InaccessiblePaths'].split()
    allowed={ROOT+'/observations',ROOT+'/audit/state',ROOT+'/audit/export',ROOT+'/control/observer.lock'}
    assert set(service['ReadWritePaths'].split())==allowed


def test_timer_is_bounded_and_separate_from_paid_manager():
    timer=unit('myink-pi-observer.timer')['Timer']
    assert timer['OnBootSec']=='120' and timer['OnUnitInactiveSec']=='15min'
    assert timer['Unit']=='myink-pi-observer.service'
