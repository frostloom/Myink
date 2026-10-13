"""Trusted collector: fixed projections, strict SELECT role, server-side deadlines."""
import re
from datetime import datetime
from sqlalchemy import text
from .metrics import _PROJECTIONS, collect_snapshot
from .feedback import make_feedback_snapshot, normalize_window, validate_cursor

_FEEDBACK_SQL = ("SELECT id, category, LEFT(description, 2001) AS description, status, created_at, updated_at "
                 "FROM feedback WHERE updated_at >= :start AND updated_at < :end ")
_FEEDBACK_TAIL = "ORDER BY updated_at, id LIMIT :limit"
_FEEDBACK_CURSOR = "AND (updated_at, id) > (:cursor_time, :cursor_id) "

class SnapshotCollector:
    def __init__(self, engine):
        self.engine = engine

    def _validate_request(self, request):
        source = request.get('source')
        if source == 'feedback':
            self._validate_feedback_request(request)
            return
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
            if request['source'] == 'feedback':
                connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
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

    def _validate_feedback_request(self, request):
        params = request.get('params', {})
        has_cursor = 'cursor_id' in params
        expected = _FEEDBACK_SQL + (_FEEDBACK_CURSOR if has_cursor else '') + _FEEDBACK_TAIL
        keys = {'start', 'end', 'limit'} | ({'cursor_time', 'cursor_id'} if has_cursor else set())
        if (set(request) != {'source', 'sql', 'params', 'read_only', 'timeout_ms'}
                or request.get('read_only') is not True or request.get('sql') != expected
                or not isinstance(params, dict) or set(params) != keys
                or type(params.get('limit')) is not int or params['limit'] != 51
                or type(request.get('timeout_ms')) is not int or not 1 <= request['timeout_ms'] <= 5000):
            raise ValueError('unapproved feedback query')
        window = normalize_window(dict(start=params['start'], end=params['end']))
        if has_cursor:
            from .feedback import _hash
            validate_cursor(dict(scope='admin', window_sha256=_hash(window),
                                 updated_at=params['cursor_time'], id=params['cursor_id']), window)

    def collect_feedback(self, window, *, admin_scope=False, cursor=None):
        """Host-only account-level collection; text cannot supply admin authority."""
        if admin_scope is not True:
            raise ValueError('explicit trusted admin scope required')
        frozen = normalize_window(window)
        cursor = validate_cursor(cursor, frozen)
        params = dict(start=datetime.fromisoformat(frozen['start']), end=datetime.fromisoformat(frozen['end']), limit=51)
        if cursor:
            params.update(cursor_time=datetime.fromisoformat(cursor['updated_at']), cursor_id=cursor['id'])
        request = dict(source='feedback', sql=_FEEDBACK_SQL + (_FEEDBACK_CURSOR if cursor else '') + _FEEDBACK_TAIL,
                       params=params, read_only=True, timeout_ms=5000)
        return make_feedback_snapshot(self._read(request), frozen, cursor=cursor)
