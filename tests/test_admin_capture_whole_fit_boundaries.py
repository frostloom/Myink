"""Whole-fitting capture values must not pay for an unused truncation marker."""
import json

import pytest

from myink.admin_observability import capture


@pytest.mark.parametrize(
    ("text", "max_bytes"),
    [
        pytest.param("A" * 100, 680, id="ascii"),
        pytest.param("\u6587" * 74, 1024, id="bmp-unicode"),
        pytest.param("\U0001f600" * 37, 1024, id="astral-unicode"),
        pytest.param('"' * 222, 1024, id="escaped-quote"),
        pytest.param("\\" * 222, 1024, id="escaped-backslash"),
    ],
)
def test_whole_fitting_text_is_preserved_without_a_truncation_marker(text, max_bytes):
    # These small values fit, including the capture envelope. JSON escaping must
    # not make an unnecessary marker displace text that could be kept in full.
    result = capture(text, max_bytes=max_bytes)
    assert len(json.dumps(result, ensure_ascii=True).encode("utf-8")) <= max_bytes
    assert result["data"] == text
    assert result["truncated"] is False
    assert result["redacted"] is False
