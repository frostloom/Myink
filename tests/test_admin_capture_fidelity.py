"""Capture fidelity contracts, independent of provider/config/DB fixtures.

Use synthetic credentials only. An alphabetic prefix is ordinary text, while
an undelimited credential suffix belongs to the secret until a real delimiter.
"""
import copy
import json

from myink.admin_observability import capture


def test_ascii_that_fits_the_byte_budget_is_retained_in_full():
    text = "a" * 9000
    # The complete JSON string fits comfortably within the 18KiB response cap.
    assert len(json.dumps(text, ensure_ascii=True).encode("utf-8")) < 17000
    result = capture(text, max_bytes=18000)
    assert result["data"] == text
    assert result["truncated"] is False
    assert result["redacted"] is False


def test_escaped_unicode_that_fits_is_not_clipped_by_character_estimates():
    text = ('文\n😀"' * 600) + ("a" * 1800)
    # JSON escaping charges different byte lengths for BMP, newline, quote and
    # surrogate-pair characters. This complete 4,200-character value still fits.
    assert len(text) == 4200
    assert len(json.dumps(text, ensure_ascii=True).encode("utf-8")) == 15002
    result = capture(text, max_bytes=18000)
    assert result["data"] == text
    assert result["truncated"] is False
    assert result["redacted"] is False


def test_adjacent_prefix_cannot_hide_a_whole_undelimited_bearer_secret():
    prefix = "ordinaryPrefix"
    secret = "syntheticCredential00_XYsuffixWithoutDelimiter"
    result = capture(prefix + "Bearer " + secret)
    assert result["data"] == prefix + "[REDACTED]"
    assert secret not in json.dumps(result)
    assert "suffixWithoutDelimiter" not in json.dumps(result)
    assert result["redacted"] is True
    assert result["truncated"] is False


def test_bearer_redaction_preserves_the_prefix_and_delimited_safe_tail():
    prefix = "ordinaryPrefix"
    secret = "syntheticCredential00_XY"
    safe_tail = " | ordinary safe tail"
    result = capture(prefix + "Bearer " + secret + safe_tail)
    assert result["data"] == prefix + "[REDACTED]" + safe_tail
    assert secret not in json.dumps(result)
    assert result["redacted"] is True
    assert result["truncated"] is False


def test_existing_text_byte_limits_and_input_immutability_remain_enforced():
    original = {"content": "Z" * 40000, "nested": ["ordinary text", 7]}
    before = copy.deepcopy(original)
    bounded = capture(original, max_bytes=200000)
    assert original == before
    assert bounded["limits"]["max_text"] == 16000
    assert bounded["limits"]["max_bytes"] == 65536
    assert bounded["truncated"] is True
    retained = bounded["data"]["content"]
    assert retained.endswith("[TRUNCATED]")
    assert len(retained.removesuffix("[TRUNCATED]")) <= 16000
    assert len(json.dumps(bounded, ensure_ascii=True).encode("utf-8")) <= 65536
    small = capture(original, max_bytes=1024)
    assert original == before
    assert small["limits"]["max_bytes"] == 1024
    assert small["truncated"] is True
    assert len(json.dumps(small, ensure_ascii=True).encode("utf-8")) <= 1024
