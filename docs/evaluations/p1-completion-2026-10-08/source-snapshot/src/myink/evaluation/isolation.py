"""Fail closed before synthetic evaluation writes to PostgreSQL."""
import os
from urllib.parse import urlsplit

from sqlalchemy import text


def require_isolated_database():
    from myink.config import settings
    from myink.db import get_admin_engine, new_session
    expected = os.getenv('MYINK_EVALUATION_SYSTEM_ID', '').strip()
    for value in (settings.database_url, settings.admin_database_url):
        url = urlsplit(value)
        if url.hostname not in ('127.0.0.1', 'localhost') or url.port != 15432 or url.path != '/myink':
            raise ValueError('evaluation requires isolated localhost:15432/myink')
    if not expected or settings.app_env != 'test':
        raise ValueError('test environment and approved database system identity required')
    with get_admin_engine().connect() as db:
        actual = str(db.execute(text('SELECT system_identifier FROM pg_control_system()')).scalar_one())
    if actual != expected:
        raise ValueError('isolated database identity mismatch')
    with new_session() as db:
        role = db.execute(text('SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()
        if role[0] != 'myink_app' or role[1] or role[2]:
            raise ValueError('evaluation business connection must enforce RLS')
    return {'system_identifier': actual, 'database': 'myink', 'port': 15432, 'business_role': role[0]}
