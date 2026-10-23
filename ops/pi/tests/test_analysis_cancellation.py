from threading import Event, Thread
import time

from ops.pi.tests.test_budget import ledger, policy, request
from ops.pi.tests.test_model_gateway import success, transport
from ops.pi.model_gateway import forward_messages


def test_cancelled_before_reserve_does_not_send(ledger, policy):
    cancel=Event();cancel.set();calls=[]
    result=forward_messages(request(), 'local-trial-1', ledger=ledger, policy=policy,
        transport=lambda *a: calls.append(a), cancel=cancel)
    assert result.status_code==403 and not calls
    with ledger.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM operations WHERE kind='model-attempt'").fetchone()[0]==0


def test_cancel_after_reservation_preserves_uncertainty_without_send(ledger, policy, monkeypatch):
    from ops.pi import model_gateway as m
    cancel=Event();calls=[];reserve=m.reserve
    def reserved(*args,**kwargs):
        permit=reserve(*args,**kwargs);cancel.set();return permit
    monkeypatch.setattr(m,'reserve',reserved)
    result=m.forward_messages(request(), 'local-trial-1', ledger=ledger, policy=policy,
        transport=lambda *a: calls.append(a), cancel=cancel)
    assert result.status_code==502 and not calls
    assert ledger.get(result.attempt_id)['status']=='uncertain'


def test_cancel_during_transport_returns_before_transport_and_stays_unknown(ledger, policy):
    cancel=Event();entered=Event();release=Event();finished=Event();results=[]
    send=transport(success)
    def blocked(body,timeout):
        entered.set();release.wait(4);return send(body,timeout)
    def call():
        try: results.append(forward_messages(request(),'local-trial-1',ledger=ledger,
            policy=policy,transport=blocked,cancel=cancel))
        finally: finished.set()
    t=Thread(target=call,daemon=True);t.start()
    try:
        assert entered.wait(2);cancel.set()
        assert finished.wait(1) and not release.is_set()
        assert results[0].status_code==502
        assert ledger.get(results[0].attempt_id)['status']=='uncertain'
    finally:
        release.set();t.join(2)


def test_cancel_after_known_settlement_cannot_overwrite_it(ledger, policy):
    cancel=Event()
    result=forward_messages(request(),'local-trial-1',ledger=ledger,policy=policy,
        transport=transport(success),cancel=cancel)
    list(result.body) if not isinstance(result.body,bytes) else None
    assert ledger.get(result.attempt_id)['status']=='done'
    cancel.set()
    assert ledger.get(result.attempt_id)['evidence']['usage_known'] is True
