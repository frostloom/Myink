"""Shared fixed metric SQL grammar, independent of database client libraries."""
import re
from .metrics import _PROJECTIONS


def validate_metric_request(request):
    source=request.get('source');sql=request.get('sql','')
    if not isinstance(source,str) or source not in _PROJECTIONS:raise ValueError('unapproved metric source')
    prefix='SELECT '+_PROJECTIONS[source]+f' FROM {source} WHERE '
    tail='ORDER BY created_at, id LIMIT :limit OFFSET :offset'
    if (request.get('read_only') is not True or type(request.get('timeout_ms')) is not int
            or not 1<=request['timeout_ms']<=5000 or not isinstance(sql,str)
            or not sql.startswith(prefix) or not sql.endswith(tail) or ';' in sql or '--' in sql):
        raise ValueError('unapproved metric query')
    where=sql[len(prefix):-len(tail)].strip()
    cohort='SELECT COALESCE(batch_task_id, id) FROM tasks WHERE created_at >= :start AND created_at < :end'
    valid=where==f'id IN ({cohort}) OR batch_task_id IN ({cohort})' if source=='tasks' else where=='FALSE' or bool(re.fullmatch(r'created_at < :end AND task_id IN \(:thread_\d+(?:, :thread_\d+)*\)',where))
    if not valid:raise ValueError('unapproved metric predicate')
