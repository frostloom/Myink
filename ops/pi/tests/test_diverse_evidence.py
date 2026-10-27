"""Stopped ACTUAL metadata remains visible; never execute a candidate or retry."""
import importlib
import json
import pytest


def api():
    assert importlib.util.find_spec('ops.pi.tests.diverse_evidence'), 'stopped evidence reporter missing'
    return importlib.import_module('ops.pi.tests.diverse_evidence')


def row(identity,status='done',known=True,charge=7,reserve=100):
    return dict(operation_id=identity,kind='model-attempt',status=status,
        payload=json.dumps(dict(reserved_microyuan=reserve)),
        evidence=json.dumps(dict(usage_known=known,charged_microyuan=charge)))


def snapshots(new=()):
    old=row('historical','uncertain',False,100,100)
    return dict(operations=[old],events=[dict(old=True)]),dict(operations=[dict(old),*new],events=[dict(old=True),dict(new=True)])


def report(artifacts,before,after):
    return api().stopped_summary(['ordering','numeric','parsing'],dict(status='stopped',reason='protocol'),
        artifacts,before,after)


def test_protocol_failure_preserves_all_tasks_known_fee_and_available_cleanup():
    before,after=snapshots([row('new')])
    artifacts={'ordering':dict(started=True,selection=dict(verified=False),cleanup=[dict(removed=True)])}
    r=report(artifacts,before,after)
    assert len(r['tasks'])==r['scheduled_tasks']==3
    assert [x['state'] for x in r['tasks']]==['selection_failed_or_unknown','unstarted','unstarted']
    assert r['new_model_attempts']==1 and r['known_cost_microyuan']==7 and r['new_unknown']==0
    assert r['historical_unknown']==1 and r['original_billing_prefix_unchanged']
    assert r['cleanup_records']==1 and r['cleanup_removed_records']==1 and not r['current_resource_absence_verified']
    assert not r['cold_recovery_attempted'] and not r['candidate_adopted']


def test_development_failure_and_prior_null_remain_distinct_from_unstarted():
    before,after=snapshots([row('s1'),row('s2'),row('dev')])
    artifacts={'ordering':dict(started=True,selection=dict(verified=True,proposal=dict(task_id=None))),
        'numeric':dict(started=True,selection=dict(verified=True,proposal=dict(task_id='numeric')),development=dict(verified=False))}
    r=report(artifacts,before,after)
    assert [x['state'] for x in r['tasks']]==['not_selected','development_failed_or_unknown','unstarted']
    assert r['known_cost_microyuan']==21 and r['new_model_attempts']==3


def test_new_unknown_reservation_is_not_a_known_charge_or_historical_release():
    before,after=snapshots([row('settled'),row('unknown','uncertain',False,100,100)])
    r=report({},before,after)
    assert r['known_cost_microyuan']==7 and r['new_unknown']==1
    assert r['new_unresolved_reserved_microyuan']==100 and r['historical_unknown']==1
    assert not r['cold_recovery_attempted']


def test_missing_checkpoint_reports_unavailable_without_zero_fee_claim():
    before,_=snapshots()
    r=report({'ordering':dict(started=True)},before,None)
    assert r['billing_available'] is False and r['known_cost_microyuan'] is None
    assert r['new_unknown'] is None and r['new_model_attempts'] is None
    assert r['tasks'][0]['state']=='incomplete'


def test_history_drift_is_reported_instead_of_aborting_failure_report():
    before,after=snapshots([row('new')]);after['operations'][0]['status']='done'
    r=report({},before,after)
    assert r['original_billing_prefix_unchanged'] is False and len(r['tasks'])==3


def test_readonly_summary_does_not_contact_tools_or_network(monkeypatch):
    import socket,subprocess
    def forbidden(*a,**k):pytest.fail('metadata report must not start a process or network')
    monkeypatch.setattr(socket,'socket',forbidden);monkeypatch.setattr(subprocess,'Popen',forbidden)
    before,after=snapshots([row('new')]);assert report({},before,after)['known_cost_microyuan']==7
