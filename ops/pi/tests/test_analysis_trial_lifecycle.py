import json
from pathlib import Path
import signal
import time

import pytest

from ops.pi.tests import test_analysis_launcher as pilot
from ops.pi.tests.test_analysis_launcher import setup
from ops.pi.tests.test_analysis_full_trial import install
from ops.pi.analysis_execution import _hash
from ops.pi.ledger import LedgerBlocked


def config_v2(c, seconds=300):
    c=c|dict(schema='pi-analysis-trial-v2',failure_policy='continue_known_contract_failure',
        time_policy='bounded_trial_v1',deadline=time.time()+seconds)
    path=Path(c['evidence_path']);e=json.loads(path.read_text());e['valid_until']=time.time()+4000
    path.write_text(json.dumps(e));c['expected_evidence_sha256']=_hash(e)
    return c


def test_v2_long_check_is_read_only_and_reports_lifecycle(setup, monkeypatch):
    c,ledger,*_=setup;c=config_v2(c,3500);before=ledger.path.read_bytes()
    def forbidden(*a,**kw):pytest.fail('check must be read-only')
    monkeypatch.setattr(pilot.api(),'_provider',forbidden)
    monkeypatch.setattr(signal,'signal',forbidden)
    r=pilot.api().launch(c)
    assert r['selected_slots']==30 and r['time_policy']=='bounded_trial_v1'
    assert r['stop_reason'] is None and r['cleanup_complete'] is None
    assert before==ledger.path.read_bytes() and not Path(c['root']).exists()


@pytest.mark.parametrize('change',[{'deadline':time.time()+3700},{'deadline':True},
    {'time_policy':'anything'},{'selected_slots':1}])
def test_v2_rejects_invalid_timing_config(setup,change):
    c,*_=setup
    with pytest.raises(LedgerBlocked):pilot.api().launch(config_v2(c)|change)


def test_v2_short_window_does_not_claim_or_create_container(setup,monkeypatch):
    c,*_=setup;processes,calls,daemon=install(monkeypatch)
    r=pilot.api().launch(config_v2(c,119),execute=True)
    assert r['status']=='blocked' and r['stop_reason']=='insufficient_slot_window'
    assert [x['status'] for x in r['slots']]==['NOT_RUN']*30
    assert not processes and not calls and not daemon.objects
    assert r['cleanup_complete'] is True
    assert (Path(c['root'])/'lifecycle-private.json').is_file()


def test_v2_full_thirty_preserves_known_contract_failure(setup,monkeypatch):
    c,*_=setup;processes,calls,daemon=install(monkeypatch,{'0':'json'})
    r=pilot.api().launch(config_v2(c),execute=True)
    assert r['status']=='completed' and r['stop_reason'] is None
    assert r['cleanup_complete'] is True and r['summary']['failed']==1
    assert [x['status'] for x in r['slots']]==['FAILED']+['DONE']*29
    assert len(calls)==30 and not daemon.objects and all(p.poll() is not None for p in processes)


@pytest.mark.parametrize('exc',[KeyboardInterrupt,SystemExit])
def test_library_interrupt_records_snapshot_and_reraises_systemexit(setup,monkeypatch,exc):
    c,*_=setup;install(monkeypatch);m=pilot.api()
    def interrupt(*a,**kw):raise exc()
    monkeypatch.setattr(m,'_slot',interrupt)
    c=config_v2(c)
    if exc is SystemExit:
        with pytest.raises(SystemExit):m.launch(c,execute=True)
        r=json.loads((Path(c['root'])/'receipt.json').read_text())
    else:r=m.launch(c,execute=True)
    assert r['status']=='blocked' and r['stop_reason']=='interrupted'
    assert [x['status'] for x in r['slots']]==['NOT_RUN']*30


def test_stop_during_cleanup_keeps_known_bill_but_uncertain_slot(setup,monkeypatch):
    c,ledger,*_=setup;_,calls,daemon=install(monkeypatch);m=pilot.api()
    original=m.ProbeHost.cleanup
    def cleanup(host,cid):
        value=original(host,cid)
        host.lifecycle.stop('interrupted')
        return value
    monkeypatch.setattr(m.ProbeHost,'cleanup',cleanup)
    r=m.launch(config_v2(c),execute=True)
    assert r['status']=='blocked' and r['stop_reason']=='interrupted'
    assert [x['status'] for x in r['slots']]==['UNCERTAIN']+['NOT_RUN']*29
    with ledger.transaction() as db:
        rows=db.execute("SELECT status FROM operations WHERE kind='model-attempt'").fetchall()
        assert len(rows)==1 and rows[0]['status']=='done'
    assert len(calls)==1 and not daemon.objects


def test_unknown_billing_stops_but_terminal_unknown_is_clean(setup,monkeypatch):
    c,*_=setup;_,calls,daemon=install(monkeypatch,mode='unknown')
    r=pilot.api().launch(config_v2(c),execute=True)
    assert r['status']=='blocked' and r['stop_reason']=='execution_failed'
    assert r['cleanup_complete'] is True and len(calls)==1 and not daemon.objects


def test_v2_completes_after_old_six_hundred_second_window(setup,monkeypatch):
    c,*_=setup;_,calls,daemon=install(monkeypatch);m=pilot.api();c=config_v2(c,1800)
    original=m.ProbeHost.cleanup;wall=m.time.time;offset=[0]
    def cleanup(host,cid):
        value=original(host,cid)
        if not offset[0]:offset[0]=700
        return value
    monkeypatch.setattr(m.time,'time',lambda:wall()+offset[0])
    monkeypatch.setattr(m.ProbeHost,'cleanup',cleanup)
    r=m.launch(c,execute=True)
    assert r['status']=='completed' and len(calls)==30 and not daemon.objects


