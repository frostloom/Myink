"""Guest writing allowances are lifetime, shared IP ledgers, not book counts."""
import importlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import delete
from myink.db import new_session
from myink.models import User, GuestIdentity
from myink.guests import ip_key


@pytest.fixture
def guest_account():
    ip = '2001:db8:' + uuid.uuid4().hex[:4] + ':' + uuid.uuid4().hex[:4] + '::1'
    with new_session() as db:
        user = User(username='quota-' + uuid.uuid4().hex, is_guest=True)
        db.add(user)
        db.flush()
        db.add(GuestIdentity(user_id=user.id, original_ip_key=ip_key(ip), recovery_digest=uuid.uuid4().hex))
        db.commit()
        uid = str(user.id)
    yield uid, ip
    with new_session() as db:
        db.execute(delete(User).where(User.id == uuid.UUID(uid)))
        db.commit()


def ledger():
    import myink
    assert importlib.util.find_spec('myink.guest_quota'), 'durable guest quota module must exist'
    return importlib.import_module('myink.guest_quota')


def reserve(q, uid, ip, dimension='long', amount=1, operation_id=None):
    return q.reserve(user_id=uid, client_ip=ip, dimension=dimension, amount=amount,
                     operation_id=operation_id or str(uuid.uuid4()), task_id=str(uuid.uuid4()))


def test_exact_limits_independent_dimensions_and_atomic_batch(guest_account):
    q = ledger()
    uid, ip = guest_account
    reserve(q, uid, ip, 'short', 2)
    reserve(q, uid, ip, 'long', 8)
    with pytest.raises(q.GuestQuotaError, match='GUEST_QUOTA_EXHAUSTED'):
        reserve(q, uid, ip, 'long', 3)
    assert q.quota_view(uid, ip) == {'short': {'limit':2,'used':2,'remaining':0},
                                   'long': {'limit':10,'used':8,'remaining':2}}
    reserve(q, uid, ip, 'long', 2)
    with pytest.raises(q.GuestQuotaError):
        reserve(q, uid, ip, 'short')
    with pytest.raises(q.GuestQuotaError):
        reserve(q, uid, ip)


def test_concurrent_last_unit_is_atomic(guest_account):
    q = ledger()
    uid, ip = guest_account
    reserve(q, uid, ip, amount=9)
    barrier = Barrier(2)
    def attempt():
        barrier.wait()
        try:
            reserve(q, uid, ip)
            return 'accepted'
        except q.GuestQuotaError:
            return 'exhausted'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == ['accepted','exhausted']
    assert q.quota_view(uid, ip)['long']['used'] == 10


def test_idempotency_release_and_reacquire(guest_account):
    q = ledger()
    uid, ip = guest_account
    params = dict(user_id=uid, client_ip=ip, dimension='long', amount=2,
                  operation_id=str(uuid.uuid4()), task_id=str(uuid.uuid4()))
    receipt = q.reserve(**params)
    assert q.reserve(**params) == receipt
    assert q.quota_view(uid, ip)['long']['used'] == 2
    q.release(receipt)
    q.release(receipt)
    assert q.quota_view(uid, ip)['long']['used'] == 0
    q.reserve(**params)
    assert q.quota_view(uid, ip)['long']['used'] == 2
    with pytest.raises(q.GuestQuotaError, match='CONFLICT'):
        q.reserve(**{**params,'amount':1})


def test_original_current_normalized_shared_and_survives_identity_deletion(guest_account):
    q = ledger()
    uid, ip = guest_account
    other_ip = '2001:db8:' + uuid.uuid4().hex[:4] + '::2'
    reserve(q, uid, ip, amount=2)
    reserve(q, uid, other_ip, amount=3)
    importlib.reload(q)
    assert q.quota_view(uid, other_ip)['long']['used'] == 5
    with new_session() as db:
        other = User(username='quota-' + uuid.uuid4().hex, is_guest=True)
        db.add(other)
        db.flush()
        db.add(GuestIdentity(user_id=other.id, original_ip_key=ip_key(other_ip), recovery_digest=uuid.uuid4().hex))
        db.execute(delete(User).where(User.id == uuid.UUID(uid)))
        db.commit()
        other_uid = str(other.id)
    try:
        assert q.quota_view(other_uid, other_ip)['long']['used'] == 3
        import ipaddress
        reserve(q, other_uid, ipaddress.ip_address(other_ip).exploded)
        assert q.quota_view(other_uid, other_ip)['long']['used'] == 4
    finally:
        with new_session() as db:
            db.execute(delete(User).where(User.id == uuid.UUID(other_uid)))
            db.commit()


def test_invalid_ip_never_creates_unknown_bucket(guest_account):
    q = ledger()
    uid, ip = guest_account
    with pytest.raises(q.GuestQuotaError, match='GUEST_IP_UNAVAILABLE'):
        reserve(q, uid, 'unknown')
    assert q.quota_view(uid, ip)['long']['used'] == 0


def test_schema_upgrade_is_idempotent_and_preserves_used_allowance(guest_account):
    from myink.db import ensure_guest_quota
    q=ledger()
    uid,ip=guest_account
    reserve(q,uid,ip,amount=4)
    ensure_guest_quota()
    ensure_guest_quota()
    assert q.quota_view(uid,ip)['long']['used']==4
