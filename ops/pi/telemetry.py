"""Public probe summary with strict maintenance exemptions and no private payloads."""
from datetime import datetime, timedelta, timezone
from .contracts import Record


def public_status(observations: Record, now: datetime) -> Record:
    if now.tzinfo is None:
        raise ValueError('aware clock required')
    local = now.astimezone(timezone(timedelta(hours=8)))
    maintenance = observations.get('maintenance') is True and 2 <= local.hour < 6
    heartbeat = observations.get('heartbeat')
    fresh = (isinstance(heartbeat, datetime) and heartbeat.tzinfo is not None
             and 0 <= (now - heartbeat).total_seconds() <= 90)
    incidents = [name for name in ('postgres', 'backup') if observations.get(name) is not True]
    if not fresh:
        incidents.append('heartbeat')
    if maintenance:
        if observations.get('maintenance_page') is not True:
            incidents.append('maintenance_page')
    elif observations.get('business_probe') is not True:
        incidents.append('business_probe')
    if observations.get('worker') is not True and not (maintenance and observations.get('expected_worker_stop') is True):
        incidents.append('worker')
    return dict(status='incident' if incidents else 'maintenance' if maintenance else 'healthy',
                maintenance=maintenance, incidents=incidents, observed_at=now.isoformat())
