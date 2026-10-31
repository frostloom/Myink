"""Late owned rm acknowledgement, no provider/candidate execution."""
import subprocess
import pytest
from ops.pi.tests.test_container_probe import host,create,CID


def late(host,monkeypatch,*,gone=True):
    value,daemon,*_=host;cid=create(host);original=daemon.run;calls=[]
    def run(args,**kw):
        command=args[3:];calls.append(command)
        if command[0]=='rm':
            if gone:daemon.objects.pop(cid,None)
            raise subprocess.TimeoutExpired(args,kw['timeout'])
        if command==['inspect',cid] and cid not in daemon.objects:
            return subprocess.CompletedProcess(args,1,'[]\n','Error: No such object: '+cid+'\n')
        return original(args,**kw)
    monkeypatch.setattr(subprocess,'run',run)
    return value,daemon,cid,calls,run


def test_rm_timeout_with_confirmed_absence_uses_stopped_evidence_without_second_rm(host,monkeypatch):
    value,daemon,cid,calls,_=late(host,monkeypatch)
    result=value.cleanup(cid)
    assert result['removed'] and result['stopped'] and result['exit_code']==137
    assert result['removal_reconciled'] and not value.owned
    assert sum(c[0]=='rm' for c in calls)==1


def test_later_final_sweep_reconciles_owned_absence_but_keeps_original_failure(host,monkeypatch):
    from threading import Event
    from ops.pi.development_launcher import OwnedHosts
    value,daemon,cid,calls,_=late(host,monkeypatch,gone=False)
    cancel=Event();owners=OwnedHosts(cancel,lambda *a:None);owners.add(value)
    with pytest.raises(subprocess.TimeoutExpired):owners.cleanup(value)
    assert owners.failed and cancel.is_set()
    assert not value.removals[cid].get('removed'), 'pending intent is not a removal receipt'
    daemon.objects.pop(cid)
    result=owners.finish()
    assert len(result)==1 and result[0]['container_id']==cid and result[0]['removed']
    assert owners.failed and cancel.is_set() and sum(c[0]=='rm' for c in calls)==1


@pytest.mark.parametrize('bad',['transport','daemon','label','missing_stop','wrong_cid','wrong_output','untracked_label','ownership'])
def test_ambiguous_absence_never_becomes_a_removal_receipt(host,monkeypatch,bad):
    value,daemon,cid,calls,run=late(host,monkeypatch,gone=False)
    with pytest.raises(subprocess.TimeoutExpired):value.cleanup(cid)
    if bad=='ownership':daemon.objects[cid]['Config']['Labels']['myink.pi.operation']='foreign'
    else:daemon.objects.pop(cid)
    def changed(args,**kw):
        command=args[3:]
        if bad=='transport' and command==['inspect',cid]:return subprocess.CompletedProcess(args,1,'','permission denied')
        if bad=='wrong_cid' and command==['inspect',cid]:return subprocess.CompletedProcess(args,1,'[]','No such object: '+('c'*64))
        if bad=='wrong_output' and command==['inspect',cid]:return subprocess.CompletedProcess(args,1,'{}','No such object: '+cid)
        if bad=='untracked_label' and command[0]=='ps':return subprocess.CompletedProcess(args,0,'foreign-id\n','')
        if bad=='label' and command[0]=='ps':return subprocess.CompletedProcess(args,0,cid+'\n','')
        return run(args,**kw)
    monkeypatch.setattr(subprocess,'run',changed)
    if bad=='daemon':daemon.daemon_id='changed-daemon'
    if bad=='missing_stop':
        assert hasattr(value,'removals'), 'recorded removal intent missing'
        value.removals.clear()
    with pytest.raises((RuntimeError,ValueError)):value.cleanup(cid)
    assert cid in value.owned and sum(c[0]=='rm' for c in calls)==1


def test_disappeared_owned_container_without_removal_intent_is_not_reconciled(host,monkeypatch):
    value,daemon,cid,calls,_=late(host,monkeypatch,gone=False);daemon.objects.pop(cid)
    with pytest.raises(RuntimeError):value.cleanup(cid)
    assert cid in value.owned and not any(c[0]=='rm' for c in calls)

from ops.pi.tests.test_development_inputs import config_file


def test_partial_cleanup_history_survives_failed_final_sweep(config_file,monkeypatch):
    from ops.pi import development_launcher as launcher
    cp,c=config_file
    class Host:
        operation_id='synthetic-owner'
    class Owners(launcher.OwnedHosts):
        def finish(self):
            self.history.append(dict(container_id='known-removed',removed=True,stopped=True,exit_code=0))
            raise RuntimeError('one other owner unresolved')
    monkeypatch.setattr(launcher,'OwnedHosts',Owners)
    monkeypatch.setattr(launcher,'_host',lambda *a:Host())
    def fail(*a):raise RuntimeError('synthetic stopped phase')
    monkeypatch.setattr(launcher,'_exchange',fail)
    result=launcher.execute(cp,transport=lambda *a:None)
    assert result['cleanup']==[dict(container_id='known-removed',removed=True,stopped=True,exit_code=0)]
    assert result['cleanup_failure_class']=='RuntimeError' and not result['verified']
    assert result['policy_restored'] and result['new_attempts']==0


def test_unverified_stopped_exit_never_enters_removal_intent(host):
    value,daemon,*_=host;cid=create(host)
    daemon.objects[cid]['State'].update(Running=False,Pid=0,ExitCode=True)
    with pytest.raises(RuntimeError,match='exit code'):value.cleanup(cid)
    assert not value.removals and not any(c[0]=='rm' for c in daemon.commands)

@pytest.mark.parametrize('failure',['later_cid','final_label'])
def test_each_removed_cid_is_preserved_before_later_cleanup_checks_raise(failure):
    from threading import Event
    from types import SimpleNamespace
    from ops.pi.development_launcher import OwnedHosts
    class Host:
        operation_id='synthetic-owner';pending={}
        def __init__(self):self.owned={'first':None,**({'second':None} if failure=='later_cid' else {})};self.fail=True
        def reconcile(self):pass
        def _daemon(self):pass
        def _call(self,*a):return SimpleNamespace(stdout='unexpected' if self.fail and failure=='final_label' else '')
        def cleanup(self,cid):
            if self.fail and cid=='second':raise RuntimeError('later CID unresolved')
            del self.owned[cid]
            return dict(container_id=cid,removed=True,stopped=True,exit_code=0)
    host=Host();cancel=Event();owners=OwnedHosts(cancel,lambda *a:None);owners.add(host)
    with pytest.raises((RuntimeError,ValueError)):owners.cleanup(host)
    assert owners.failed and cancel.is_set() and 'first' not in host.owned
    assert owners.history==[dict(container_id='first',removed=True,stopped=True,exit_code=0)]
    host.fail=False
    history=owners.finish()
    assert len(history)==(2 if failure=='later_cid' else 1)
    assert len({r['container_id'] for r in history})==len(history)
    assert owners.failed and cancel.is_set()
