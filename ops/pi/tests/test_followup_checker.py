"""The actual adapter delegates to the authenticated fixed checker and cleans up."""
from pathlib import Path
import json
import pytest
from ops.pi.tests.test_followup import configured,report,api,run,NOW


def test_adapter_uses_fixed_checker_not_host_import_and_verifies_staged_copy(configured,monkeypatch,tmp_path):
    m=api();e=configured[1]['entries'][0];root=tmp_path/'checker';root.mkdir(mode=0o700);calls=[]
    import ops.pi.development_launcher as development
    class Owners:
        failed=False
        def __init__(self,cancel,write):self.hosts=[]
        def finish(self):calls.append('cleanup');return report()['cleanup']
    def fixed(c,candidate,destination,limits,write,owners):
        import shutil
        calls.append((c,candidate,limits.maximum))
        destination.mkdir();shutil.copytree(candidate/'src',destination/'src');shutil.copyfile(c['test_path'],destination/'test.py')
        return report()
    monkeypatch.setattr(development,'OwnedHosts',Owners);monkeypatch.setattr(development,'_fixed_check',fixed)
    result=m._isolated_check(e,root,lambda *args:None)
    assert result['passed'] and calls[-1]=='cleanup'
    assert calls[0][0]['test_sha256']==e['test_sha256'] and calls[0][0]['test_cases']==e['test_cases']
    assert calls[0][1]==Path(e['candidate_path']) and calls[0][2]==dict(model=1,tool=1)


def test_actual_adapter_always_sweeps_owned_hosts_on_error(configured,monkeypatch,tmp_path):
    import ops.pi.development_launcher as development
    calls=[]
    class Owners:
        failed=False
        def __init__(self,*args):pass
        def finish(self):calls.append('cleanup');return []
    monkeypatch.setattr(development,'OwnedHosts',Owners)
    monkeypatch.setattr(development,'_fixed_check',lambda *a:(_ for _ in ()).throw(RuntimeError('checker failed')))
    root=tmp_path/'checker';root.mkdir()
    with pytest.raises(RuntimeError):api()._isolated_check(configured[1]['entries'][0],root,lambda *a:None)
    assert calls==['cleanup']


def test_only_one_new_check_per_bounded_tick(configured):
    p,c=configured;second=dict(c['entries'][0],test_id='second');c['entries'].append(second)
    from ops.pi.audit import AuditStore
    store=AuditStore(c['audit_path']);old=store.events()[0]
    record={k:old[k] for k in ('kind','status','run_id','occurred_at','summary','details','version','changes','evidence','followups','mode','evidence_domain')}
    record['followups']=[dict(record['followups'][0],test_id='second')];store.append('second-plan',record)
    p.write_text(json.dumps(c));calls=[]
    result=run(configured,lambda *a:calls.append(1) or report())
    assert len(calls)==1 and len(result['results'])==1
