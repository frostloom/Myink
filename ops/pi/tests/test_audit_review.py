"""Regressions found by the independent audit foundation review."""
import json
from pathlib import Path
import pytest
from ops.pi.audit import digest
from ops.pi.tests.test_audit import record,store
from ops.pi.tests.test_audit_reader import publish,reader


@pytest.mark.parametrize('secret',[{'password':{'value':'nested-secret-value'}},{'token':['nested-secret-value','second-secret-value']},{'password':json.dumps({'value':'nested-secret-value'})}])
def test_nested_credential_values_are_removed_from_every_text_surface(tmp_path,record,secret):
    text=json.dumps(secret);s=store(tmp_path)
    follow=dict(test_id='next',scheduled_for='2026-10-29T18:00:00+00:00',target_run_id='run-1',target_version_sha256='b'*64,criterion=text,kind='regression',status='planned')
    s.append('nested',dict(record,summary=text,details=dict(reason=text),followups=[follow]))
    s.export(tmp_path/'export');r=reader(tmp_path/'export')
    output=json.dumps(r.events('run-1'))
    assert 'nested-secret-value' not in output and 'second-secret-value' not in output


def test_reader_refuses_parent_directory_replacement_before_open(tmp_path,record,monkeypatch):
    _,root,_=publish(tmp_path,record);r=reader(root)
    outside=tmp_path/'outside';(root/'pages').rename(outside);(root/'pages').symlink_to(outside,target_is_directory=True)
    import os
    original=os.open
    def guarded(path,*args,**kwargs):
        if Path(path).is_absolute() and Path(path).resolve().is_relative_to(outside):raise AssertionError('outside page must not be opened')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(os,'open',guarded)
    with pytest.raises(ValueError):r.events('run-0')


def test_later_no_release_run_and_late_history_cannot_erase_newer_deployment(tmp_path,record):
    s=store(tmp_path);v=dict(deployment_id='new',generation=2,owner='pi')
    s.append('new',dict(record,kind='deployment',status='passed',evidence_domain='online_business',occurred_at='2026-10-28T10:00:00+00:00',version=v))
    s.append('other-run',dict(record,run_id='run-2',kind='deployment',status='no_release',occurred_at='2026-10-28T11:00:00+00:00'))
    s.append('late-old',dict(record,kind='rollback',status='rolled_back',evidence_domain='online_business',occurred_at='2026-10-28T09:00:00+00:00',version=dict(v,deployment_id='old',generation=1)))
    s.export(tmp_path/'export');day=reader(tmp_path/'export').daily('2026-10-28')
    assert day['release_state']=='deployed'
    assert {x['run_id']:x['state'] for x in day['release_runs']}=={'run-1':'deployed','run-2':'no_release'}


@pytest.mark.parametrize('field',['run_count','day_count','watermark','first_sequence','last_sequence'])
def test_manifest_bool_counters_and_sequences_are_rejected(tmp_path,record,field):
    _,root,m=publish(tmp_path,record,1)
    if field=='run_count':m['runs'][0]['event_count']=True
    elif field=='day_count':m['days'][0]['event_count']=True
    elif field=='watermark':m['watermark']['sequence']=True
    else:m['pages'][0][field]=True
    m['snapshot_sha256']=digest({k:v for k,v in m.items() if k!='snapshot_sha256'})
    (root/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError):reader(root)


def test_small_unfiltered_page_skips_unrequested_pages(tmp_path,record,monkeypatch):
    _,root,_=publish(tmp_path,record,205);r=reader(root);calls=[];original=r._page
    def page(key):calls.append(key);return original(key)
    monkeypatch.setattr(r,'_page',page)
    result=r.events('run-0',limit=1)
    assert result['total']==103 and len(result['items'])==1
    assert len(calls)==1


def test_filtered_pagination_retains_only_requested_records(tmp_path,record,monkeypatch):
    _,root,_=publish(tmp_path,record,205);r=reader(root);original=r._page
    class Tracked(dict):
        live=0;peak=0
        def __init__(self,event):
            super().__init__(event);Tracked.live+=1;Tracked.peak=max(Tracked.peak,Tracked.live)
        def __del__(self):Tracked.live-=1
    monkeypatch.setattr(r,'_page',lambda key:(Tracked(e) for e in original(key)))
    result=r.events('run-0',kind='analysis',limit=1)
    assert result['total']==103 and len(result['items'])==1
    assert Tracked.peak<=3


def test_existing_redaction_marker_remains_stable_for_old_immutable_records(record):
    from ops.pi.audit import validate_record
    value='password=[REDACTED]; public data'
    assert validate_record(dict(record,summary=value))['summary']==value


def test_daily_aggregate_refuses_unbounded_body_before_memory_growth(tmp_path,record):
    from ops.pi.audit import TEXT_FIELDS,encoded
    s=store(tmp_path);large=dict(record,details={key:'x'*900 for key in TEXT_FIELDS})
    first=s.append('large-0',large)
    count=8388608//len(encoded(first))+1
    for index in range(1,count):s.append('large-'+str(index),large)
    s.export(tmp_path/'export');r=reader(tmp_path/'export')
    with pytest.raises(ValueError,match='daily audit exceeds'):r.daily('2026-10-29')
