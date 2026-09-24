"""短篇的字数观测（SHORT-FORM-PLAN Phase 4）。

短篇消掉了跨章一致性，**确定性检查只剩字数**（决策文档 §一）。但这条检查的严重度必须
是观测而不是门禁：长篇那套 `major` 的意思是「触发修订」，短篇没有那条路——改稿那一次是
编辑视角驱动的，不喂字数。所以这里只需要钉住两件事：判据说得清（复用长篇的 0.8×–1.3×
口径）、**不阻塞**（severity 是 hint，且空章不重复报「过短」）。
"""

from __future__ import annotations

import pytest

from myink.validation.short import observe_lengths

TARGET = 4000


def _body(n: int) -> str:
    return "字" * n


def test_a_chapter_inside_the_band_produces_no_finding():
    assert observe_lengths([_body(TARGET)], TARGET) == []


@pytest.mark.parametrize("n", [int(TARGET * 0.8), TARGET, int(TARGET * 1.3)])
def test_the_band_edges_are_inclusive(n):
    """区间是闭区间——长篇的门禁就是 `low <= n <= high`，短篇照抄口径。"""
    assert observe_lengths([_body(n)], TARGET) == []


def test_a_short_chapter_is_reported_as_an_observation_not_a_gate():
    findings = observe_lengths([_body(100)], TARGET)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "hint", "观测不阻塞：major 在长篇那条路上是「触发修订」的意思"
    assert finding.conflict_key == "short-len:1"
    assert finding.evidence[0].chapter == 1
    assert "100" in finding.evidence[0].quote
    assert "3200" in finding.evidence[0].quote and "5200" in finding.evidence[0].quote


def test_a_long_chapter_is_reported_too():
    """超长同样只观测——短篇的水漫金山不比过短轻，但都不拦。"""
    findings = observe_lengths([_body(9000)], TARGET)

    assert len(findings) == 1 and findings[0].severity == "hint"


def test_findings_are_numbered_by_chapter_position():
    findings = observe_lengths([_body(TARGET), _body(100), _body(9000)], TARGET)

    assert [(f.conflict_key, f.evidence[0].chapter) for f in findings] == [
        ("short-len:2", 2), ("short-len:3", 3)]


def test_an_empty_chapter_is_left_to_the_continuation():
    """空章是补写的事，不该在这里再报一次「过短」——同一个事实报两遍只会淹掉真信号。"""
    assert observe_lengths(["", "   \n ", _body(TARGET)], TARGET) == []


@pytest.mark.parametrize("target", [0, None])
def test_no_target_means_no_observation(target):
    assert observe_lengths([_body(10)], target) == []