"""Host-only captured daily notifications, with durable conservative receipts."""
from datetime import date
import hashlib
import json
from typing import Callable
from .contracts import Receipt, Record
from .ledger import Ledger, OperationConflict


def send_daily(ledger: Ledger, report: Record, transport: Callable | None) -> Receipt:
    identity = {key: report[key] for key in ('date', 'run_id', 'content_version')}
    if not all(isinstance(value, str) and value.strip() for value in identity.values()):
        raise ValueError('notification identity required')
    date.fromisoformat(identity['date'])
    identity['kind'] = 'daily_report'
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    operation_id = 'notification:' + digest
    message_id = '<' + digest + '@pi.capture.local>'
    record = ledger.intent(operation_id, 'daily_report', dict(**identity, message_id=message_id, attempts=0, unknown=False, delivery_status='pending'))
    if record['status'] != 'pending':
        return Receipt(operation_id, record['status'], record['evidence'])
    evidence = dict(**identity, message_id=message_id, attempts=0, unknown=False, delivery_status='pending')
    if transport is None or not isinstance(report.get('recipient'), str) or not report['recipient'].strip():
        return Receipt(operation_id, 'pending', evidence)
    # Claim before any external side effect. A crash after claim cannot prove non-send.
    with ledger.transaction() as connection:
        current = ledger._record(connection.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone())
        if current['status'] != 'pending':
            return Receipt(operation_id, current['status'], current['evidence'])
        previous = [json.loads(row[0]) for row in connection.execute("SELECT payload FROM events WHERE kind='notification_attempt'")]
        attempts = max((item.get('attempts', 1) for item in previous if item.get('operation_id') == operation_id), default=0)
        claimed = attempts > 0
        if not claimed:
            connection.execute("INSERT INTO events(kind,payload,schema_version) VALUES ('notification_attempt',?,1)", (json.dumps({'operation_id': operation_id, 'attempts': 1}),))
    status = 'uncertain'
    evidence.update(attempts=max(1, attempts), unknown=True, delivery_status='uncertain')
    if not claimed:
        envelope = dict(**identity, message_id=message_id, recipient=report['recipient'])
        for attempt in range(1, 4):
            if attempt > 1:
                ledger.append_event('notification_attempt', {'operation_id': operation_id, 'attempts': attempt})
            status = 'uncertain'
            evidence.update(attempts=attempt, unknown=True, delivery_status='uncertain')
            try:
                outcome = transport(envelope)
            except Exception:
                break  # Receipt loss, including SMTP success, never means safe retry.
            if isinstance(outcome, dict) and outcome.get('status') == 'captured':
                status = 'done'
                evidence.update(unknown=False, delivery_status='captured')
                break
            if not isinstance(outcome, dict) or outcome.get('status') != 'not_sent':
                break
            # Explicit proof of no send permits bounded retries; no receipt does not.
            status = 'failed'
            evidence.update(unknown=False, delivery_status='not_sent')
    receipt = Receipt(operation_id, status, evidence)
    try:
        ledger.finish(receipt)
    except OperationConflict:
        current = ledger.get(operation_id)
        return Receipt(operation_id, current['status'], current['evidence'])
    return receipt
