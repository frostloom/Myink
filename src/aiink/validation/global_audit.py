"""全局审计（阶段 3 长线治理 L2 · 切片 1 人设漂移抽样 + 切片 2 桥段重复「呼应 vs 重复」）。

plan.md §8.6「周期性全局审计」的抽样 L2 骨架：每 K 章对窗口内候选做跨章长线判定。
两个维度共用同一窗口与同一报告行（一次 marker 推进，防 per-kind 标记错位）：
  - 维度 A 人设漂移：抽样角色性格基线 vs 窗口言行摘录（切片 1）；
  - 维度 B 桥段重复：窗口事件 vs 历史事件向量近邻 → LLM 判「刻意呼应 vs 偷懒重复」（切片 2）。
确定性编排（窗口 / 抽样 / 组装 / 核验 / 落库）+ 每维度一次 LLM 判定（json_mode，空数组 = 无发现）。

0 误报的兜底是 _verify_findings 的确定性证据核验（evidence 引文必须是该章正文逐字
子串、chapter 在窗口内、实体在采样集、kind 合法、置信度 ≥ 阈值），不是信任 LLM——
LLM 过度标记会被守卫拦下，负例 0 误报由此保证（样例 12/36 阳性阴性、样例 32/37
桥段呼应对照）。

采样口径：persona 只审窗口内有名字/别名提及的角色（cap 3），零提及短路空报告；
bridge 只审窗口内事件命中历史向量近邻且未被呼应词表豁免的候选对（cap 3），零候选
短路——不给 LLM 喂无证据候选，防其从任意正文摘句凑数过子串守卫（宁缺毋滥，§8.8）。

数据流边界 §6.2：Agent 不直写——LLM 只产出候选 findings，落库走编排层（record_report）。
维度失败（LLM error / 解析失败）不阻塞另一维度：失败维度 error 记入 summary["errors"]；
报告 status = completed（任一维度成功或全维度中性）或 failed（有维度失败且无维度成功），
marker 照常推进——非阻塞 + 有界，防每批重审同一毒窗口（§8.6 落地注记）。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aiink.memory.embedder import get_embedder
from aiink.memory.vector_store import PgvectorStore
from aiink.models import Chapter, Character, Event, GlobalAuditReport
from aiink.providers import make_chain
from aiink.validation.l1 import (  # 复用 L1 桥段阈值与呼应词表（同包私有导入，无环）
    _REPEAT_DIST_THRESHOLD,
    _REPEAT_MIN_GAP,
    _REPEAT_TOP_K,
    _has_callback_marker,
)

logger = logging.getLogger(__name__)

MAX_SAMPLED_CHARACTERS = 3  # 每轮审计抽样角色上限（成本有界：1 次 LLM 调用）
MAX_PASSAGES_PER_CHAR = 4  # 每角色摘录段落上限
QUOTE_WINDOW_CHARS = 80  # 每次提及截取的引用窗口宽度
MIN_CONFIDENCE = 0.6  # 宁缺毋滥：LLM 置信度低于此丢弃（L2 软冲突只提示不阻塞）

MAX_BRIDGE_PAIRS = 3  # 每轮审计桥段候选对上限（成本有界：另一维度的 1 次 LLM 调用）
MAX_BRIDGE_SCAN_EVENTS = 8  # 窗口事件扫描池上限（先按 confidence 降序预筛）
MAX_BRIDGE_CHAPTER_CHARS = 3000  # 当前章正文节选上限（供 LLM 逐字引用；核验仍用全章）


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


def _verify_findings(db: Session, project_id, raw, window: tuple[int, int], *,
                     entity_field: str, kind_field: str, kind_value: str,
                     resolve, emit) -> list[dict]:
    """共享确定性核验守卫（0 误报的真正保证，persona/bridge 两维度共用，独立于 LLM 行为）。

    逐条丢弃：非 dict / 字段缺失 / kind != 预期值 / 实体不在采样集 / chapter 不在窗口 /
    evidence 引文不是该章正文逐字子串 / 置信度 < MIN_CONFIDENCE。强制 severity=hint
    scope=local source=L2；(去重键, chapter) 去重保最高置信度。
    resolve(entity) -> dict | None：LLM 输出实体标识 → 采样集内目标（不在采样集 → None 丢弃）；
    emit(target, chapter, quote, confidence, reason) -> (去重键, Finding 形状 dict)。
    返回 Finding 形状 dict 列表（前端审计视图与章节 finding 同构渲染）。
    """
    contents = {c.chapter_seq: c.content or "" for c in db.query(Chapter).filter(
        Chapter.project_id == project_id,
        Chapter.chapter_seq >= window[0],
        Chapter.chapter_seq <= window[1]).all()}
    verified: dict[tuple, dict] = {}
    for f in raw or []:
        if not isinstance(f, dict):
            continue
        entity = f.get(entity_field)
        chapter = f.get("chapter")
        kind = f.get(kind_field)
        quote = _evidence_text(f.get("evidence"))
        reason = f.get("reason")
        try:
            confidence = float(f.get("confidence") or 0.0)
        except (TypeError, ValueError):
            continue
        if not (entity and isinstance(chapter, int) and quote and reason
                and kind == kind_value):
            continue
        target = resolve(entity)
        if target is None:
            continue
        if not (window[0] <= chapter <= window[1]):
            continue
        content = contents.get(chapter)
        if content is None or quote not in content:  # 逐字子串校验（核验守卫）
            continue
        if confidence < MIN_CONFIDENCE:
            continue
        key, finding = emit(target, chapter, quote, confidence, reason)
        prev = verified.get(key)
        if prev is None or confidence > prev["confidence"]:
            verified[key] = finding
    return [verified[k] for k in sorted(verified, key=lambda k: k[1])]


def normalize_and_verify_findings(db: Session, project_id, raw, personas: list[dict],
                                  window: tuple[int, int]) -> list[dict]:
    """确定性核验守卫（人设漂移维度，0 误报的真正保证，独立于 LLM 行为）。

    逐条丢弃：非 dict / 字段缺失 / drift_type != persona / character 不在采样集 /
    chapter 不在窗口 / evidence 引文不是该章正文逐字子串 / 置信度 < MIN_CONFIDENCE。
    强制 severity=hint scope=local source=L2；(character, chapter) 去重保最高置信度。
    返回 Finding 形状 dict 列表（前端审计视图与章节 finding 同构渲染）。
    """
    by_name = {p["name"]: p for p in personas}

    def resolve(name):
        return by_name.get(name)

    def emit(p, chapter, quote, confidence, reason):
        return (p["name"], chapter), {
            "conflict_key": f"persona:{p['name']}:{chapter}",
            "conflict_type": "persona",
            "severity": "hint",  # L2 软冲突一律 hint：不阻塞、不耗修订预算（§8.6）
            "scope": "local",
            "source": "L2",
            "evidence": [{"chapter": chapter, "quote": quote}],
            "confidence": confidence,
            "suggestion": f"角色「{p['name']}」第 {chapter} 章言行与性格基线不符：{reason}",
        }

    return _verify_findings(db, project_id, raw, window,
                            entity_field="character", kind_field="drift_type",
                            kind_value="persona", resolve=resolve, emit=emit)


def sample_bridge_pairs(db: Session, project_id, window: tuple[int, int],
                        *, cap: int = MAX_BRIDGE_PAIRS) -> list[dict]:
    """桥段重复候选抽样（切片 2）：窗口事件 vs 历史事件向量近邻 → 呼应词表预滤除 → cap。

    确定性：窗口事件按 confidence 降序扫（池 cap MAX_BRIDGE_SCAN_EVENTS），逐个向量近邻
    历史（level=event，复用 L1 _REPEAT_* 阈值）；过滤章距 >= _REPEAT_MIN_GAP + 距离 <
    _REPEAT_DIST_THRESHOLD；当前章正文或事件摘要含呼应标记的对直接排除（L1 已豁免，L2
    不重审——词表未覆盖的微妙呼应留给 LLM 判，样例 32/37）。零事件/零对 → 返回 []（调用
    方短路，mirror sample_characters 零提及短路）。返回 [{id: "pair_N", history_event_id,
    history_chapter, history_summary, chapter, summary, dist}]（id 按确定性序赋 pair_1..）。
    """
    events = (db.query(Event)
              .filter(Event.project_id == project_id,
                      Event.source_chapter >= window[0],
                      Event.source_chapter <= window[1])
              .order_by(Event.confidence.desc())
              .limit(MAX_BRIDGE_SCAN_EVENTS)
              .all())
    if not events:
        return []
    contents = {c.chapter_seq: c.content or "" for c in db.query(Chapter).filter(
        Chapter.project_id == project_id,
        Chapter.chapter_seq >= window[0],
        Chapter.chapter_seq <= window[1]).all()}
    pairs: list[dict] = []
    seen: set[tuple] = set()
    for ev in events:
        chapter = ev.source_chapter
        if _has_callback_marker(contents.get(chapter)) or _has_callback_marker(ev.summary):
            continue  # 当前章/摘要自带呼应意图 → L1 已豁免，L2 不重审
        try:
            emb = get_embedder().encode([ev.summary])[0]
            hits = PgvectorStore().search(db, project_id=project_id, level="event",
                                          embedding=emb, top_k=_REPEAT_TOP_K)
        except Exception as exc:  # noqa: BLE001 —— 向量不可用降级（加分项不阻塞，§6.12）
            logger.warning("桥段审计向量近邻失败，跳过（不阻塞）: %s", exc)
            continue
        if not hits:
            continue
        rows = db.execute(select(Event).where(Event.id.in_([sid for sid, _ in hits]))).scalars().all()
        by_id = {e.id: e for e in rows}
        for sid, dist in hits:
            hist = by_id.get(sid)
            if hist is None or hist.source_chapter > chapter - _REPEAT_MIN_GAP:
                continue  # 章距太近：正常情节连续性，非偷懒重复
            if dist >= _REPEAT_DIST_THRESHOLD:
                continue
            pk = (str(sid), chapter)
            if pk in seen:
                continue
            seen.add(pk)
            pairs.append({
                "id": "",
                "history_event_id": str(sid),
                "history_chapter": hist.source_chapter,
                "history_summary": hist.summary,
                "chapter": chapter,
                "summary": ev.summary,
                "dist": dist,
            })
    pairs.sort(key=lambda p: (p["dist"], -p["chapter"]))
    for i, p in enumerate(pairs[:cap], start=1):
        p["id"] = f"pair_{i}"
    return pairs[:cap]


def assemble_bridge_context(db: Session, project_id, window: tuple[int, int],
                            pairs: list[dict]) -> list[dict]:
    """每候选对：当前章正文节选（≤MAX_BRIDGE_CHAPTER_CHARS，逐字供 LLM 引用与守卫核验）+ 章距。"""
    contents = {c.chapter_seq: c.content or "" for c in db.query(Chapter).filter(
        Chapter.project_id == project_id,
        Chapter.chapter_seq >= window[0],
        Chapter.chapter_seq <= window[1]).all()}
    ctx: list[dict] = []
    for p in pairs:
        text = contents.get(p["chapter"]) or ""
        if len(text) > MAX_BRIDGE_CHAPTER_CHARS:
            text = text[:MAX_BRIDGE_CHAPTER_CHARS]
        ctx.append({
            "id": p["id"],
            "history_chapter": p["history_chapter"],
            "history_summary": p["history_summary"],
            "chapter": p["chapter"],
            "summary": p["summary"],
            "gap": p["chapter"] - p["history_chapter"],
            "text": text,
        })
    return ctx


def normalize_and_verify_bridge_findings(db: Session, project_id, raw, pairs: list[dict],
                                         window: tuple[int, int]) -> list[dict]:
    """确定性核验守卫（桥段重复维度，mirror persona 守卫；0 误报不依赖 LLM）。

    逐条丢弃：非 dict / 字段缺失 / verdict != repeat / event 不在候选对集合 / chapter
    不在窗口 / evidence 引文不是该章正文逐字子串 / 置信度 < MIN_CONFIDENCE。强制
    severity=hint scope=local source=L2 conflict_type=style（与 L1 桥段口径一致）；
    (history_event_id, chapter) 去重保最高置信度。返回 Finding 形状 dict 列表。
    """
    by_id = {p["id"]: p for p in pairs}

    def resolve(event):
        return by_id.get(event)

    def emit(pair, chapter, quote, confidence, reason):
        key = (pair["history_event_id"], chapter)
        return key, {
            "conflict_key": f"bridge:{pair['history_event_id']}:{chapter}",
            "conflict_type": "style",
            "severity": "hint",  # L2 软冲突一律 hint：不阻塞、不耗修订预算（§8.6）
            "scope": "local",
            "source": "L2",
            "evidence": [{"chapter": chapter, "quote": quote}],
            "confidence": confidence,
            "suggestion": (f"疑似桥段偷懒重复：第 {chapter} 章事件与第 {pair['history_chapter']} 章"
                           f"「{pair['history_summary'][:30]}」雷同（{reason}）；若为刻意呼应请补"
                           f"意图/差异，否则改写桥段（§8.6）"),
        }

    return _verify_findings(db, project_id, raw, window,
                            entity_field="event", kind_field="verdict",
                            kind_value="repeat", resolve=resolve, emit=emit)


def record_report(db: Session, *, project_id, window: tuple[int, int], findings: list[dict],
                  sampled: list[dict], status: str, error: str | None, source: str,
                  source_batch_task_id: str | None = None,
                  bridge_pairs: int = 0, bridge_findings: int = 0,
                  kind_errors: dict[str, str] | None = None) -> dict:
    """审计报告落库（编排层写库，§6.2）并返回报告 dict。audited_up_to = window_end 推进 marker。

    sampled_characters 列存抽样角色（persona 维度）；summary 追加桥段维度计数（bridge 维度
    跑了才有）与维度失败明细（kind_errors）。error 字段单失败透传原文 / 多失败 k=v 拼接。
    """
    window_start, window_end = window
    summary: dict = {"sampled": len(sampled), "findings": len(findings),
                     "chapters": window_end - window_start + 1}
    if bridge_pairs:
        summary["bridge"] = {"pairs": bridge_pairs, "findings": bridge_findings}
    if kind_errors:
        summary["errors"] = dict(kind_errors)
    db.add(GlobalAuditReport(
        project_id=uuid.UUID(project_id), window_start=window_start, window_end=window_end,
        audited_up_to_chapter=window_end, trigger=source,
        source_batch_task_id=source_batch_task_id, status=status,
        sampled_characters=sampled, findings=findings,
        summary=summary, error=error,
    ))
    db.flush()  # autoflush=False：同会话后续查询需显式可见
    return {
        "window_start": window_start, "window_end": window_end,
        "audited_up_to_chapter": window_end, "status": status,
        "sampled_characters": sampled, "findings": findings, "error": error,
        "summary": summary,
    }


def _join_errors(errors: dict[str, str]) -> str | None:
    """报告 error 字段：单失败透传原文（保 test_llm_failure 断言），多失败 k=v 拼接。"""
    if not errors:
        return None
    if len(errors) == 1:
        return next(iter(errors.values()))
    return "; ".join(f"{k}={v}" for k, v in errors.items())


def _run_kind_llm(db: Session, project_id, task_id: str | None, window: tuple[int, int],
                  messages: list[dict], *, detail: dict) -> tuple[list | None, str | None]:
    """单维度审计 LLM 判定：调用 + 运行记录（成本透明）+ 解析。返回 (raw|None, error|None)。"""
    from aiink.workflow import nodes  # 懒导入防循环（见 run_global_audit docstring）

    resp = make_chain("audit").generate(messages, json_mode=True,
                                        max_tokens=nodes._MAX_TOKENS["audit"])
    nodes.record_run(db, project_id=project_id, task_id=task_id, node="global_audit",
                     role="GlobalAudit", resp=resp, error=resp.error, detail=detail)
    if resp.error:
        return None, resp.error
    try:
        data = nodes._parse_json(resp.content)
    except Exception as exc:  # noqa: BLE001 —— 解析失败同 LLM 失败处理（§6.12）
        return None, f"parse_error: {exc}"
    raw = data.get("findings", []) if isinstance(data, dict) else []
    return raw, None


def run_global_audit(db: Session, project_id, window: tuple[int, int], *,
                     source: str = "manual", source_batch_task_id: str | None = None) -> dict:
    """全局审计编排入口：窗口内抽样跑【人设漂移】+【桥段重复】两个 L2 维度（§8.6）。

    两维度共用同一窗口与同一报告行（一次 marker 推进）。维度"中性"= 无候选（短路零成本）；
    "成功"= 有候选且 LLM+解析通过；"失败"= 有候选但 LLM/解析挂。status = completed 当任一
    维度成功 或 全维度中性（空报告）；failed 当有维度失败且无维度成功；部分成功 → completed，
    失败维度 error 记入 summary["errors"]——非阻塞 + 有界，marker 照常推进（防每批重审毒窗口）。
    函数级懒导入 workflow.nodes/prompts（validation 被 workflow.nodes 模块级引用，模块级
    import 会成环；懒导入破环，mirror reflexion 的运行记录模式）。
    """
    from aiink.workflow import prompts  # 懒导入防循环（见 docstring）

    pid = str(project_id)
    window_start, window_end = window
    findings: list[dict] = []
    errors: dict[str, str] = {}
    bridge_findings: list[dict] = []

    # 维度 A：人设漂移（切片 1）
    sampled = sample_characters(db, pid, window)
    personas = assemble_persona_context(db, pid, window, sampled) if sampled else []
    if personas:
        messages = prompts.global_audit_messages(personas, window)
        raw, err = _run_kind_llm(db, pid, source_batch_task_id, window, messages,
                                 detail={"window": [window_start, window_end],
                                         "sampled": [p["name"] for p in personas]})
        if err:
            errors["persona"] = err
        else:
            findings += normalize_and_verify_findings(db, pid, raw, personas, window)

    # 维度 B：桥段重复「区分呼应 vs 重复」（切片 2，复用框架）
    pairs = sample_bridge_pairs(db, pid, window)
    if pairs:
        pair_ctx = assemble_bridge_context(db, pid, window, pairs)
        messages = prompts.bridge_audit_messages(pair_ctx, window)
        raw, err = _run_kind_llm(db, pid, source_batch_task_id, window, messages,
                                 detail={"window": [window_start, window_end], "kind": "bridge",
                                         "sampled": [p["id"] for p in pairs]})
        if err:
            errors["bridge"] = err
        else:
            bridge_findings = normalize_and_verify_bridge_findings(db, pid, raw, pairs, window)
            findings += bridge_findings

    any_succeeded = (personas and "persona" not in errors) or (pairs and "bridge" not in errors)
    status = "completed" if (any_succeeded or not errors) else "failed"
    if errors:
        logger.warning("全局审计维度失败（不阻塞，marker 已推进）: %s", errors)
    return record_report(db, project_id=pid, window=window, findings=findings,
                         sampled=personas, status=status, error=_join_errors(errors),
                         source=source, source_batch_task_id=source_batch_task_id,
                         bridge_pairs=len(pairs), bridge_findings=len(bridge_findings),
                         kind_errors=errors)
