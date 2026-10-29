"""Pure reporting tests: no database connection."""
from datetime import date
from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException
from myink.api import routes_admin


def test_empty_days_are_filled_and_metrics_are_separate():
    db = MagicMock()
    db.execute.return_value.mappings.return_value.all.side_effect = [
        [{"day": date(2026, 1, 2), "count": 2}], [], [], [],
        [{"day": date(2026, 1, 2), "run_count": 1, "input_tokens": 12,
          "output_tokens": 7, "cost_est": 0.25}],
    ]
    result = routes_admin.trends(db, date(2026, 1, 1), date(2026, 1, 3))
    assert len(result["items"]) == 3
    assert result["items"][0]["run_count"] == 0
    assert result["items"][1]["user_count"] == 2
    assert result["items"][1]["input_tokens"] == 12
    assert result["items"][1]["output_tokens"] == 7
    assert result["items"][1]["cost_est"] == 0.25


@pytest.mark.parametrize("start,end", [(date(2026,1,2),date(2026,1,1)),
                                       (date(2026,1,1),date(2026,4,1)),
                                       (date.max,date.max)])
def test_invalid_range_never_queries_reporting_connection(start, end):
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        routes_admin.trends(db, start, end)
    assert exc.value.status_code == 422
    db.execute.assert_not_called()
