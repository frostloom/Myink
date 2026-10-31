"""Human-authorized rebuild preserves the old pending artifact and accounting."""
from datetime import timedelta
from pathlib import Path
import json,sqlite3,uuid
import pytest
from ops.pi.tests.test_nightly_gate import case
from ops.pi.audit import digest
from ops.pi.development_inputs import file_hash,ledger_snapshot


def setup(case):
    g=case[0](True);old=str(uuid.uuid4());g.begin(old,'2026-10-31');g.bind_task(old,'original-task');g.ready(old,case[2]);new=str(uuid.uuid4())
    value=dict(schema='pi-nightly-human-rebuild-v1',mode='SIMULATED',issuer='human_operator',action='prepare_same_candidate',cycle_id=old,package_sha256=digest(case[2]),new_cycle_id=new,night='2026-11-01',base_image_id='sha256:'+'9'*64,compatibility_sha256='8'*64,issued_at=case[1][0].isoformat(),expires_at=(case[1][0]+timedelta(hours=2)).isoformat())
    path,pin=case[3](value,'rebuild');return g,old,new,path,pin,value


def test_bound_human_rebuild_archives_without_faking_a_completed_comparison(case):
    g,old,new,path,pin,value=setup(case);before=ledger_snapshot(g.state),ledger_snapshot(g.billing)
    result=g.begin_rebuild(old,path,pin)
    assert result['phase']=='preparing' and result['cycle_id']==new and result['task_id']=='original-task'
    with g._connection() as c:
        row=g._row(c,old);assert row['phase']=='awaiting_approval' and row['deployment'] is None and row['result_sha256'] is None and json.loads(row['package'])==case[2]
        assert not c.execute("SELECT 1 FROM approval_events WHERE cycle_id=? AND kind='comparison_complete'",(old,)).fetchone()
    assert (ledger_snapshot(g.state),ledger_snapshot(g.billing))==before
    assert g.begin_rebuild(old,path,pin)['cycle_id']==new
    for cycle in (old,new):
        for action in ('deploy','github_push','registry_push','observe_metrics'):
            with pytest.raises(ValueError):g.require_action(cycle,action)


@pytest.mark.parametrize('fault',['issuer','package','expiry','action'])
def test_invalid_rebuild_permission_does_not_upgrade_or_change_pending_state(case,fault):
    g,old,new,path,pin,v=setup(case)
    if fault=='issuer':v['issuer']='model'
    elif fault=='package':v['package_sha256']='0'*64
    elif fault=='expiry':v['expires_at']=(case[1][0]-timedelta(seconds=1)).isoformat()
    else:v['action']='deploy'
    path.write_text(json.dumps(v))
    with pytest.raises(ValueError):g.begin_rebuild(old,path,file_hash(path))
    assert g.status()['cycle_id']==old
    with sqlite3.connect(g.path) as c:assert c.execute('PRAGMA user_version').fetchone()[0]==7402


def test_rebuild_cannot_change_original_fix_or_base_and_cannot_run_paid_hosts(case):
    g,old,new,path,pin,v=setup(case);g.begin_rebuild(old,path,pin)
    g.require_preparation(new,'original-task',v['base_image_id'])
    with pytest.raises(ValueError):g.require_preparation(new,'another-task',v['base_image_id'])
    with pytest.raises(ValueError):g.require_preparation(new,'original-task','sha256:'+'a'*64)
    from ops.pi.nightly_host import admission
    for component in ('autonomy','manager','investigation','sdk_review','observer'):
        assert admission(g,component)['allowed'] is False
    bad=dict(case[2],source_sha256='0'*64)
    with pytest.raises(ValueError):g.ready(new,bad)
    assert g.ready(new,case[2])['phase']=='awaiting_approval'


def test_destination_conflict_rolls_back_upgrade_and_archival(case):
    g,old,new,path,pin,v=setup(case);v['night']='2026-10-31';path.write_text(json.dumps(v))
    with pytest.raises((ValueError,sqlite3.IntegrityError)):g.begin_rebuild(old,path,file_hash(path))
    assert g.status()['cycle_id']==old
    with sqlite3.connect(g.path) as c:assert c.execute('PRAGMA user_version').fetchone()[0]==7402


def test_failure_after_ddl_rolls_back_schema_version_and_old_candidate(case):
    g,old,new,path,pin,v=setup(case)
    with sqlite3.connect(g.path) as c:c.execute("CREATE TRIGGER fail_new_rebuild BEFORE INSERT ON approval_cycles BEGIN SELECT RAISE(ABORT,'forced insert failure');END")
    with pytest.raises(sqlite3.IntegrityError):g.begin_rebuild(old,path,pin)
    with sqlite3.connect(g.path) as c:
        assert c.execute('PRAGMA user_version').fetchone()[0]==7402
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='approval_rebuilds'").fetchone()
    assert g.status()['cycle_id']==old


def test_archived_record_and_forward_link_are_immutable(case):
    g,old,new,path,pin,v=setup(case);g.begin_rebuild(old,path,pin)
    with sqlite3.connect(g.path) as c:
        for query,args in [('UPDATE approval_cycles SET phase=? WHERE cycle_id=?',('blocked',old)),('DELETE FROM approval_rebuilds WHERE old_cycle_id=?',(old,))]:
            with pytest.raises(sqlite3.IntegrityError):c.execute(query,args)