def test_insufficient_window_after_done_preserves_done_and_unrun(setup,monkeypatch):
    c,*_=setup;_,calls,daemon=install(monkeypatch);m=pilot.api()
    original=m.ProbeHost.cleanup
    def cleanup(host,cid):
        value=original(host,cid);host.lifecycle._end=time.monotonic()+119
        return value
    monkeypatch.setattr(m.ProbeHost,'cleanup',cleanup)
    r=m.launch(config_v2(c),execute=True)
    assert r['stop_reason']=='insufficient_slot_window'
    assert [x['status'] for x in r['slots']]==['DONE']+['NOT_RUN']*29
    assert len(calls)==1 and not daemon.objects


def test_cleanup_failure_keeps_container_identity(setup,monkeypatch):
    c,*_=setup;_,calls,daemon=install(monkeypatch,mode='cleanup-failure')
    r=pilot.api().launch(config_v2(c),execute=True)
    assert r['status']=='blocked' and r['cleanup_complete'] is False
    assert r['stop_reason']=='cleanup_failed'
    assert any(not x['removed'] and x.get('container_id') for x in r['cleanup'])
    assert len(calls)==1 and daemon.objects


def test_v2_final_receipt_failure_never_reports_success(setup,monkeypatch):
    from ops.pi import analysis_trial_lifecycle as lifecycle
    c,*_=setup;install(monkeypatch);write=lifecycle._write
    def fail_receipt(path,value):
        if path.name=='receipt.json':raise OSError('synthetic final storage failure')
        return write(path,value)
    monkeypatch.setattr(lifecycle,'_write',fail_receipt)
    with pytest.raises(LedgerBlocked):pilot.api().launch(config_v2(c,119),execute=True)


def test_cli_installs_and_restores_signal_handlers_on_interrupt(setup,monkeypatch):
    c,*_=setup;_,calls,daemon=install(monkeypatch);m=pilot.api();original=m._slot
    before={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
    def interrupt(*args,**kwargs):
        handler=signal.getsignal(signal.SIGTERM)
        assert handler is not before[signal.SIGTERM]
        handler(signal.SIGTERM,None)
        kwargs['lifecycle'].check()
        return original(*args,**kwargs)
    monkeypatch.setattr(m,'_slot',interrupt)
    r=m.launch(config_v2(c),execute=True,_signals=True)
    assert r['stop_reason']=='interrupted' and not calls and not daemon.objects
    assert all(signal.getsignal(s)==h for s,h in before.items())


def test_bounded_docker_waits_share_cleanup_budget(monkeypatch):
    from ops.pi import analysis_lifecycle as clocks
    from ops.pi.analysis_lifecycle import Lifecycle
    from ops.pi.analysis_trial_lifecycle import _bound_host
    clock=[100.,10.];timeouts=[]
    monkeypatch.setattr(clocks.time,'time',lambda:clock[0])
    monkeypatch.setattr(clocks.time,'monotonic',lambda:clock[1])
    class Host:
        def _call(self,*args,**kwargs):timeouts.append(kwargs['timeout'])
    host=Host();life=Lifecycle(400);_bound_host(host,life)
    life.begin_cleanup();host._call('inspect')
    clock[:]=[218.,128.];host._call('inspect')
    clock[:]=[221.,131.]
    with pytest.raises(TimeoutError):host._call('rm')
    assert timeouts==[15,2]


@pytest.mark.parametrize('exc',[KeyboardInterrupt,SystemExit])
def test_interrupt_during_final_cleanup_still_attempts_receipt(setup,monkeypatch,exc):
    c,*_=setup;install(monkeypatch);m=pilot.api();c=config_v2(c,119)
    def interrupted(*a,**kw):raise exc()
    monkeypatch.setattr(m.ProbeHost,'reconcile',interrupted)
    if exc is SystemExit:
        with pytest.raises(SystemExit):m.launch(c,execute=True)
        r=json.loads((Path(c['root'])/'receipt.json').read_text())
    else:
        try:r=m.launch(c,execute=True)
        except KeyboardInterrupt:pytest.fail('cleanup interrupt escaped without receipt')
    assert r['status']=='blocked' and r['stop_reason']=='insufficient_slot_window'
    assert r['cleanup_complete'] is False
    assert (Path(c['root'])/'receipt.json').is_file()


@pytest.mark.parametrize('stop',['interrupted','deadline_exceeded'])
def test_stop_while_waiting_to_finish_does_not_commit_done(setup,monkeypatch,stop):
    from ops.pi.analysis_run import AnalysisRun
    c,*_=setup;_,calls,_=install(monkeypatch);m=pilot.api();slot=m._slot;finish=AnalysisRun.finish;state={}
    def capture(*a,**kw):
        state['life']=kw['lifecycle'];return slot(*a,**kw)
    def delayed_finish(run,index,**kw):
        if stop=='interrupted':state['life'].stop(stop)
        else:state['life']._end=time.monotonic()-1
        return finish(run,index,**kw)
    monkeypatch.setattr(m,'_slot',capture);monkeypatch.setattr(AnalysisRun,'finish',delayed_finish)
    r=m.launch(config_v2(c),execute=True)
    assert r['stop_reason']==stop and len(calls)==1
    assert [x['status'] for x in r['slots']]==['UNCERTAIN']+['NOT_RUN']*29


def test_lifecycle_and_prepare_use_same_frozen_config(setup,monkeypatch):
    c,*_=setup;c=config_v2(c);m=pilot.api();prepare=m._prepare
    def check_copy(value):
        assert value is not c,'caller configuration must freeze before lifecycle capture'
        return prepare(value)
    monkeypatch.setattr(m,'_prepare',check_copy)
    assert m.launch(c)['status']=='checked'
