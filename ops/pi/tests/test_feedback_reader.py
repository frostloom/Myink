"""Fixed feedback SQL contract; real PostgreSQL permissions are separately NOT_RUN."""
from datetime import datetime,timezone
import pytest
from ops.pi.db_reader import SnapshotCollector

WINDOW=dict(start=datetime(2020,1,1,tzinfo=timezone.utc),end=datetime(2020,1,2,tzinfo=timezone.utc))

def test_feedback_reader_is_fixed_readonly_and_explicit_admin(monkeypatch):
    reader=SnapshotCollector(None);seen=[]
    monkeypatch.setattr(reader,'_read',lambda request:seen.append(request) or [])
    snapshot=reader.collect_feedback(WINDOW,admin_scope=True)
    assert snapshot['rows']==[] and snapshot['has_more'] is False
    request=seen[0]
    assert request['read_only'] is True and request['params']['limit']==51
    assert 'FROM feedback' in request['sql'] and 'ORDER BY updated_at, id' in request['sql']
    assert not any(field in request['sql'] for field in ('contact','user_id','username','user_agent','attachments','page_url'))


def source_rows(count=1):
    from uuid import UUID
    return [dict(id=UUID(int=i+1),category='bug',status='open',description='删除按钮报错',
        created_at=WINDOW['start'],updated_at=WINDOW['start']) for i in range(count)]


@pytest.mark.parametrize('scope',[False,None,1,'admin'])
def test_feedback_requires_explicit_admin_before_read(monkeypatch,scope):
    reader=SnapshotCollector(None)
    monkeypatch.setattr(reader,'_read',lambda request:pytest.fail('unauthorized read'))
    with pytest.raises(ValueError):reader.collect_feedback(WINDOW,admin_scope=scope)


def test_feedback_limit51_and_bound_cursor_preserve_page(monkeypatch):
    reader=SnapshotCollector(None);requests=[]
    monkeypatch.setattr(reader,'_read',lambda r:requests.append(r) or source_rows(51))
    snapshot=reader.collect_feedback(WINDOW,admin_scope=True)
    assert len(snapshot['rows'])==50 and snapshot['has_more'] is True
    assert snapshot['next_cursor']['id']==snapshot['rows'][-1]['id']
    monkeypatch.setattr(reader,'_read',lambda r:requests.append(r) or [])
    reader.collect_feedback(WINDOW,admin_scope=True,cursor=snapshot['next_cursor'])
    assert '(updated_at, id) > (:cursor_time, :cursor_id)' in requests[-1]['sql']
    assert requests[-1]['params']['cursor_id']==snapshot['rows'][-1]['id']
    for bad in ({**snapshot['next_cursor'],'window_sha256':'0'*64},
                {**snapshot['next_cursor'],'id':'../../foreign'},
                {**snapshot['next_cursor'],'updated_at':WINDOW['end'].isoformat()},
                {**snapshot['next_cursor'],'scope':'user'},
                {**snapshot['next_cursor'],'sql':'DELETE FROM feedback'}):
        with pytest.raises(ValueError):reader.collect_feedback(WINDOW,admin_scope=True,cursor=bad)


@pytest.mark.parametrize('fault',['duplicate','privacy','out_of_window','unordered','over_limit','oversize','bad_category'])
def test_feedback_rejects_bad_driver_rows(monkeypatch,fault):
    rows=source_rows(2)
    if fault=='duplicate':rows[1]=rows[0]
    elif fault=='privacy':rows[0]['contact']='private@example.invalid'
    elif fault=='out_of_window':rows[0]['updated_at']=WINDOW['end']
    elif fault=='unordered':rows.reverse()
    elif fault=='over_limit':rows=source_rows(52)
    elif fault=='oversize':rows[0]['description']='x'*2001
    else:rows[0]['category']='trusted-admin'
    reader=SnapshotCollector(None);monkeypatch.setattr(reader,'_read',lambda r:rows)
    with pytest.raises(ValueError):reader.collect_feedback(WINDOW,admin_scope=True)


def test_feedback_fixed_sql_validation_rejects_drift(monkeypatch):
    reader=SnapshotCollector(None);requests=[]
    monkeypatch.setattr(reader,'_read',lambda r:requests.append(r) or [])
    reader.collect_feedback(WINDOW,admin_scope=True);request=requests[0]
    reader._validate_request(request)
    for bad in ({**request,'sql':'DELETE FROM feedback'},{**request,'read_only':False},
                {**request,'sql':request['sql'].replace('description','contact')},
                {**request,'params':{**request['params'],'limit':500}},
                {**request,'timeout_ms':5001}):
        with pytest.raises(ValueError):reader._validate_request(bad)
