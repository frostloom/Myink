"""短篇整篇草稿的宽容解析（docs/SHORT-FORM.md §二 第 3 步 / §四）。

短篇是「一次调用写完 5–10 章」，拆章只能靠模型自己打的标记。模型不保证听话，于是四级回退：
block 标记 → markdown 标题 → 数字前缀 → 按段落均分。

与长篇的取向**相反，这是有意的**（决策文档 §二）：长篇走严格契约（Pydantic + `_parse_json`，
坏数据拒绝），而短篇整篇一次输出、格式漂移概率高得多，同一条严格契约只会在长输出上频繁失败。
所以这里**从宽解析 + 事后再修**：拆不出来就把那一格留成空串，交给 `find_empty_chapters` 去数、
交给补写去补。**绝不抛异常**——一个抛异常的解析器会把一次 160 秒的生成变成一次 500。
"""

from __future__ import annotations

import re

# 写手 prompt 与解析器**共用这一个常量**：prompt 让人照它打标记，解析器按它切块。
# 改这里等于同时改提示词契约，所以只此一份。形状取自参照实现（决策文档 §四）。
CHAPTER_HEADING = "=== CHAPTER {seq} CONTENT ==="

# 模型爱多打一行「章标题」标记（参照实现的产物就是 TITLE + CONTENT 两行）。
# 删掉而不是当边界：当边界会把每章切成两格，正文整体错位一格，比空章难查得多。
_TITLE_LINE = re.compile(r"^=+\s*CHAPTER\s*\d+\s+TITLE\s*=+\s*$", re.IGNORECASE | re.MULTILINE)

# 一级：`=== CHAPTER N [CONTENT] ===` / `=== 第 N 章 ===`（章号后面只允许跟 CONTENT）。
_TAGGED = re.compile(
    r"^=+\s*(?:CHAPTER\s*(\d+)(?:\s+CONTENT)?|第\s*(\d+)\s*章)\s*=+\s*$",
    re.IGNORECASE | re.MULTILINE)
# 二级：markdown 标题；三级：行首章号前缀（`第 N 章` / `N.` / `N、`）。
_HEADING = re.compile(r"^#{1,6}\s*(?:第\s*(\d+)\s*章|CHAPTER\s*(\d+))", re.IGNORECASE | re.MULTILINE)
_PREFIX = re.compile(r"^\s*(?:第\s*(\d+)\s*章|(\d{1,3})\s*[.、,，:：])\s*", re.MULTILINE)

_BLANK_LINE = re.compile(r"\n\s*\n")


def find_empty_chapters(chapters: list[str]) -> list[int]:
    """空章的 1-based 章号（空串与纯空白都算空）。补写的触发条件就靠这个可确定的状态。"""
    return [i + 1 for i, body in enumerate(chapters) if not (body or "").strip()]


def parse_short_draft(text: str, chapter_count: int) -> list[str]:
    """把整篇草稿拆成 `chapter_count` 格正文：格子 = 章（0-based），拆不出来的是空串。

    永远返回这个长度、永远不抛异常。
    """
    if chapter_count <= 0:
        return []
    body = _TITLE_LINE.sub("", text or "")
    for pattern in (_TAGGED, _HEADING):
        blocks = _split(body, pattern)
        if blocks:
            return _assemble(blocks, chapter_count)
    blocks = _split(body, _PREFIX)
    if blocks and _looks_like_chapter_numbers([seq for seq, _ in blocks], chapter_count):
        return _assemble(blocks, chapter_count)
    return _even_split(body, chapter_count)


def _looks_like_chapter_numbers(seqs: list[int], chapter_count: int) -> bool:
    """数字前缀这一级要不要信：**从 1 起、严格递增、不越界**。

    这一级最容易被散文误伤——正文里以「3：」开头的一行也命中，而误判的代价是标记之前的
    正文被 `_split` 当前言丢掉。一份真的章节清单总是从 1 开始往上走；单条或散落的章号不是。
    """
    return bool(seqs) and seqs[0] == 1 and seqs[-1] <= chapter_count and all(
        a < b for a, b in zip(seqs, seqs[1:]))


def render_short_draft(chapters: list[str]) -> str:
    """把拆好的逐章正文重新装回一篇带标记的草稿。

    审稿与改稿喂的就是这个形状：读者读到的也是它（落库按块拆章）。直接回喂模型的原始
    输出的话，模型整篇不打卡时审稿看到的是一堵墙，而不是「第 3 章后半段泄气」。
    空章不装——审稿不该看见一排空标记。
    """
    return "\n\n".join(
        CHAPTER_HEADING.format(seq=i + 1) + "\n" + body.strip()
        for i, body in enumerate(chapters) if (body or "").strip())


def _split(text: str, pattern: re.Pattern) -> list[tuple[int, str]]:
    """按标记切块 → `[(章号, 正文)]`，正文不含标记行本身；标记之前的前言（整篇标题等）丢弃。"""
    matches = list(pattern.finditer(text))
    if not matches:
        return []
    blocks = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append((int(match.group(1) or match.group(2) or 0), text[match.end():end].strip()))
    return blocks


def _assemble(blocks: list[tuple[int, str]], n: int) -> list[str]:
    """按章号归位；章号不可信（重复 / 越界）时退回按出现顺序。

    归位比顺序重要：模型只写了前 3 章时，顺序装配会把第 3 章塞进第 4 格，补写随后就会
    以为「第 3 章有了」——错位比空章难查得多。

    判据是「互不相同且都在 1..n 内」，不是「构成 1..块数 的排列」：**缺号恰恰是可信的**，
    而且正是补写要用的那个确定状态（1、2、4、5 说明缺的是第 3 章）。只有重复或越界才真的
    说明章号不可信。
    """
    seqs = [seq for seq, _ in blocks]
    if len(set(seqs)) != len(seqs) or any(not 1 <= seq <= n for seq in seqs):
        blocks = [(i + 1, body) for i, (_, body) in enumerate(blocks)]
    chapters = [""] * n
    for seq, body in blocks:
        chapters[seq - 1] = body
    return chapters


def _even_split(text: str, n: int) -> list[str]:
    """最后一道兜底：按段落贪心均分。宁可切歪，也不能让整篇丢在地上。"""
    paragraphs = [p.strip() for p in _BLANK_LINE.split((text or "").strip()) if p.strip()]
    if not paragraphs:
        return [""] * n
    target = sum(len(p) for p in paragraphs) / n
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    remaining = n
    for i, para in enumerate(paragraphs):
        buf.append(para)
        size += len(para)
        rest = len(paragraphs) - i - 1
        # 只在「剩下的段落还够填满剩下的格」时才封口，否则尾巴会被挤成一格。
        if remaining > 1 and rest >= remaining - 1 and size >= target:
            parts.append("\n\n".join(buf))
            buf, size = [], 0
            remaining -= 1
    if buf:
        parts.append("\n\n".join(buf))
    parts.extend([""] * (n - len(parts)))
    return parts[:n]