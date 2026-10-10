import importlib.util
from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger


def send(ledger, report, transport):
    if importlib.util.find_spec('ops.pi.notify') is None:
        return Receipt('missing', 'blocked', {})
    from ops.pi.notify import send_daily
    return send_daily(ledger, report, transport)


def report(**changes):
    return dict(date='2026-10-11', run_id='run-1', content_version='v1', recipient='capture', **changes)


def test_missing_recipient_queues_report(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    item = report(); item.pop('recipient')
    calls = []
    receipt = send(ledger, item, lambda envelope: calls.append(envelope))
    assert receipt.status == 'pending' and receipt.evidence['attempts'] == 0
    assert calls == [] and ledger.get(receipt.operation_id)['status'] == 'pending'


def test_development_report_is_not_incident(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    calls = []
    receipt = send(ledger, report(), lambda envelope: calls.append(envelope) or {'status': 'captured'})
    assert receipt.evidence['kind'] == 'daily_report'
    assert receipt.evidence['delivery_status'] == 'captured'
    assert calls[0]['kind'] == 'daily_report'


def test_uncertain_send_not_automatically_duplicated(tmp_path):
    path = tmp_path / 'ledger.sqlite'; calls = []
    def transport(envelope):
        calls.append(envelope)
        raise TimeoutError('receipt lost')
    first = send(Ledger(path), report(), transport)
    second = send(Ledger(path), report(), transport)
    assert first.status == second.status == 'uncertain'
    assert len(calls) == 1 and second.evidence['unknown'] is True


def test_notification_identity_survives_restart_and_versions(tmp_path):
    path = tmp_path / 'ledger.sqlite'; calls = []
    def capture(envelope):
        calls.append(envelope); return {'status': 'captured'}
    first = send(Ledger(path), report(), capture)
    assert send(Ledger(path), report(), capture) == first
    changed = report(); changed['content_version'] = 'v2'
    second = send(Ledger(path), changed, capture)
    assert first.operation_id != second.operation_id and len(calls) == 2
    assert first.evidence['message_id'] != second.evidence['message_id']


def test_pending_without_transport_can_be_captured_later(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    pending = send(ledger, report(), None)
    assert pending.status == 'pending'
    captured = send(ledger, report(), lambda envelope: {'status': 'captured'})
    assert captured.status == 'done' and captured.evidence['delivery_status'] == 'captured'


def test_notification_does_not_persist_body_or_credentials(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    item = report(body='RAW_SECRET', api_key='KEY_SECRET')
    receipt = send(ledger, item, lambda envelope: {'status': 'captured'})
    assert receipt.status == 'done'
    stored = str(ledger.get(receipt.operation_id))
    assert 'RAW_SECRET' not in stored and 'KEY_SECRET' not in stored


def test_retry_receipt_loss_remains_uncertain(tmp_path):
    calls = []
    def transport(envelope):
        calls.append(envelope)
        if len(calls) == 1:
            return {'status': 'not_sent'}
        raise TimeoutError('receipt lost on retry')
    receipt = send(Ledger(tmp_path / 'ledger.sqlite'), report(), transport)
    assert receipt.status == 'uncertain' and receipt.evidence['unknown'] is True
    assert receipt.evidence['attempts'] == 2


def test_proven_non_send_retries_are_bounded(tmp_path):
    calls = []
    receipt = send(Ledger(tmp_path / 'ledger.sqlite'), report(), lambda envelope: calls.append(envelope) or {'status': 'not_sent'})
    assert receipt.status == 'failed' and receipt.evidence['attempts'] == 3
    assert len(calls) == 3


def test_crash_after_durable_claim_never_resends(tmp_path):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    pending = send(ledger, report(), None)
    ledger.append_event('notification_attempt', {'operation_id': pending.operation_id, 'attempts': 1})
    calls = []
    receipt = send(ledger, report(), lambda envelope: calls.append(envelope))
    assert receipt.status == 'uncertain' and calls == []


def test_pending_notification_metadata_is_durable(tmp_path):
    path = tmp_path / 'ledger.sqlite'
    pending = send(Ledger(path), report(), None)
    stored = Ledger(path).get(pending.operation_id)['payload']
    assert stored.get('message_id') == pending.evidence['message_id']
    assert stored['attempts'] == 0 and stored['unknown'] is False
