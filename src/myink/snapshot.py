"""生成快照的留存投影：把一次生成尝试的原始输入裁成「值得留的部分」。

调用方（workflow/nodes.py 的 record_snapshot）只负责取数与落库，这里决定留什么。

为什么按渲染后的文本切节、而不是回头改 prompts.py 的拼装：提示词是各节拼成的一整段，
节边界就是行首的【…】标签。在渲染结果上切分不动拼装顺序与分隔符（生成行为零风险），
且 plan_cast / plan_chapter / write / audit / patch 的标签名各不相同但拼法一致，
一份规则全覆盖。

留存口径（用户定的「只存有分析价值的部分」）：
- full：随章变化、排障要逐字看的段（章节计划、文风要求、硬约束、近期上下文、大纲…）；
- hash：每章逐字节相同的模板、或库里另有全文的素材（题材包、题材参考文档），
  只留字节数与 sha256——足以证明它当时在场、也能与今天的设置比对是否改过，不占正文预算。
标签名不认识的节按 full 处理：宁可多留，不静默丢掉新加的段。
超过单节上限的节留到上限为止（记 truncated + 原字节数 + sha256）；合计预算见底时整节
退化为 hash（记 omitted=budget）——两种都不静默丢。
"""

from __future__ import annotations

import hashlib
import re

from myink.admin_observability import capture

# 逐节上限与合计上限（字节）。总行上限 64 KiB，与 agent_runs.detail 的遥测预算同量级：
# 那些 detail 只能看截断后的样子，本表是「原始输入」的正本。
# 三个数字按真书实测定（深渊天梯第 5 章）：各阶段要留 13.4–16.3 KB，单节最大 6075 字节
# （审计/补丁的提示词把本章原稿整段嵌了进去）。原来的 12000/4000 会把「章节计划」这类
# 最该逐字看的段砍掉——留存口径明说它要全文，预算却先一步截断，自相矛盾。
SECTION_BYTE_CAP = 8000
PROMPT_BYTE_BUDGET = 24000
ROW_BUDGET = 65536
# 预算只剩个零头时不留半截正文：剩不到一句话的字节，留 1 个字节既没有分析价值，
# 也不如整节退化成哈希干净（原字节数与 sha256 本来就在）。
MIN_SECTION_SLICE = 256
# 召回条目摘录与模型输出摘录（正文与台账原文在 chapters/memory 表里，不在这里重复存）
ITEM_EXCERPT_CHARS = 200
OUTPUT_EXCERPT_CHARS = 500

# 只留长度 + 哈希的节前缀。两类：① 每章逐字节相同的模板（SYSTEM_WRITE 前言）；
# ② 全库另有全文的静态素材——题材包与题材参考文档都在 project_settings / 语料里。
# 前缀匹配：大纲类标签名含卷名/阶段名，是动态的。
_HASH_PREFIXES = (
    "题材参考文档",
    "本书题材",
)
# 行首独占一行的【…】才是节标签；正文里引用标签名（「【近期上下文】中上一章结尾」）不算。
_LABEL = re.compile(r"(?m)^【([^】\n]{1,80})】[ \t]*$")
# 召回条目的定位字段（排障只问「带了谁、哪一章、什么类型」，不问全文）。
# is_hard/source 是「生效的硬规则」的判据：facts 表来的带 is_hard，建书时配置的带 source=project_settings。
_ITEM_KEYS = ("kind", "name", "fact_id", "event_id", "entity_id", "character_id", "thread_id",
              "foreshadow_id", "chapter", "chapter_seq", "source_chapter", "first_seen_chapter",
              "confidence", "status", "lesson_type", "category", "is_hard", "source")
# 摘录优先取这些内容字段（按序取第一个有值的）；都没有才退回最长字符串。
_EXCERPT_KEYS = ("content", "text", "description", "summary", "statement", "state", "excerpt",
                 "old_value", "new_value", "trigger", "reason", "suggestion", "quote", "name")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _clip_to_bytes(text: str, cap: int) -> tuple[str, bool]:
    """按字节裁到 cap 以内。二分而非按字数估：中文 3 字节/字，估算法会浪费半数预算。"""
    if len(text.encode()) <= cap:
        return text, False
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if len(text[:mid].encode()) <= cap:
            low = mid
        else:
            high = mid - 1
    return text[:low], True


def split_sections(text: str) -> list[dict]:
    """按行首的【标签】切分渲染后的提示词；首个标签之前是模板前言（name=None）。"""
    matches = list(_LABEL.finditer(text))
    if not matches:
        return [{"name": None, "text": text}]
    sections: list[dict] = []
    if matches[0].start() > 0:
        sections.append({"name": None, "text": text[:matches[0].start()]})
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append({"name": match.group(1), "text": text[match.end():end]})
    return sections


def _is_hash_section(name: str | None) -> bool:
    return bool(name) and name.startswith(_HASH_PREFIXES)


