"""Offline summaries project safe fields; raw evidence never enters reports."""
import math
from .contracts import Record

PENDING_ACCEPTANCE = [
    'A4 live database SELECT reader, actual timeout and collector SQL: pending until B7',
    'tests/test_run_provenance, admin_observability and run_ownership: pending until B7',
    'C16 raw usage presence: pending',
    'Cloud/production readiness and online evidence: not accepted',
]


def _text(value):
    return str(value if value is not None else 'unknown').replace('\n', ' ').replace('\r', ' ').replace('|', '\uFF5C')[:200]


def render_report(events: list[Record], snapshots: list[Record]) -> str:
    lines = ['# Pi daily development report', '', 'Evidence domain: offline; not cloud ready.', '', '## Immutable event history']
    released = False
    for event in events:
        payload = event.get('payload') or {}
        kind = event.get('kind', 'unknown')
        status = payload.get('status', 'unknown')
        operation = payload.get('operation_id', 'unknown')
        lines.append(f'- {_text(kind)} / {_text(operation)} / {_text(status)}')
        if kind == 'receipt' and status == 'done' and (payload.get('evidence') or {}).get('released') is True:
            released = True
    if not released:
        lines += ['', 'No release', 'Reason: no verified release receipt in this ledger.', 'Next action: review blockers and gather the pending acceptance evidence.']
    lines += ['', '## Snapshot index']
    for snapshot in snapshots:
        measurements = snapshot.get('measurements') or {}
        cost = measurements.get('cost', {})
        value = (cost.get('value') if cost.get('availability') == 'measured' else None) if 'cost' in measurements else snapshot.get('cost_cny')
        known = type(value) in (int, float) and math.isfinite(value) and value >= 0
        lines.append(f"- {_text(snapshot.get('id'))}: cost={str(value) + ' CNY' if known else 'unknown'}; config={_text(snapshot.get('config_hash'))}; pricing={_text(snapshot.get('pricing_id'))}")
    if not snapshots:
        lines.append('- Cost: unknown; no measured snapshots.')
    lines += ['', '## Pending acceptance'] + ['- ' + item for item in PENDING_ACCEPTANCE]
    return '\n'.join(lines) + '\n'
