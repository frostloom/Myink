"""The main application consumes only validated, immutable audit data."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from ops.pi.tests.test_audit import record,store


def reader(root):return importlib.import_module('myink.pi_audit').AuditReader(root)


def publish(tmp_path,record,n=3):
    s=store(tmp_path)
    for i in range(n):
        s.append('event-'+str(i),dict(record,run_id='run-'+str(i%2),kind='tool' if i%2 else 'analysis'))
    root=tmp_path/'export';manifest=s.export(root)
    return s,root,manifest


def test_writer_main_reader_roundtrip_and_pagination(tmp_path,record):
    s,root,m=publish(tmp_path,record,5);r=reader(root)
    assert r.runs(limit=1)['total']==2
    assert [x['run_id'] for x in r.runs()['items']]==['run-0','run-1']
    events=r.events('run-0',limit=1,offset=1)
    assert events['total']==3 and events['limit']==1 and events['offset']==1
    assert events['items'][0]['sequence']==3
    assert r.events('run-1',kind='analysis')['total']==0
    s.path.unlink()
    assert r.events('run-0')['total']==3
    assert m['authority']=='audit_only' and m['watermark']['sequence']==5


def test_export_has_bounded_immutable_content_pages(tmp_path,record):
    s,root,m=publish(tmp_path,record,205)
    assert sum(p['event_count'] for p in m['pages'])==205
    assert all(0<p['event_count']<=100 for p in m['pages'])
    for p in m['pages']:
        data=root/'pages'/(p['sha256']+'.json')
        assert data.stat().st_size<=1048576
    assert reader(root).events('run-0',limit=100,offset=100)['total']==103


def test_export_also_splits_on_byte_limit(tmp_path,record):
    from ops.pi.audit import TEXT_FIELDS
    s=store(tmp_path)
    for i in range(100):
        s.append('large-'+str(i),dict(record,summary='x'*2000,details={k:'y'*900 for k in TEXT_FIELDS}))
    root=tmp_path/'export';m=s.export(root)
    assert len(m['pages'])>1
    assert all((root/'pages'/(p['sha256']+'.json')).stat().st_size<=1048576 for p in m['pages'])
    assert reader(root).events('run-1')['total']==100


def test_failed_export_keeps_previous_readable_manifest(tmp_path,record,monkeypatch):
    s,root,m=publish(tmp_path,record);before=(root/'manifest.json').read_bytes()
    s.append('new',dict(record,run_id='run-new'))
    replace=os.replace
    def fail(source,target):
        if Path(target).name=='manifest.json':raise OSError('synthetic interruption')
        return replace(source,target)
    with monkeypatch.context() as patch:
        patch.setattr(os,'replace',fail)
        with pytest.raises(OSError):s.export(root)
    assert (root/'manifest.json').read_bytes()==before
    assert reader(root).runs()['total']==2
    s.export(root)
    assert reader(root).runs()['total']==3


@pytest.mark.parametrize('change',['schema','extra','duplicate','index','page_hash','missing'])
def test_bad_snapshot_never_becomes_an_empty_or_verified_report(tmp_path,record,change):
    _,root,m=publish(tmp_path,record)
    target=root/'manifest.json'
    if change=='schema':m['schema_version']=99
    elif change=='extra':m['secret_path']='/etc/private'
    elif change=='index':m['runs'][0]['event_count']+=1
    elif change=='page_hash':
        page=root/'pages'/(m['pages'][0]['sha256']+'.json')
        page.write_bytes(page.read_bytes()+b' ')
    elif change=='missing':(root/'pages'/(m['pages'][0]['sha256']+'.json')).unlink()
    if change=='duplicate':
        text=target.read_text().replace('"schema_version":1','"schema_version":1,"schema_version":1',1)
        target.write_text(text)
    elif change not in ('page_hash','missing'):target.write_text(json.dumps(m))
    with pytest.raises((ValueError,OSError)):reader(root)


@pytest.mark.parametrize('link_kind',['symbolic','hard'])
def test_page_alias_does_not_read_outside_snapshot(tmp_path,record,link_kind,monkeypatch):
    _,root,m=publish(tmp_path,record);page=root/'pages'/(m['pages'][0]['sha256']+'.json')
    outside=tmp_path/'private.txt';outside.write_text('private-value');page.unlink()
    if link_kind=='symbolic':page.symlink_to(outside)
    else:page.hardlink_to(outside)
    original=os.open
    def guarded(path,*args,**kwargs):
        if Path(path).resolve()==outside:raise AssertionError('outside file must not be opened')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(os,'open',guarded)
    with pytest.raises(ValueError):reader(root)


@pytest.mark.parametrize('limit,offset',[(0,0),(101,0),(True,0),(25,-1),(25,True)])
def test_invalid_pagination_is_rejected(tmp_path,record,limit,offset):
    _,root,_=publish(tmp_path,record)
    with pytest.raises(ValueError):reader(root).runs(limit=limit,offset=offset)


def test_read_module_works_without_site_packages_or_execution_stack(tmp_path,record):
    _,root,_=publish(tmp_path,record)
    source=Path.cwd()/'src/myink/pi_audit.py'
    script="import importlib.util,sys; s=importlib.util.spec_from_file_location('standalone',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);assert m.AuditReader(sys.argv[2]).runs()['total']==2"
    result=subprocess.run([sys.executable,'-I','-S','-c',script,str(source),str(root)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
