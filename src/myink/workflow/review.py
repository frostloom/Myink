"""人工评审恢复：拒绝正文设定后走完整修订循环，保留决策证据。"""
from __future__ import annotations
import json
import uuid
from myink.db import tenant_session
from myink.models import MemoryCandidate
from myink.memory.candidate_identity import same_proposal


def rejection_text(rows) -> str:
    return "作者已否定以下设定；修订正文及其因果影响，禁止换一种说法重新引入。\n" + "\n".join(
        f"- {r.kind}: {json.dumps(r.payload, ensure_ascii=False)}；理由：{(r.review or {}).get('reason') or '不接受此设定'}"
        for r in rows)


def resolve_review(graph, values: dict, *, task_id: str) -> dict:
    from myink.workflow import nodes
    from myink.workflow.chapter_graph import build_chapter_graph
    pid, seq = values["project_id"], values["chapter_seq"]
    with tenant_session(pid) as db:
        pool = db.query(MemoryCandidate).filter(
            MemoryCandidate.project_id == uuid.UUID(pid), MemoryCandidate.source_chapter == seq).all()
        rejected = [r for r in pool if r.status == "rejected" and
                    (r.review or {}).get("mode") == "revise" and not (r.review or {}).get("applied")]
        if not rejected:
            if any(r.status == "pending" for r in pool):
                return {**values, "needs_review": True, "error": None}
            result = nodes.finalize_awaiting_review(values, task_id=task_id)
            return {**values, **result, "task_id": task_id}
        from myink.guest_quota import require_review_admission
        require_review_admission(db, task_id, [row.id for row in rejected])
        instruction = rejection_text(rejected)
        ids = [r.id for r in rejected]
        # 旧稿尚未处理的候选失去依据；保留历史，不让用户逐条拒绝过期条目。
        for row in pool:
            if row.status == "pending":
                row.status = "rejected"
                row.review = {"superseded": True, "reason": "原稿已进入人工修订"}
    ctx = dict(values.get("context") or {})
    ctx["short_context"] = [*(ctx.get("short_context") or []),
                            {"kind": "user_instruction", "text": instruction}]
    state = {**values, "task_id": task_id, "context": ctx, "error": None,
             "needs_review": False, "persisted": False, "rewrite": True, "review_revision": True,
             "revision_count": 0, "replan_count": 0, "audit_verdict": None,
             "patch_count": 0, "revise_mode": "full", "patch_applied": 0,
             "patch_skipped": 0, "patch_rejected_reason": None,
             "unresolved": [{"conflict_key": "author:review", "severity": "major",
                  "conflict_type": "fact", "evidence": [], "suggestion": instruction}]}
    revision = build_chapter_graph(checkpointer=graph.checkpointer, entry="revise")
    result = revision.invoke(state, config={"configurable": {"thread_id": task_id}, "recursion_limit": 64})
    if not result.get("error"):
        with tenant_session(pid) as db:
            for cid in ids:
                row = db.get(MemoryCandidate, cid)
                if row:
                    row.review = {**(row.review or {}), "applied": True}
    return result


def rejected_proposal(db, pid: str, seq: int, cand: dict):
    rows = db.query(MemoryCandidate).filter(
        MemoryCandidate.project_id == uuid.UUID(pid), MemoryCandidate.status == "rejected",
        MemoryCandidate.kind == cand["kind"], MemoryCandidate.source_chapter <= seq).all()
    return next((r for r in rows if not (r.review or {}).get("superseded") and
                 (r.source_chapter == seq or r.kind == "character_card") and
                 same_proposal(r.kind, r.payload, cand.get("payload") or {})), None)
