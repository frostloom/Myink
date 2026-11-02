from types import SimpleNamespace
from datetime import datetime,timezone
import pytest
from ops.pi.audit import AuditStore
from ops.pi.nightly_outcome import publish


@pytest.mark.parametrize('requests,cost',[(0,0),(1,None)])
def test_no_release_event_matches_existing_admin_release_contract(tmp_path,requests,cost):
    tmp_path.chmod(0o700);gate=SimpleNamespace(mode='SIMULATED',clock=lambda:datetime(2026,11,1,tzinfo=timezone.utc))
    publish(gate,'night-1',tmp_path,'no_writing_data' if requests==0 else 'no_task',model_requests=requests)
    events=AuditStore(tmp_path/'outcome-audit/events.sqlite').events()
    assert len(events)==1
    event=events[0]
    assert event['kind']=='deployment' and event['status']=='no_release'
    assert event['details']['model_requests']==requests and event['details']['known_cost_microyuan']==cost


def test_no_release_metadata_retries_reuse_original_time(tmp_path):
    from datetime import timedelta
    tmp_path.chmod(0o700);now=[datetime(2026,11,1,tzinfo=timezone.utc)]
    gate=SimpleNamespace(mode='SIMULATED',clock=lambda:now[0])
    publish(gate,'night-1',tmp_path,'no_writing_data')
    original=AuditStore(tmp_path/'outcome-audit/events.sqlite').events()
    now[0]+=timedelta(minutes=5)
    publish(gate,'night-1',tmp_path,'no_writing_data')
    assert AuditStore(tmp_path/'outcome-audit/events.sqlite').events()==original
