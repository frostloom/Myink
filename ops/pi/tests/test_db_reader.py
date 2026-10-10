import pytest
from ops.pi.db_reader import SnapshotCollector

@pytest.mark.parametrize('sql', ['DELETE FROM tasks', 'SELECT pg_sleep(9)', 'SELECT * FROM tasks', 'SELECT id FROM tasks; SELECT 1'])
def test_arbitrary_query_rejected(sql):
    reader = SnapshotCollector(None)
    with pytest.raises(ValueError):
        reader._validate_request({'source': 'tasks', 'sql': sql, 'read_only': True, 'timeout_ms': 5000, 'params': {}})

def test_reader_timeout_cannot_exceed_server_bound():
    reader = SnapshotCollector(None)
    with pytest.raises(ValueError):
        reader._validate_request({'source': 'tasks', 'sql': 'SELECT id FROM tasks', 'read_only': True, 'timeout_ms': 5001, 'params': {}})
