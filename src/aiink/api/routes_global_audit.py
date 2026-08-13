"""全局审计手动触发（阶段 3 长线治理 · 切片 1：人设漂移抽样 L2）。

同步端点：显式动作，不做 K 门槛——窗口 = 全部未审计章（[上次审计后 +1, 当前最大章]）。
单次 LLM 调用（~30s，同 CorrectMemory 超时 caveat：同步请求请放大客户端超时）。

数据流边界 §6.2：LLM 只产出候选 findings，落库经编排层 record_report；审计失败
（LLM/解析）返回 502 且已写 status=failed 报告行（非阻塞，marker 已推进，§8.6）。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from aiink.db import tenant_session
from aiink.validation import global_audit as ga

router = APIRouter(prefix="/internal/v1", tags=["global-audit"])


def _project_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"项目 id 非法: {raw}") from exc


@router.post("/projects/{project_id}/global-audit")
def trigger_global_audit(project_id: str) -> dict:
    """手动触发全局审计：全部未审计章窗口（不做 K 门槛），返回审计报告。

    无已写章节 → 400；LLM/解析失败 → 502（报告已落库为 failed 并推进 marker）。
    """
    pid = _project_id(project_id)
    with tenant_session(project_id) as db:
        end = ga.current_max_chapter(db, str(pid))
        if end == 0:
            raise HTTPException(status_code=400, detail="该书尚无已写章节，无法审计")
        start = ga.last_audited_up_to(db, str(pid)) + 1
        report = ga.run_global_audit(db, str(pid), (start, end), source="manual")
    if report.get("status") == "failed":
        raise HTTPException(status_code=502, detail=f"全局审计失败: {report.get('error')}")
    return report
