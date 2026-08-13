"""全局审计（阶段 3 长线治理 L2 · 切片 1：人设漂移抽样）。

plan.md §8.6「周期性全局审计」的抽样 L2 骨架：每 K 章对抽样角色做跨章人设漂移判定。
确定性编排（窗口 / 抽样 / 组装 / 核验 / 落库）+ 一次 LLM 判定（json_mode，空数组 = 无漂移）。

0 误报的兜底是 normalize_and_verify_findings 的确定性证据核验（evidence 引文必须是
该章正文逐字子串、chapter 在窗口内、character 在采样集、drift_type=persona、置信度
≥ 阈值），不是信任 LLM——LLM 过度标记会被守卫拦下，负例 0 误报由此保证（样例 12 阳性 /
新增阴性 36）。

采样口径：只审窗口内有名字/别名提及的角色（cap 3），零提及直接短路空报告——不给
LLM 喂无证据角色，防其从任意正文摘句凑数过子串守卫（宁缺毋滥，§8.8）。

数据流边界 §6.2：Agent 不直写——LLM 只产出候选 findings，落库走编排层（record_report）。
失败（LLM error / 解析失败）仍写 status=failed 报告行并推进 marker——非阻塞 + 有界，
防每批重审同一毒窗口（§8.6 落地注记）。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from aiink.models import Chapter, Character, GlobalAuditReport
from aiink.providers import make_chain

logger = logging.getLogger(__name__)

MAX_SAMPLED_CHARACTERS = 3  # 每轮审计抽样角色上限（成本有界：1 次 LLM 调用）
MAX_PASSAGES_PER_CHAR = 4  # 每角色摘录段落上限
QUOTE_WINDOW_CHARS = 80  # 每次提及截取的引用窗口宽度
MIN_CONFIDENCE = 0.6  # 宁缺毋滥：LLM 置信度低于此丢弃（L2 软冲突只提示不阻塞）


def last_audited_up_to(db: Session, project_id) -> int:
    """该租户已审计到的最远章号（global_audit_reports 进度 marker），无则 0。"""
    row = (db.query(func.max(GlobalAuditReport.audited_up_to_chapter))
           .filter(GlobalAuditReport.project_id == project_id).scalar())
    return row or 0


def current_max_chapter(db: Session, project_id) -> int:
    """该租户已写入的最大章号，无则 0。"""
    row = (db.query(func.max(Chapter.chapter_seq))
           .filter(Chapter.project_id == project_id).scalar())
    return row or 0


def window_for_batch(db: Session, project_id, *, K: int) -> tuple[int, int] | None:
    """批次触发窗口 = [上次审计后 +1, 当前最大章]；长度 < K → None（短路零成本）。

    跨批累计：上次审计后新写的章数达到 K 才审计（§8.6「每 K 章一次」），不足则跳过。
    """
    start = last_audited_up_to(db, project_id) + 1
    end = current_max_chapter(db, project_id)
    if end - start + 1 < K:
        return None
    return (start, end)


def sample_characters(db: Session, project_id, window: tuple[int, int],
                      *, cap: int = MAX_SAMPLED_CHARACTERS) -> list[dict]:
    """确定性抽样：窗口内有名字/别名提及的角色，按提及数降序（同名升序）cap。

    零提及角色不参与审计（无言行证据，喂给 LLM 只会诱发幻觉）——零提及则返回空表，
    调用方短路落空报告并推进 marker。返回 [{character_id, name}]。
    """
    chars = (db.query(Character)
             .filter(Character.project_id == project_id,
                     Character.personality.isnot(None))
             .all())
    if not chars:
        return []
    contents = {c.chapter_seq: c.content or "" for c in db.query(Chapter).filter(
        Chapter.project_id == project_id,
        Chapter.chapter_seq >= window[0],
        Chapter.chapter_seq <= window[1]).all()}
    scored = []
    for ch in chars:
        names = [ch.name] + list(ch.aliases or [])
        mentions = sum(sum(text.count(n) for n in names) for text in contents.values())
        scored.append({"character_id": str(ch.id), "name": ch.name, "mentions": mentions})
    mentioned = sorted(
        [s for s in scored if s["mentions"] > 0],
        key=lambda s: (-s["mentions"], s["name"]),
    )[:cap]
    return [{"character_id": s["character_id"], "name": s["name"]} for s in mentioned]


def assemble_persona_context(db: Session, project_id, window: tuple[int, int],
                             sampled: list[dict]) -> list[dict]:
    """每抽样角色：性格基线 + 窗口内言行摘录（逐字引用，供 LLM 判定与守卫核验）。

    摘录 = 每章首次提及处前后 ±QUOTE_WINDOW_CHARS/4 的正文片段，至多 MAX_PASSAGES_PER_CHAR 段。
    """
    chars = {str(c.id): c for c in db.query(Character).filter(
        Character.project_id == project_id,
        Character.id.in_([uuid.UUID(s["character_id"]) for s in sampled])).all()}
    chapters = (db.query(Chapter).filter(
        Chapter.project_id == project_id,
        Chapter.chapter_seq >= window[0],
        Chapter.chapter_seq <= window[1])
        .order_by(Chapter.chapter_seq).all())
    personas: list[dict] = []
    for s in sampled:
        ch = chars.get(s["character_id"])
        if ch is None:
            continue
        names = [ch.name] + list(ch.aliases or [])
        passages: list[dict] = []
        for c in chapters:
            content = c.content or ""
            idx = next((content.find(n) for n in names if content.find(n) >= 0), -1)
            if idx < 0:
                continue
            start = max(0, idx - QUOTE_WINDOW_CHARS // 4)
            passages.append({"chapter": c.chapter_seq, "quote": content[start:idx + QUOTE_WINDOW_CHARS].strip()})
            if len(passages) >= MAX_PASSAGES_PER_CHAR:
                break
        personas.append({"character_id": s["character_id"], "name": s["name"],
                         "baseline": ch.personality, "passages": passages})
    return personas


def _evidence_text(evidence) -> str | None:
    """LLM 输出 evidence 兼容 str 或 [{quote}]：取逐字引用文本。"""
    if isinstance(evidence, str):
        return evidence.strip()
    if isinstance(evidence, list) and evidence and isinstance(evidence[0], dict):
        q = evidence[0].get("quote")
        return str(q).strip() if q else None
    return None


def normalize_and_verify_findings(db: Session, project_id, raw, personas: list[dict],
                                  window: tuple[int, int]) -> list[dict]:
    """确定性核验守卫（0 误报的真正保证，独立于 LLM 行为）。

    逐条丢弃：非 dict / 字段缺失 / drift_type != persona / character 不在采样集 /
    chapter 不在窗口 / evidence 引文不是该章正文逐字子串 / 置信度 < MIN_CONFIDENCE。
    强制 severity=hint scope=local source=L2；(character, chapter) 去重保最高置信度。
    返回 Finding 形状 dict 列表（前端审计视图与章节 finding 同构渲染）。
    """
    contents = {c.chapter_seq: c.content or "" for c in db.query(Chapter).filter(
        Chapter.project_id == project_id,
        Chapter.chapter_seq >= window[0],
        Chapter.chapter_seq <= window[1]).all()}
    sampled_names = {p["name"] for p in personas}
    verified: dict[tuple, dict] = {}
    for f in raw or []:
        if not isinstance(f, dict):
            continue
        name = f.get("character")
        chapter = f.get("chapter")
        drift = f.get("drift_type")
        quote = _evidence_text(f.get("evidence"))
        reason = f.get("reason")
        try:
            confidence = float(f.get("confidence") or 0.0)
        except (TypeError, ValueError):
            continue
        if not (name and isinstance(chapter, int) and quote and reason
                and drift == "persona"):
            continue
        if name not in sampled_names:
            continue
        if not (window[0] <= chapter <= window[1]):
            continue
        content = contents.get(chapter)
        if content is None or quote not in content:  # 逐字子串校验（核验守卫）
            continue
        if confidence < MIN_CONFIDENCE:
            continue
        key = (name, chapter)
        prev = verified.get(key)
        if prev is None or confidence > prev["confidence"]:
            verified[key] = {
                "conflict_key": f"persona:{name}:{chapter}",
                "conflict_type": "persona",
                "severity": "hint",  # L2 软冲突一律 hint：不阻塞、不耗修订预算（§8.6）
                "scope": "local",
                "source": "L2",
                "evidence": [{"chapter": chapter, "quote": quote}],
                "confidence": confidence,
                "suggestion": f"角色「{name}」第 {chapter} 章言行与性格基线不符：{reason}",
            }
    return [verified[k] for k in sorted(verified, key=lambda k: k[1])]


def record_report(db: Session, *, project_id, window: tuple[int, int], findings: list[dict],
                  sampled: list[dict], status: str, error: str | None, source: str,
                  source_batch_task_id: str | None = None) -> dict:
    """审计报告落库（编排层写库，§6.2）并返回报告 dict。audited_up_to = window_end 推进 marker。"""
    window_start, window_end = window
    db.add(GlobalAuditReport(
        project_id=uuid.UUID(project_id), window_start=window_start, window_end=window_end,
        audited_up_to_chapter=window_end, trigger=source,
        source_batch_task_id=source_batch_task_id, status=status,
        sampled_characters=sampled, findings=findings,
        summary={"sampled": len(sampled), "findings": len(findings),
                 "chapters": window_end - window_start + 1},
        error=error,
    ))
    db.flush()  # autoflush=False：同会话后续查询需显式可见
    return {
        "window_start": window_start, "window_end": window_end,
        "audited_up_to_chapter": window_end, "status": status,
        "sampled_characters": sampled, "findings": findings, "error": error,
        "summary": {"sampled": len(sampled), "findings": len(findings),
                    "chapters": window_end - window_start + 1},
    }


def run_global_audit(db: Session, project_id, window: tuple[int, int], *,
                     source: str = "manual", source_batch_task_id: str | None = None) -> dict:
    """全局审计编排入口：抽样 → 组装 → 1 次 LLM 判定 → 确定性核验 → 落库。

    - 零提及（窗口内无角色可审）：短路落空报告并推进 marker（有界，防每批重审）；
    - LLM error / 解析失败：写 status=failed 报告 + 推进 marker（非阻塞，§8.6）；
    - 成功：findings 经核验守卫后落库，status=completed。
    函数级懒导入 workflow.nodes（validation 被 workflow.nodes 模块级引用，模块级
    import 会成环；懒导入破环，mirror reflexion 的运行记录模式）。
    """
    from aiink.workflow import nodes, prompts  # 懒导入防循环（见 docstring）

    pid = str(project_id)
    window_start, window_end = window
    sampled = sample_characters(db, pid, window)
    personas = assemble_persona_context(db, pid, window, sampled) if sampled else []
    detail = {"window": [window_start, window_end], "sampled": [p["name"] for p in personas]}
    if not personas:
        logger.info("全局审计窗口 %d-%d 无角色提及，落空报告（已推进 marker）", window_start, window_end)
        return record_report(db, project_id=pid, window=window, findings=[], sampled=[],
                             status="completed", error=None, source=source,
                             source_batch_task_id=source_batch_task_id)

    messages = prompts.global_audit_messages(personas, window)
    resp = make_chain("audit").generate(messages, json_mode=True,
                                        max_tokens=nodes._MAX_TOKENS["audit"])
    nodes.record_run(db, project_id=pid, task_id=source_batch_task_id, node="global_audit",
                     role="GlobalAudit", resp=resp, error=resp.error, detail=detail)
    if resp.error:
        logger.warning("全局审计 LLM 失败（不阻塞，marker 已推进）: %s", resp.error)
        return record_report(db, project_id=pid, window=window, findings=[],
                             sampled=personas, status="failed", error=resp.error,
                             source=source, source_batch_task_id=source_batch_task_id)
    try:
        data = nodes._parse_json(resp.content)
    except Exception as exc:  # noqa: BLE001 —— 解析失败同 LLM 失败处理（§6.12）
        logger.warning("全局审计输出解析失败（不阻塞，marker 已推进）: %s", exc)
        return record_report(db, project_id=pid, window=window, findings=[],
                             sampled=personas, status="failed", error=f"parse_error: {exc}",
                             source=source, source_batch_task_id=source_batch_task_id)
    raw = data.get("findings", []) if isinstance(data, dict) else []
    findings = normalize_and_verify_findings(db, pid, raw, personas, window)
    return record_report(db, project_id=pid, window=window, findings=findings,
                         sampled=personas, status="completed", error=None,
                         source=source, source_batch_task_id=source_batch_task_id)
