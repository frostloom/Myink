"""Exercise additive guest upgrades in a rollback-only legacy schema."""
from contextlib import nullcontext
from types import SimpleNamespace
import uuid

from sqlalchemy import text

import myink.db as database


def test_legacy_upgrade_preserves_accounts_and_usage_and_is_idempotent(monkeypatch):
    engine = database.get_admin_engine()
    schema = 'guest_upgrade_' + uuid.uuid4().hex
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            conn.execute(text('CREATE TABLE users (id UUID PRIMARY KEY, username VARCHAR(64) NOT NULL)'))
            uid = uuid.uuid4()
            conn.execute(text("INSERT INTO users VALUES (:id, 'existing-user')"), {'id': uid})
            monkeypatch.setattr(database, 'get_admin_engine', lambda: SimpleNamespace(begin=lambda: nullcontext(conn)))
            database.ensure_guest_identity()
            database.ensure_guest_quota()
            assert conn.scalar(text('SELECT is_guest FROM users WHERE id=:id'), {'id': uid}) is False

            conn.execute(text('UPDATE users SET is_guest=true WHERE id=:id'), {'id': uid})
            conn.execute(text('INSERT INTO guest_quota_buckets (ip_key, short_used, long_used) VALUES (:key, 1, 5)'),
                         {'key': 'a' * 64})
            database.ensure_guest_identity()
            database.ensure_guest_quota()
            assert conn.scalar(text('SELECT is_guest FROM users WHERE id=:id'), {'id': uid}) is True
            assert tuple(conn.execute(text('SELECT short_used, long_used FROM guest_quota_buckets')).one()) == (1, 5)
            expected = {'users', 'guest_identities', 'guest_quota_buckets',
                        'guest_quota_operations', 'guest_body_attempts'}
            actual = set(conn.scalars(text('SELECT table_name FROM information_schema.tables '
                                           'WHERE table_schema=current_schema()')))
            assert expected <= actual
        finally:
            transaction.rollback()
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM pg_namespace WHERE nspname=:schema'), {'schema': schema}) == 0
