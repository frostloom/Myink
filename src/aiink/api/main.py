"""Python API 装配（FastAPI，127.0.0.1:8100，内部服务）。

启动：`aiink-api` 或 `python -m aiink.api.main`（pyproject scripts）。
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from aiink.api.routes_candidates import router as candidates_router
from aiink.api.routes_lessons import router as lessons_router
from aiink.api.routes_tasks import router as tasks_router
from aiink.config import settings
from aiink.db import new_session, tenant_session
from aiink.models import Chapter, Project
from aiink.worker.redis_client import get_redis

logger = logging.getLogger(__name__)

app = FastAPI(title="Ai Ink 内部 API", docs_url=None, redoc_url=None)

# 仅网关访问，但 MVP 开发方便看错误；生产收紧为内网白名单（阶段 5）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)
app.include_router(candidates_router)
app.include_router(lessons_router)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict:
    checks = {}
    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"fail: {exc}"
    try:
        from sqlalchemy import text

        with new_session() as db:
            db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"fail: {exc}"
    ok = all(v == "ok" for v in checks.values())
    if not ok:
        from fastapi.responses import JSONResponse

        return JSONResponse({"status": "degraded", "checks": checks}, status_code=503)
    return {"status": "ok", "checks": checks}


# ---- 项目/章节读（RLS 保护，tenant_session 带租户上下文）----


@app.get("/internal/v1/projects")
def list_projects() -> list[dict]:
    """项目列表（根表无 RLS，普通连接）。"""
    with new_session() as db:
        rows = db.query(Project).all()
        return [
            {"id": str(p.id), "title": p.title, "genre": p.genre, "current_chapter": p.current_chapter}
            for p in rows
        ]


@app.get("/internal/v1/projects/{project_id}/chapters")
def list_chapters(project_id: str) -> list[dict]:
    """章节列表（RLS：tenant_session 过滤，只返回本项目）。"""
    with tenant_session(project_id) as db:
        rows = db.query(Chapter).order_by(Chapter.chapter_seq).all()
        return [
            {
                "id": str(c.id),
                "chapter_seq": c.chapter_seq,
                "title": c.title,
                "status": c.status,
            }
            for c in rows
        ]


@app.get("/internal/v1/projects/{project_id}/chapters/{chapter_id}")
def get_chapter(project_id: str, chapter_id: str) -> dict:
    with tenant_session(project_id) as db:
        chapter = db.get(Chapter, uuid.UUID(chapter_id))
        if chapter is None:
            raise HTTPException(status_code=404, detail="章节不存在")
        return {
            "id": str(chapter.id),
            "chapter_seq": chapter.chapter_seq,
            "title": chapter.title,
            "status": chapter.status,
            "content": chapter.content,
            "summary": chapter.summary,
        }


def main() -> None:
    """`aiink-api` 入口（uvicorn 127.0.0.1:8100，仅内部监听）。"""
    import uvicorn

    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level="info")


if __name__ == "__main__":
    main()
