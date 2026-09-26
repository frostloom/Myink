"""对话式短篇建书的纯逻辑：方案卡、合并规则、就绪判定、premise 拼装。

与 `short/form.py` 的分工：那边管篇幅护栏（章数/每章字数，后端最终按它归一），
这边管「聊出来的那张卡」。这里没有 I/O，LLM 那一回合在 `book_setup` 里。
"""

from __future__ import annotations

import math

from pydantic import BaseModel

# 凑齐这 7 个才允许「确认，开写」。后端自算，不信模型自报 ready——
# 模型很容易在只聊了两句时说「这就够了」，而短篇方案缺了冲突或回报就是一堆空话。
REQUIRED_CARD_FIELDS = (
    "working_title", "genre", "direction", "protagonist_pressure",
    "conflict_core", "emotional_payoff", "plot_sketch",
)

DEFAULT_CHAPTER_COUNT = 5
# 5 × 4000 = 20000，正好是 SHORT_TOTAL_MAX（short/form.py）——默认值不触发压缩。
DEFAULT_CHARS_PER_CHAPTER = 4000

_NUMBER_FIELDS = ("chapter_count", "chars_per_chapter")


class ShortCreationCard(BaseModel):
    """方案卡：模型提案与用户可编辑的**同一份数据**（右栏就是它的可编辑视图）。"""

    working_title: str = ""
    genre: str = ""
    direction: str = ""
    protagonist_pressure: str = ""
    conflict_core: str = ""
    emotional_payoff: str = ""
    plot_sketch: str = ""
    chapter_count: int = DEFAULT_CHAPTER_COUNT
    chars_per_chapter: int = DEFAULT_CHARS_PER_CHAPTER


def default_card() -> dict:
    return ShortCreationCard().model_dump()


def _known(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for key, value in raw.items():
        if key not in ShortCreationCard.model_fields:
            continue
        if isinstance(value, bool):          # bool 是 int 的子类，先挡掉
            continue
        if isinstance(value, str):
            text = value.strip()
            if key in _NUMBER_FIELDS:
                try:
                    out[key] = int(float(text))
                except (ValueError, OverflowError):
                    continue                 # 数字位上的垃圾/空串/无穷：宁可不改，也不写进去
                continue
            out[key] = text
            continue
        if isinstance(value, (int, float)):
            # 只有数字位收数字；文本位收数字会让 Project(title=<int>) 在建书那步崩。
            if key not in _NUMBER_FIELDS:
                continue
            if not math.isfinite(value):     # Infinity / NaN / 1e400 一律当「没给」
                continue
            out[key] = int(value)
    return out


def card_patch(raw) -> dict:
    """模型这轮给的卡：只收已知字段，且**空串不留**。

    留空是不留痕的意思——「这轮我没新想法」。若把空串也当值写进去，模型一轮走神就能把
    用户手写好的一段抹掉。
    """
    return {key: value for key, value in _known(raw).items()
            if not (isinstance(value, str) and value == "")}


def card_normalize(raw) -> dict:
    """用户改过的卡：只收已知字段，**空串照收**——用户有权把一个字段清空。

    与 `card_patch` 的唯一差别就是这一条。
    """
    return _known(raw)


def merge_model_card(current: dict, raw) -> dict:
    return {**(current or {}), **card_patch(raw)}


def merge_user_card(current: dict, edited) -> dict:
    return {**(current or {}), **card_normalize(edited)}


def card_ready(card: dict) -> bool:
    return all(str((card or {}).get(field) or "").strip() for field in REQUIRED_CARD_FIELDS)


def card_premise(card: dict) -> str:
    """拼成 `premise` 一段——方案生成器只吃一个字符串（`generate_short_plan` 的入参）。"""
    card = card or {}
    parts = [str(card.get("direction") or "").strip()]
    for label, key in (("主角压力", "protagonist_pressure"), ("核心冲突", "conflict_core"),
                       ("情绪回报", "emotional_payoff"), ("大致情节", "plot_sketch")):
        value = str(card.get(key) or "").strip()
        if value:
            parts.append(f"{label}：{value}")
    return "\n\n".join(part for part in parts if part)
