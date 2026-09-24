"""短篇的确定性观测：只有字数（docs/SHORT-FORM.md §一 —— 「确定性检查只剩字数」）。

短篇整篇一次成稿，跨章一致性由注意力保证，所以那套分级校验（L1/L2/台账比对）整个不存在。
长度是唯一可机检的东西，而它在这里**只做观测**：长篇那条路上的 `major` 意味着「触发修订」，
短篇没有修订循环去消化它（改稿那一次是编辑视角驱动的，不喂字数），所以严重度取 `hint`，
发现只回给用户看，不拦稿、不落库、不进提示词。

判据复用长篇的字数门禁口径（`validation.service` 的 0.8×–1.3×target），常量直接引用同一份，
免得两个数各改各的。
"""

from __future__ import annotations

from myink.schemas import Finding
from myink.validation.service import _LEN_HIGH_RATIO, _LEN_LOW_RATIO


def observe_lengths(chapters: list[str], target: int) -> list[Finding]:
    """逐章字数观测（1-based 章号）。`target` 是每章目标字数，缺省/为 0 则不观测。

    空章跳过：那是补写的信号（`find_empty_chapters`），同一个事实报两遍只会淹掉真信号。
    """
    if not target:
        return []
    low, high = int(target * _LEN_LOW_RATIO), int(target * _LEN_HIGH_RATIO)
    findings: list[Finding] = []
    for i, body in enumerate(chapters):
        text = (body or "").strip()
        if not text:
            continue
        n = len(text)
        if low <= n <= high:
            continue
        seq = i + 1
        findings.append(Finding(
            conflict_key=f"short-len:{seq}",
            conflict_type="style", severity="hint", scope="local", source="L1",
            evidence=[{"chapter": seq,
                       "quote": f"第 {seq} 章正文 {n} 字，目标 {target} 字（区间 {low}–{high}）"}],
            suggestion=f"第 {seq} 章 {'长于' if n > high else '短于'}目标：{n} 字 / {target} 字",
        ))
    return findings