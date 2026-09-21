"""HTTP 响应契约套件（阶段 5 契约测试形式化）。

单一事实源 = FastAPI `app.openapi()`：全部公开消费端点（前端 api.ts 方法逐一覆盖，
含任务历史列表 tasks、写作经验 lessons×3、correct-memory、级联删章）挂 response_model
（src/myink/api/schemas.py）后，openapi 响应 schema有实质内容；`myink contract export`
导出到 spec/api-openapi.json 提交入库，本套件与 CI 的 `git diff --exit-code` 构成双闸
——后端改 response_model 未重新导出即红。

独立运行：只 import app 调 app.openapi()，不触 DB、不需要 myink init。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from myink.api.main import app

# 公开消费端点（前端 api.ts 方法逐一覆盖：生成走网关入队不在此列）。path 用 FastAPI
# 模板形式（{project_id}）。
PUBLIC_ENDPOINTS: list[tuple[str, str]] = [
    ("POST", "/api/v1/auth/token"),
    ("POST", "/api/v1/auth/register"),
    ("GET", "/api/v1/auth/session"),
    ("POST", "/api/v1/auth/password"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/projects/{project_id}/access"),
    ("GET", "/api/v1/tasks/{task_id}/access"),
    ("GET", "/api/v1/projects"),
    ("POST", "/api/v1/projects"),
    ("GET", "/api/v1/projects/{project_id}/creation"),
    ("PUT", "/api/v1/projects/{project_id}"),
    ("DELETE", "/api/v1/projects/{project_id}"),
    ("GET", "/api/v1/projects/{project_id}/chapters"),
    ("GET", "/api/v1/projects/{project_id}/chapters/{chapter_id}"),
    ("PUT", "/api/v1/projects/{project_id}/chapters/{chapter_id}/content"),
    ("GET", "/api/v1/projects/{project_id}/chapters/{chapter_id}/versions"),
    ("POST", "/api/v1/projects/{project_id}/chapters/{chapter_id}/versions/{version}/restore"),
    ("POST", "/api/v1/projects/{project_id}/chapters/{chapter_id}/correct-memory"),
    ("DELETE", "/api/v1/projects/{project_id}/chapters/{chapter_id}"),
    ("GET", "/api/v1/tasks/{task_id}"),
    ("POST", "/api/v1/tasks/{task_id}/pause"),
    ("POST", "/api/v1/tasks/{task_id}/resume"),
    ("POST", "/api/v1/tasks/{task_id}/cancel"),
    ("GET", "/api/v1/projects/{project_id}/tasks"),
    ("GET", "/api/v1/projects/{project_id}/candidates"),
    ("POST", "/api/v1/projects/{project_id}/candidates/{candidate_id}/confirm"),
    ("POST", "/api/v1/projects/{project_id}/candidates/{candidate_id}/reject"),
    ("GET", "/api/v1/projects/{project_id}/lessons"),
    ("POST", "/api/v1/projects/{project_id}/lessons/{lesson_id}/confirm"),
    ("POST", "/api/v1/projects/{project_id}/lessons/{lesson_id}/reject"),
    ("GET", "/api/v1/skill-presets"),
    ("GET", "/api/v1/genre-packs"),
    ("PUT", "/api/v1/projects/{project_id}/genre-pack"),
    ("POST", "/api/v1/projects/{project_id}/genre-pack/restore"),
    ("POST", "/api/v1/projects/{project_id}/style-samples"),
    ("PUT", "/api/v1/projects/{project_id}/style-profile"),
    ("POST", "/api/v1/projects/{project_id}/setup-draft"),
    ("PUT", "/api/v1/projects/{project_id}/setup"),
    # 整书大纲（§11 建书 ③：草稿 / 确认落库 / 读取）
    ("POST", "/api/v1/projects/{project_id}/outline-draft"),
    ("PUT", "/api/v1/projects/{project_id}/outline"),
    ("GET", "/api/v1/projects/{project_id}/outline"),
    ("GET", "/api/v1/projects/{project_id}/world"),
    ("GET", "/api/v1/projects/{project_id}/characters"),
    ("GET", "/api/v1/projects/{project_id}/characters/{character_id}/state-history"),
    ("GET", "/api/v1/projects/{project_id}/events"),
    ("GET", "/api/v1/projects/{project_id}/entities"),
    ("GET", "/api/v1/projects/{project_id}/graph"),
    ("GET", "/api/v1/projects/{project_id}/foreshadows"),
    ("GET", "/api/v1/rankings"),
    ("GET", "/api/v1/projects/{project_id}/settings"),
    ("PUT", "/api/v1/projects/{project_id}/settings"),
    ("GET", "/api/v1/environment"),
    ("PUT", "/api/v1/environment"),
    ("POST", "/api/v1/projects/{project_id}/global-audit"),
    ("GET", "/api/v1/projects/{project_id}/global-audit"),
    ("GET", "/api/v1/projects/{project_id}/global-audit/{report_id}"),
]

# 探针（无业务消费方，不要求响应契约；Go 路径闸允许清单）
ALLOWLIST = {("GET", "/healthz"), ("GET", "/readyz")}

SPEC_PATH = pathlib.Path(__file__).resolve().parents[1] / "spec" / "api-openapi.json"


def _spec() -> dict[str, Any]:
    return app.openapi()


def _resolve(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        schema = components["schemas"][schema["$ref"].split("/")[-1]]
    return schema


def _schema_has_fields(schema: dict[str, Any], components: dict[str, Any]) -> bool:
    """契约有实质内容：object 有 properties，或 array 的 items 有 properties。

    未挂 response_model 时 FastAPI 对 `-> list[dict]` 只给 {"type":"array","items":{}}——
    items 空即无契约。
    """
    schema = _resolve(schema, components)
    if schema.get("properties"):
        return True
    items = schema.get("items")
    if items:
        return bool(_resolve(items, components).get("properties"))
    return False


def _response_schema(openapi: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    responses = openapi["paths"][path][method.lower()]["responses"]
    success = [response for code, response in responses.items() if code.startswith("2")]
    assert len(success) == 1, f"expected one success response for {method} {path}"
    return success[0]["content"]["application/json"]["schema"]


@pytest.mark.parametrize("method,path", PUBLIC_ENDPOINTS)
def test_covered_endpoint_has_response_schema(method: str, path: str) -> None:
    """每条公开端点 openapi 里必须有该 path + method + 非空 200 响应 schema。"""
    openapi = _spec()
    components = openapi["components"]
    assert path in openapi["paths"], f"契约缺路径: {method} {path}"
    assert method.lower() in openapi["paths"][path], f"契约缺 method: {method} {path}"
    schema = _response_schema(openapi, method, path)
    assert _schema_has_fields(schema, components), f"响应 schema 为空（缺 response_model）: {method} {path}"


def test_no_uncovered_business_route() -> None:
    """反向闸：除探针外所有业务路由必须有响应契约（未来新路由不加 response_model 即红）。"""
    openapi = _spec()
    components = openapi["components"]
    uncovered = []
    for path, methods in openapi["paths"].items():
        for method in methods:
            if (method.upper(), path) in ALLOWLIST:
                continue
            schema = _response_schema(openapi, method, path)
            if not _schema_has_fields(schema, components):
                uncovered.append(f"{method.upper()} {path}")
    assert not uncovered, f"以下业务路由无响应契约（缺 response_model）: {uncovered}"


def test_openapi_matches_committed_spec() -> None:
    """diff 闸的测试侧：提交的 spec/api-openapi.json 必须与 app 当前 openapi 一致。

    改了 response_model 但没 `myink contract export` 重新导出 → 本测试红
    （CI 另有 git diff --exit-code 双重拦截）。
    """
    if not SPEC_PATH.exists():
        pytest.fail(f"契约文件缺失: {SPEC_PATH}（先运行 myink contract export）")
    committed = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert committed == _spec(), (
        "spec/api-openapi.json 与当前 app.openapi() 不一致——改了响应契约后需重新 "
        "`myink contract export` 并提交"
    )
