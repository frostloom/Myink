"""短篇形态的参数联合约束（docs/SHORT-FORM.md §5）。纯函数，无 I/O，方便直接测。"""

from __future__ import annotations

from dataclasses import dataclass

SHORT_CHAPTER_MIN, SHORT_CHAPTER_MAX = 1, 10
SHORT_CHARS_MIN, SHORT_CHARS_MAX = 1000, 8000
SHORT_TOTAL_MAX = 20000


def resolve_short_lengths(chapter_count: int, chars_per_chapter: int) -> tuple[int, int, bool]:
    """把用户给的「章数 / 每章字数」归一成合法参数。

    返回 `(章数, 归一后的每章字数, 是否发生过压缩)`。超限是「按比例压每章字数并
    告知」，不是拒绝；第三个返回值就是给路由回前端提示用的。

    先各自夹进声明区间再看总量：每章字数上限 8000 是「再长就该拆章」，下限 1000 是
    「再短写不出完整场面」。总量超了就用 20000 // 章数 反推——这条规则自然给出
    「章数少则每章长」。
    """
    chapters = min(max(chapter_count, SHORT_CHAPTER_MIN), SHORT_CHAPTER_MAX)
    chars = min(max(chars_per_chapter, SHORT_CHARS_MIN), SHORT_CHARS_MAX)
    if chapters * chars > SHORT_TOTAL_MAX:
        return chapters, max(SHORT_CHARS_MIN, SHORT_TOTAL_MAX // chapters), True
    return chapters, chars, False


@dataclass(frozen=True)
class ShortParams:
    """短篇写手要的规模参数：已归一（章数/每章字数都在区间内、总量不超上限）。"""

    chapter_count: int
    chars_per_chapter: int
    compressed: bool = False

    @classmethod
    def resolve(cls, chapter_count: int, chars_per_chapter: int) -> ShortParams:
        chapters, chars, compressed = resolve_short_lengths(chapter_count, chars_per_chapter)
        return cls(chapters, chars, compressed)

    @property
    def total_chars(self) -> int:
        """全篇目标字数——一次成稿的 max_tokens 就是照它换算的。"""
        return self.chapter_count * self.chars_per_chapter