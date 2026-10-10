from datetime import datetime, timedelta, timezone
from importlib.util import find_spec


def public_status(*args):
    assert find_spec('ops.pi.telemetry') is not None, 'public status capability must exist'
    from ops.pi.telemetry import public_status as status
    return status(*args)

NOW = datetime(2026, 10, 11, 19, tzinfo=timezone.utc)  # 03:00 Shanghai


def observations(**changes):
    data = dict(maintenance=True, expected_worker_stop=True, heartbeat=NOW,
                maintenance_page=True, postgres=True, backup=True, business_probe=False, worker=False)
    data.update(changes)
    return data


def test_maintenance_page_up_pg_down_is_incident():
    assert public_status(observations(postgres=False), NOW)['status'] == 'incident'


def test_stale_heartbeat_is_incident():
    assert public_status(observations(heartbeat=NOW - timedelta(seconds=91)), NOW)['status'] == 'incident'


def test_expected_worker_stop_is_not_incident():
    assert public_status(observations(), NOW)['status'] == 'maintenance'


def test_backup_and_after_six_probe_never_exempted():
    assert public_status(observations(backup=False), NOW)['status'] == 'incident'
    after = NOW + timedelta(hours=3)
    assert public_status(observations(heartbeat=after), after)['status'] == 'incident'


def test_public_status_allowlist_omits_private_fields():
    result = public_status(observations(environment={'secret': 'x'}, prompt='body'), NOW)
    assert 'environment' not in result and 'prompt' not in result
    assert public_status({}, NOW)['status'] == 'incident'
