"""Independent readonly product observer has no provider or product-write path."""
from configparser import ConfigParser
from pathlib import Path
import importlib,sys
import pytest

DEPLOY=Path(__file__).parents[1]/'deploy';ROOT='/home/ubuntu/myink-pi-managed'


def unit(name):
    p=ConfigParser(interpolation=None,strict=False);p.optionxform=str
    with (DEPLOY/name).open() as stream:p.read_file(stream)
    return p


def test_product_entry_is_fixed_stdlib_route_without_vendor_or_paid_kernel(tmp_path,monkeypatch,capsys):
    from ops.pi.tests.test_observer_entry import module
    entry=module();seen=[];old=list(sys.path)
    monkeypatch.setattr(entry,'verify_release',lambda *a:tmp_path/'code')
    target=importlib.import_module('ops.pi.product_preflight');monkeypatch.setattr(target,'observe_and_publish',lambda *a:seen.append(a) or dict(status='recorded',model_requests=0,release_allowed=False))
    monkeypatch.setattr(sys,'argv',['entry.py','--component','product_observer','--config','/fixed/product-observer.json','--config-sha256','a'*64]);monkeypatch.setattr(sys,'dont_write_bytecode',True)
    try:assert entry.main()==0
    finally:sys.path[:]=old
    assert seen==[('/fixed/product-observer.json','a'*64)] and 'recorded' in capsys.readouterr().out and not (tmp_path/'vendor').exists()


def test_product_unit_is_independent_and_has_only_readonly_product_access():
    p=unit('myink-pi-product-observer.service');s=p['Service']
    assert s['User']=='ubuntu' and s['SupplementaryGroups']=='docker' and s['Type']=='oneshot'
    assert s['PrivateNetwork']=='yes' and s['RestrictAddressFamilies']=='AF_UNIX' and s['ProtectSystem']=='strict'
    assert s['NoNewPrivileges']=='yes' and s['CapabilityBoundingSet']=='' and s['Restart']=='no'
    assert s['EnvironmentFile']==ROOT+'/config/product-observer.env' and '--component product_observer' in s['ExecStart']
    assert '--config '+ROOT+'/config/product-observer.json ' in s['ExecStart'] and '--nonblock --no-fork' in s['ExecStart']
    assert ROOT+'/state' in s['ReadOnlyPaths'].split() and ROOT+'/state/credentials' in s['InaccessiblePaths'].split()
    assert set(s['ReadWritePaths'].split())=={ROOT+'/product-observations',ROOT+'/audit/state',ROOT+'/audit/export',ROOT+'/control/product-observer.lock'}
    text=(DEPLOY/'myink-pi-product-observer.service').read_text();assert 'TOKEN' not in text and 'platform-model' not in text
    assert int(s['TimeoutStartSec'])<=120 and int(s['MemoryMax'].removesuffix('M'))<=256


def test_product_timer_does_not_replace_or_wake_paid_manager():
    timer=unit('myink-pi-product-observer.timer')['Timer']
    assert timer['Unit']=='myink-pi-product-observer.service' and timer['OnUnitInactiveSec']=='15min' and timer['OnBootSec']=='120'
