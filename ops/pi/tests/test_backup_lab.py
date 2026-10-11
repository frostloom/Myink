"""Finite handler lifecycle regression; SQLite/artifacts real, source boundary doubled."""
from types import SimpleNamespace
from ops.pi.tests.test_backup import case,artifacts


def test_fresh_creator_verification_then_first_pre_before_restore(case,monkeypatch):
    from ops.pi.lab import backup_lab as lab
    ledger,identity,pair,root=case;trace=[]
    monkeypatch.setattr(lab,'verify_test_environment',lambda:({},{}))
    monkeypatch.setattr(lab,'initialize_source',lambda:trace.append('initialize'))
    def historical():raise AssertionError('fresh current creator routed to historical failed/PRE observer')
    monkeypatch.setattr(lab,'observe_source',historical)
    monkeypatch.setattr(lab,'observe_created_source',lambda **kw:trace.append('current_creator_verified'),raising=False)
    monkeypatch.setattr(lab,'identities',lambda:(identity,None,pair))
    monkeypatch.setattr(lab,'COLLECTIONS',root)
    class Boundary:
        def __init__(self):self.ledger=ledger
        def __call__(self,action,context):return artifacts(action,context)
    monkeypatch.setattr(lab,'get_boundary',lambda **kw:Boundary())
    def restore_run(*args,**kwargs):
        assert ledger.get('backup:release-1:PRE')['status']=='done'
        trace.append('first_pre_then_restore');return SimpleNamespace(returncode=0)
    monkeypatch.setattr(lab.subprocess,'run',restore_run)
    lab.prepare('b11-source')
    assert trace==['initialize','current_creator_verified','first_pre_then_restore']


def test_corruption_probe_uses_matching_canonical_candidate(case,monkeypatch):
    from ops.pi.lab import backup_fresh as fresh
    from ops.pi.tests.test_backup import backup,CONTEXT,NOW
    ledger,identity,pair,_=case;backup(case)
    monkeypatch.setattr(fresh.lab,'identities',lambda:(None,identity,None))
    def mark(ledger,pair_id,candidate,**kwargs):
        assert candidate==pair['post_identity'],'probe rejected wrong candidate before testing collection corruption'
        raise ValueError('actual collection corruption blocks gate')
    monkeypatch.setattr(fresh,'mark_released',mark)
    assert fresh.assert_corrupt_pre_refuses_release(ledger,pair['release_pair_id'],CONTEXT,NOW)