def project_prompt(messages: list[dict]) -> dict:
    """逐节投影提示词：full 留原文（受节上限与合计预算约束），其余留字节数 + 哈希。"""
    sections: list[dict] = []
    remaining = PROMPT_BYTE_BUDGET
    truncated = False
    for message in messages:
        role = message.get("role")
        for section in split_sections(str(message.get("content") or "")):
            name, text = section["name"], section["text"]
            raw_bytes = len(text.encode())
            # 放得下就留全文；放不下时剩余预算得够装一段话才切，否则整节退化哈希。
            keep_text = not _is_hash_section(name) and (
                raw_bytes <= remaining or remaining >= MIN_SECTION_SLICE)
            if keep_text:
                kept, clipped = _clip_to_bytes(text, min(SECTION_BYTE_CAP, remaining))
                remaining -= len(kept.encode())
                entry = {"role": role, "name": name, "policy": "full", "text": kept}
                if clipped:
                    entry.update({"truncated": True, "bytes": raw_bytes, "sha256": _sha(text)})
                    truncated = True
            else:
                omitted = not _is_hash_section(name)
                truncated |= omitted
                entry = {"role": role, "name": name, "policy": "hash",
                         "bytes": raw_bytes, "sha256": _sha(text)}
                if omitted:
                    entry["omitted"] = "budget"
            sections.append(entry)
    return {"sections": sections, "truncated": truncated, "bytes": PROMPT_BYTE_BUDGET}


def _longest_str(value: object, depth: int = 0) -> str:
    """取条目里最长的一段文本：字典里没有已知内容字段时的兜底。"""
    if isinstance(value, str):
        return value
    if depth >= 3:
        return ""
    if isinstance(value, dict):
        children = value.values()
    elif isinstance(value, (list, tuple)):
        children = value
    else:
        return ""
    return max((_longest_str(child, depth + 1) for child in children), key=len, default="")


def _excerpt_source(item: object) -> str:
    """摘录取内容字段而非最长字段：事实的 content 才是要看的，source 只是来源标记。"""
    if isinstance(item, dict):
        for key in _EXCERPT_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return _longest_str(item)


def _excerpt(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit]


def _project_item(item: object) -> dict:
    """召回条目只留定位字段 + 一段摘录，正文归属 chapters，不在这里重复存。"""
    if not isinstance(item, dict):
        return {"excerpt": _excerpt(_longest_str(item), ITEM_EXCERPT_CHARS)}
    out = {key: item[key] for key in _ITEM_KEYS
           if key in item and isinstance(item[key], (str, int, float, bool))}
    text = _excerpt(_excerpt_source(item), ITEM_EXCERPT_CHARS)
    if text:
        out["excerpt"] = text
    return out


def project_recall(context: dict | None) -> dict:
    """召回投影：逐条定位 + 摘录，配合全量统计量（空转/降级/捞错是这里的核心排障点）。

    空列表保留（counts 记 0）：「这一章根本没召回到长期事实」正是要看的结论，不能在
    投影时被当作「没有内容」抹掉。
    """
    ctx = context or {}
    groups = {key: [_project_item(item) for item in value]
              for key, value in ctx.items() if isinstance(value, list)}
    stats = {key: value for key, value in ctx.items() if not isinstance(value, list)}
    return {"groups": groups, "counts": {key: len(value) for key, value in groups.items()},
            "stats": stats}


def project_findings(findings: list | None) -> list:
    """校验发现与审计发现全留：证据已限 160 字、条数有限，是改进规则质量的关键样本。"""
    return [finding for finding in (findings or []) if isinstance(finding, dict)]


def project_output(content: str | None) -> dict:
    """模型输出只留长度 + 哈希 + 摘录：正文已落 chapters/chapter_versions，不重复存。"""
    text = content or ""
    return {"bytes": len(text.encode()), "sha256": _sha(text),
            "excerpt": _excerpt(text, OUTPUT_EXCERPT_CHARS)}


def finalize(payload: dict, previous: dict | None = None) -> dict:
    """套上 capture 的脱敏与硬顶（只去凭据与 URL 授权段，正文原样），并留下截断标记。

    二次写入（patch 先记提示词、应用后再补应用片段）传 previous=旧 payload：脱敏与截断
    是「这一行曾经发生过」的事实，不能因为第二轮没有再命中而被抹掉。
    """
    result = capture(payload, max_bytes=ROW_BUDGET)
    data = result["data"] if isinstance(result["data"], dict) else {}
    old = (previous or {}).get("_capture") or {}
    data["_capture"] = {"scope": "snapshot", "selective": True,
                        "truncated": bool(result["truncated"]) or bool(old.get("truncated")),
                        "redacted": bool(result["redacted"]) or bool(old.get("redacted")),
                        "limits": result["limits"]}
    return data
