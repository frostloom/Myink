"""Python API 装配（FastAPI，127.0.0.1:8100，内部服务）。

启动：`myink-api` 或 `python -m myink.api.main`（pyproject scripts）。
"""

from __future__ import annotations

import logging
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from myink.api.auth import current_user, require_owner
from myink.api.auth import router as auth_router
from myink.api.ratelimit import ApiError, GlobalRateLimit
from myink.api.routes_admin import router as admin_router
from myink.api.routes_book import router as book_router
from myink.api.routes_candidates import router as candidates_router
from myink.api.routes_chapters import router as chapters_router
from myink.api.routes_environment import router as environment_router
from myink.api.routes_genre import router as genre_router
from myink.api.routes_global_audit import router as global_audit_router
from myink.api.routes_lessons import router as lessons_router
from myink.api.routes_rankings import router as rankings_router
from myink.api.routes_settings import router as settings_router
from myink.api.routes_style import router as style_router
from myink.api.routes_tasks import router as tasks_router
from myink.api.schemas import ChapterDetailOut, ChapterMetaOut, ProjectOut
from myink.config import settings
from myink.db import new_session, tenant_session
from myink.models import Chapter, Project
from myink.worker.redis_client import get_redis

logger = logging.getLogger(__name__)

app = FastAPI(title="Myink 内部 API", docs_url=None, redoc_url=None)


@app.middleware("http")
async def admin_no_store(request, call_next):
    if request.url.path == "/api/v1/admin" or request.url.path.startswith("/api/v1/admin/"):
        try:
            response = await call_next(request)
        except Exception:
            from fastapi.responses import JSONResponse
            response = JSONResponse({"detail": "ADMIN_REPORT_UNAVAILABLE"}, status_code=503)
        response.headers["Cache-Control"] = "no-store"
        return response
    return await call_next(request)

# 粗粒度限流（等价网关的令牌桶）。原先这里挂着 allow_origins=["*"] 的 CORSMiddleware：
# 边缘交给 Caddy 之后前端与 API 同源（本地开发走 Vite 代理也是同源），没有任何跨源调用方，
# 而 allow_headers=["*"] 等于允许任何站点朝这里发 Authorization——严格劣于没有。删掉。
app.add_middleware(GlobalRateLimit)


@app.exception_handler(ApiError)
async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
    """`{"error": CODE}` 信封——前端 GATE_CODES 认这个键，不认 FastAPI 默认的 detail。"""
    return JSONResponse({"error": exc.code}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(StarletteHTTPException)
async def _aligned_http_error(request: Request, exc: StarletteHTTPException):
    """把「路由没匹配上」这一种 404 归一成 `{"error": "not_found"}`。

    只改这一种：显式抛出的 404 都带着自己的 detail，原样透传（走 FastAPI 默认处理器）。
    这样 `/api/v1/不存在的路径` 给 API 客户端的是 JSON，而不是 Caddy 的 SPA 回退。
    """
    if exc.status_code == 404 and exc.detail == "Not Found":
        return JSONResponse({"error": "not_found"}, status_code=404)
    return await http_exception_handler(request, exc)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(book_router)
app.include_router(tasks_router)
app.include_router(candidates_router)
app.include_router(chapters_router)
app.include_router(lessons_router)
app.include_router(style_router)
app.include_router(settings_router)
app.include_router(environment_router)
app.include_router(genre_router)
app.include_router(global_audit_router)
app.include_router(rankings_router)


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
    # worker 心跳：queue:heartbeat:* 有任一条即视为存活（等价网关 Ready 的 worker 项）。
    # 用 scan_iter 而不是 KEYS——KEYS 是全系统唯一的 O(N) 阻塞命令，没理由把它一起抄过来。
    try:
        alive = next(get_redis().scan_iter("queue:heartbeat:*", count=100), None)
        checks["worker"] = "ok" if alive is not None else "fail: 无 worker 心跳"
    except Exception as exc:
        checks["worker"] = f"fail: {exc}"
    ok = all(v == "ok" for v in checks.values())
    if not ok:
        return JSONResponse({"status": "degraded", "checks": checks}, status_code=503)
    return {"status": "ok", "checks": checks}


# ---- 项目/章节读（RLS 保护，tenant_session 带租户上下文）----


@app.get("/api/v1/projects", response_model=list[ProjectOut])
def list_projects(user_id: str | None = Depends(current_user)) -> list[dict]:
    """项目列表（根表无 RLS，应用层按身份过滤：只返回自己的书，§14.1 ③）。

    identity 缺失/非法 → 空列表（fail closed，不返回他人作品）。
    """
    if not user_id:
        return []  # 身份缺失 → fail closed
    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        return []  # 身份非法 → fail closed
    with new_session() as db:
        rows = db.query(Project).filter(Project.user_id == uid).all()
        return [
            {
                "id": str(p.id),
                "title": p.title,
                "genre": p.genre,
                "current_chapter": p.current_chapter,
                "target_words": p.target_words,
                "creation_status": p.creation_status,
            }
            for p in rows
        ]


@app.get("/api/v1/projects/{project_id}/chapters",
         dependencies=[Depends(require_owner)], response_model=list[ChapterMetaOut])
def list_chapters(project_id: str) -> list[dict]:
    """章节列表（RLS：tenant_session 过滤，只返回本项目 + 归属断言双保险）。

    word_count = 正文字符数（len 口径，与 L1 chapter_length_check §6.9 同源——
    中文按字符计，含标点），供章节列表/正文侧展示每章字数。
    """
    with tenant_session(project_id) as db:
        rows = db.query(Chapter).order_by(Chapter.chapter_seq).all()
        return [
            {
                "id": str(c.id),
                "chapter_seq": c.chapter_seq,
                "title": c.title,
                "status": c.status,
                "word_count": len(c.content or ""),
                "summary": c.summary,
            }
            for c in rows
        ]


@app.get("/api/v1/projects/{project_id}/chapters/{chapter_id}",
         dependencies=[Depends(require_owner)], response_model=ChapterDetailOut)
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
            "version": chapter.version or 1,
            "summary": chapter.summary,
        }


def main() -> None:
    """`myink-api` 入口（uvicorn 127.0.0.1:8100，仅内部监听）。"""
    import uvicorn

    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level="info")


if __name__ == "__main__":
    main()
