"""Daily summaries preserve evidence domain, version identity and unfinished work."""
from datetime import datetime,timezone
import pytest
from ops.pi.tests.test_audit import record,store
from ops.pi.tests.test_audit_reader import reader


def exported(s,tmp_path):
    s.export(tmp_path/'export');return reader(tmp_path/'export')


def test_day_uses_shanghai_occurrence_and_marks_unknown_historical_time(tmp_path,record):
    s=store(tmp_path)
    s.append('old',dict(record,occurred_at='2026-10-28T15:59:59+00:00'))
    s.append('new',dict(record,occurred_at='2026-10-28T16:00:00+00:00'))
    s.append('unknown',record)
    r=exported(s,tmp_path)
    assert r.daily('2026-10-28')['event_count']==1
    day=r.daily('2026-10-29')
    assert day['event_count']==2 and day['unknown_occurrence_count']==1
    assert r.daily('2026-10-30')['event_count']==0
    with pytest.raises(ValueError):r.daily('../private')


def test_release_states_are_evidence_not_inferred_from_development_pass(tmp_path,record):
    s=store(tmp_path);s.append('dev',dict(record,kind='development',status='candidate_ready'))
    assert exported(s,tmp_path).daily('2026-10-29')['release_state']=='unknown'
    s.append('no-release',dict(record,kind='deployment',status='no_release'))
    assert exported(s,tmp_path).daily('2026-10-29')['release_state']=='no_release'
    s.append('sim',dict(record,kind='deployment',status='passed',mode='SIMULATED',evidence_domain='synthetic'))
    assert exported(s,tmp_path).daily('2026-10-29')['release_state']=='no_release'
    s.append('actual',dict(record,kind='deployment',status='passed',evidence_domain='online_business',version=dict(deployment_id='deploy-1',generation=1,owner='pi')))
    assert exported(s,tmp_path).daily('2026-10-29')['release_state']=='deployed'
    s.append('restore',dict(record,kind='rollback',status='rolled_back',evidence_domain='online_business'))
    assert exported(s,tmp_path).daily('2026-10-29')['release_state']=='rolled_back'


def test_same_code_redeploy_versions_remain_distinct_and_changes_not_double_counted(tmp_path,record):
    s=store(tmp_path);change=dict(path='src/example.py',category='production',added=4,deleted=2)
    v=dict(source_commit='a'*40,candidate_sha256='b'*64,deployment_id='one',generation=1)
    s.append('plan',dict(record,kind='development',version=v,changes=[change]))
    s.append('test',dict(record,kind='test',version=v,changes=[change]))
    s.append('redeploy',dict(record,kind='version',version=dict(v,deployment_id='two',generation=2)))
    d=exported(s,tmp_path).daily('2026-10-29')
    assert len(d['versions'])==2
    assert d['change_scope']==[dict(change,candidate_sha256='b'*64,source_commit='a'*40)]
    assert d['known_cost_microyuan'] is None
    assert d['observed_samples']==0


def test_due_plan_stays_planned_until_matching_actual_test_result(tmp_path,record):
    s=store(tmp_path);plan=dict(test_id='tomorrow',scheduled_for='2026-10-29T18:00:00+00:00',target_run_id='run-1',target_version_sha256='b'*64,criterion='18 cases pass',kind='regression',status='planned')
    s.append('plan',dict(record,followups=[plan]))
    s.append('wrong-version',dict(record,kind='test',status='passed',version=dict(candidate_sha256='c'*64),details=dict(test_id='tomorrow')))
    r=exported(s,tmp_path);f=r.daily('2026-10-29')['next_tests'][0]
    assert f['status']=='planned' and f['result'] is None
    s.append('simulated',dict(record,kind='test',status='passed',mode='SIMULATED',evidence_domain='synthetic',version=dict(candidate_sha256='b'*64),details=dict(test_id='tomorrow')))
    assert exported(s,tmp_path).daily('2026-10-29')['next_tests'][0]['result'] is None
    s.append('real',dict(record,occurred_at='2026-10-29T18:30:00+00:00',kind='test',status='failed',version=dict(candidate_sha256='b'*64),details=dict(test_id='tomorrow')))
    f=exported(s,tmp_path).daily('2026-10-29')['next_tests'][0]
    assert f['status']=='planned' and f['result']['status']=='failed'


def test_enhancement_inventory_preserves_availability_and_provenance(tmp_path,record):
    s=store(tmp_path)
    s.append('inventory',dict(record,kind='enhancement',status='blocked',details=dict(reference='memory.hindsight',availability='not_connected',reason='No runtime adapter')))
    s.append('inventory-tools',dict(record,kind='enhancement',details=dict(reference='tool.fixed_allowlist',availability='deployed')))
    items=exported(s,tmp_path).enhancements()['items']
    assert [x['details']['reference'] for x in items]==['memory.hindsight','tool.fixed_allowlist']
    assert items[0]['details']['availability']=='not_connected'
