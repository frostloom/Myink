"""One author fixpass for the three independent final-review findings."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json,os,stat,sys
import pytest
from ops.pi.tests.test_followup import configured,run,report,api
from ops.pi.tests.test_observer_entry import module


@pytest.mark.parametrize('overlap',['candidate','inside_candidate','source','contains_inputs','contains_audit','audit_inside_candidate'])
def test_all_writable_destinations_are_separate_from_protected_inputs(configured,overlap):
    p,c=configured;e=c['entries'][0];candidate=Path(e['candidate_path']);candidate.chmod(0o700)
    if overlap=='candidate':c['export_root']=str(candidate)
    elif overlap=='inside_candidate':
        inside=candidate/'export';inside.mkdir(mode=0o700);c['export_root']=str(inside)
    elif overlap=='source':
        source=Path(e['source_path']);source.chmod(0o700);c['export_root']=str(source)
    elif overlap=='contains_inputs':c['export_root']=str(candidate.parent)
    elif overlap=='contains_audit':c['export_root']=str(Path(c['audit_path']).parent)
    else:
        target=candidate/'events.sqlite';target.write_bytes(Path(c['audit_path']).read_bytes());target.chmod(0o600);c['audit_path']=str(target)
    p.write_text(json.dumps(c))
    with pytest.raises(ValueError):api()._load(p,sha256(p.read_bytes()).hexdigest(),lambda *a:report(),lambda:None)
    assert list(Path(c['root']).iterdir())==[]


@pytest.mark.parametrize('status',['blocked','failed'])
def test_failed_or_blocked_first_and_cached_tick_exit_nonzero(configured,monkeypatch,tmp_path,status):
    def backend(*args):
        value=report(status!='failed')
        if status=='blocked':value['cleanup'][0]['removed']=False
        return value
    first=run(configured,backend);cached=run(configured,lambda *a:pytest.fail('replayed'))
    assert first['status']==cached['status']==status
    for result in (first,cached):
        entry=module();monkeypatch.setattr(entry,'verify_release',lambda *a:tmp_path)
        monkeypatch.setitem(sys.modules,'ops.pi.followup',SimpleNamespace(run_due=lambda *a:result))
        monkeypatch.setattr(sys,'argv',['entry','--component','followup','--config','/registry','--config-sha256','a'*64])
        assert entry.main()==1


def test_parent_and_intent_are_synced_before_any_checker_execution(configured,monkeypatch):
    m=api();parent=Path(configured[1]['root']);parent_inode=parent.stat().st_ino;real=os.fsync;events=[];before=[]
    def fsync(fd):
        info=os.fstat(fd)
        events.append('parent' if info.st_ino==parent_inode else 'directory' if stat.S_ISDIR(info.st_mode) else 'file')
        return real(fd)
    monkeypatch.setattr(m.os,'fsync',fsync)
    def backend(*args):before.extend(events);return report()
    run(configured,backend)
    assert before[:3]==['parent','file','directory']


def test_parent_sync_failure_blocks_before_execution_and_never_replays(configured,monkeypatch):
    m=api();parent_inode=Path(configured[1]['root']).stat().st_ino;real=os.fsync;called=[]
    def fsync(fd):
        if os.fstat(fd).st_ino==parent_inode:raise OSError('synthetic fsync refusal')
        return real(fd)
    with monkeypatch.context() as patch:
        patch.setattr(m.os,'fsync',fsync)
        with pytest.raises(OSError):run(configured,lambda *a:called.append(1) or report())
    assert not called
    result=run(configured,lambda *a:pytest.fail('replayed incomplete claim'))
    assert result['status']=='uncertain'


def test_cached_uncertain_cleanup_stops_other_due_checks(configured):
    p,c=configured
    def backend(*args):value=report();value['cleanup'][0]['removed']=False;return value
    run(configured,backend)
    second=dict(c['entries'][0],test_id='second');c['entries'].append(second);p.write_text(json.dumps(c))
    result=run(configured,lambda *a:pytest.fail('started another check after uncertain cleanup'))
    assert result['status']=='blocked' and len(result['results'])==1
