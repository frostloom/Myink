"""Trusted collector: fixed projections, strict SELECT role, server-side deadlines."""
import re
from sqlalchemy import text
from .metrics import _PROJECTIONS, collect_snapshot

class SnapshotCollector:
    def __init__(self, engine):
        self.engine = engine

    def _validate_request(self, request):
        source = request.get('source')
        prefix = 'SELECT ' + _PROJECTIONS.get(source, '') + f' FROM {source} WHERE '
        sql = request.get('sql', '')
        tail = 'ORDER BY created_at, id LIMIT :limit OFFSET :offset'
        if (source not in _PROJECTIONS or request.get('read_only') is not True
                or type(request.get('timeout_ms')) is not int or not 1 <= request['timeout_ms'] <= 5000
                or not sql.startswith(prefix) or not sql.endswith(tail) or ';' in sql or '--' in sql):
            raise ValueError('unapproved metric query')
        where = sql[len(prefix):-len(tail)].strip()
        cohort = ('SELECT COALESCE(batch_task_id, id) FROM tasks '
                  'WHERE created_at >= :start AND created_at < :end')
        if source == 'tasks':
            valid = where == f'id IN ({cohort}) OR batch_task_id IN ({cohort})'
        else:
            valid = where == 'FALSE' or bool(re.fullmatch(
                r'created_at < :end AND task_id IN \(:thread_\d+(?:, :thread_\d+)*\)', where))
        if not valid:
            raise ValueError('unapproved metric predicate')

    def _read(self, request):
        self._validate_request(request)
        with self.engine.connect() as connection, connection.begin():
            connection.execute(text('SET LOCAL transaction_read_only = on'))
            connection.execute(text("SELECT set_config('statement_timeout', :timeout, true)"), {'timeout': str(request['timeout_ms'])})
            role = connection.execute(text('SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication '
                                           'FROM pg_roles WHERE rolname = current_user')).mappings().one()
            if any(role.values()):
                raise ValueError('privileged metric role')
            permissions = connection.execute(text("SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                                                  "WHERE grantee = current_user AND privilege_type <> 'SELECT' AND table_schema = 'public'" )).all()
            if permissions:
                raise ValueError('metric role has write grants')
            connection.execute(text('SET LOCAL transaction_read_only = on'))
            connection.execute(text("SELECT set_config('statement_timeout', :timeout, true)"),
                               {'timeout': str(request['timeout_ms'])})
            return [dict(row) for row in connection.execute(text(request['sql']), request['params']).mappings()]

    def collect(self, window, identity):
        return collect_snapshot(self._read, window, identity)
