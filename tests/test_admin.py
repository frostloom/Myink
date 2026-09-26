"""Admin reads cross tenants only after a fresh bearer role check."""
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from myink.api import auth
from myink.api.main import app
from myink.config import settings
from myink.db import get_admin_engine, new_session, tenant_session
from myink.models import AgentRun, Chapter, Fact, Invitation, Project, ProjectSettings, Task, User

client = TestClient(app, raise_server_exceptions=False)
PREFIX = "/api/v1/admin"


@pytest.fixture
def admin_data(monkeypatch):
    monkeypatch.setattr(auth, "settings", replace(settings, jwt_secret="admin-test-secret-at-least-32-characters"))
    with new_session() as db:
        users = [User(username=f"adm-test-{uuid.uuid4().hex}", role=role,
                      environment={"api_key": "ENV-DO-NOT-EXPOSE"}) for role in ("admin", "user")]
        db.add_all(users)
        db.flush()
        books = [Project(user_id=u.id, title=f"book-{u.id}") for u in users]
        db.add_all(books)
        db.flush()
        task = Task(project_id=books[1].id, task_type="batch_generate", status="paused",
                    payload={"password": "PAYLOAD-SECRET", "size": 2}, error="Bearer ERROR-SECRET")
        db.add(task)
        db.flush()
        runs = [AgentRun(project_id=pid, task_id=tid, node="write", input_tokens=n,
                         output_tokens=2*n, cost_est=n/10, duration_ms=n*100,
                         detail={"api_key": "RUN-SECRET", "output": "story"})
                for pid, tid, n in [(books[1].id, str(task.id), 3),
                                    (books[1].id, f"{task.id}:ch1", 5),
                                    (books[1].id, f"{task.id}-wrong", 100),
                                    (books[0].id, str(task.id), 1000),
                                    (books[1].id, None, 7)]]
        db.add_all(runs)
        db.commit()
    chapters = []
    for book in books:
        with tenant_session(book.id) as db:
            chapter = Chapter(project_id=book.id, chapter_seq=1, content="正文abc", summary="summary")
            db.add(chapter)
            db.add(ProjectSettings(project_id=book.id, world_rules={"setting": "moon", "secret": "WORLD-SECRET"},
                                   model_routes={"api_key": "ROUTE-SECRET"}))
            db.flush()
            chapters.append(chapter)
    try:
        yield users, books, task, runs, chapters
    finally:
        with new_session() as db:
            db.query(AgentRun).filter(AgentRun.project_id.in_([b.id for b in books])).delete()
            # Audit retains actors after account deletion, like production.
            db.query(User).filter(User.id.in_([u.id for u in users])).delete()
            db.commit()


def bearer(user):
    return {"Authorization": "Bearer " + auth.create_access_token(user.id, auth_version=user.auth_version)}


@pytest.mark.parametrize("identity,status", [("missing",401), ("forged",401), ("user",403), ("admin",200)])
def test_admin_authority_and_no_store(admin_data, identity, status):
    users, *_ = admin_data
    headers = {} if identity == "missing" else {"X-Myink-User": str(users[0].id)} if identity == "forged" else bearer(users[identity == "user"])
    response = client.get(PREFIX + "/overview", headers=headers)
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"


def test_admin_reads_cross_user_paginated_metadata_and_exact_batch_sums(admin_data):
    users, books, task, runs, chapters = admin_data
    headers = bearer(users[0])
    response = client.get(PREFIX+f"/tasks?user_id={users[1].id}&limit=1", headers=headers)
    assert response.status_code == 200, response.text
    page = response.json()
    assert (page["total"], page["limit"], page["offset"]) == (1, 1, 0)
    row = page["items"][0]
    assert row["metrics"] == {"run_count": 2, "input_tokens": 8, "output_tokens":16, "cost_est":0.8, "duration_ms":800}
    assert "payload" not in row
    detail = client.get(PREFIX+f"/tasks/{task.id}", headers=headers).json()
    assert detail["payload"]["data"]["size"] == 2
    assert detail["elapsed_includes_waits"] is True
    assert "PAYLOAD-SECRET" not in str(detail) and "ERROR-SECRET" not in str(detail)
    run_page = client.get(PREFIX+f"/tasks/{task.id}/runs?limit=1&offset=1", headers=headers).json()
    assert run_page["total"] == 2 and len(run_page["items"]) == 1
    assert "detail" not in run_page["items"][0]
    all_runs = client.get(PREFIX+f"/runs?project_id={books[1].id}", headers=headers).json()
    assert all_runs["total"] == 4 and any(r["task_id"] is None for r in all_runs["items"])
    projects = client.get(PREFIX+f"/projects?user_id={users[1].id}", headers=headers).json()
    assert projects["total"] == 1 and projects["items"][0]["word_count"] == 5
    chapter_page = client.get(PREFIX+f"/projects/{books[1].id}/chapters", headers=headers).json()
    assert chapter_page["total"] == 1 and "content" not in chapter_page["items"][0]
    chapter = client.get(PREFIX+f"/projects/{books[1].id}/chapters/{chapters[1].id}", headers=headers)
    assert chapter.json()["content"] == "正文abc"
    wrong = client.get(PREFIX+f"/projects/{books[0].id}/chapters/{chapters[1].id}", headers=headers)
    assert wrong.status_code == 404 and wrong.headers["cache-control"] == "no-store"
    context = client.get(PREFIX+f"/projects/{books[1].id}/context", headers=headers)
    assert context.status_code == 200 and "moon" in context.text
    assert all(s not in context.text for s in ("WORLD-SECRET", "ROUTE-SECRET", "model_routes", "environment"))
    run_detail = client.get(PREFIX+f"/runs/{runs[0].id}", headers=headers).json()
    assert "RUN-SECRET" not in str(run_detail) and run_detail["prompt_missing"] is True
    safe_users = client.get(PREFIX+f"/users?q={users[1].username}", headers=headers).json()
    assert safe_users["total"] == 1 and "ENV-DO-NOT-EXPOSE" not in str(safe_users)
    logs = client.get(PREFIX+"/access-logs?limit=100", headers=headers).json()
    assert any(r["actor_id"] == str(users[0].id) and r["action"] == "admin.task" for r in logs["items"])


def test_admin_project_detail_matches_its_list_row_and_404s_on_unknown(admin_data):
    users, books, *_ = admin_data
    headers = bearer(users[0])
    listed = client.get(PREFIX+f"/projects?user_id={users[1].id}", headers=headers).json()["items"][0]
    detail = client.get(PREFIX+f"/projects/{books[1].id}", headers=headers)
    assert detail.status_code == 200, detail.text
    # 详情页直接按 id 取数，字段必须与列表行一致，否则跳页后数字会变。
    assert detail.json() == listed
    missing = client.get(PREFIX+f"/projects/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404 and missing.headers["cache-control"] == "no-store"


def test_admin_revocation_and_validation_errors(admin_data):
    users, *_ = admin_data
    headers = bearer(users[0])
    for query in ("limit=101", "offset=-1"):
        response = client.get(PREFIX+"/users?"+query, headers=headers)
        assert response.status_code == 422 and response.headers["cache-control"] == "no-store"
    with new_session() as db:
        db.get(User, users[0].id).role = "user"
        db.commit()
    assert client.get(PREFIX+"/overview", headers=headers).status_code == 403
    with new_session() as db:
        user = db.get(User, users[0].id)
        user.role = "admin"
        user.auth_version += 1
        db.commit()
    assert client.get(PREFIX+"/overview", headers=headers).status_code == 401


def test_admin_read_connection_rejects_writes_and_audit_fails_closed(admin_data, monkeypatch):
    from myink.api import routes_admin
    with routes_admin.admin_read_session() as db:
        assert db.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        with pytest.raises(Exception, match="read-only"):
            db.execute(text("UPDATE users SET tier = tier WHERE false"))
    def unavailable(*args, **kwargs):
        raise RuntimeError("Bearer DO-NOT-EXPOSE")
    monkeypatch.setattr(routes_admin, "write_access_log", unavailable)
    response = client.get(PREFIX+"/overview", headers=bearer(admin_data[0][0]))
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
    assert "DO-NOT-EXPOSE" not in response.text


def test_context_limits_legacy_missing_and_owner_aggregates(admin_data):
    users, books, task, runs, _ = admin_data
    headers = bearer(users[0])
    with tenant_session(books[1].id) as db:
        db.add_all([Fact(project_id=books[1].id, content=f"fact-{i}", source_chapter=1) for i in range(3)])
    with new_session() as db:
        db.get(AgentRun, runs[4].id).detail = None
        db.commit()
    data = client.get(PREFIX+f"/projects/{books[1].id}/context?limit=2", headers=headers).json()
    assert data["facts"]["total"] == 3 and len(data["facts"]["items"]) == 2 and data["facts"]["truncated"]
    row = client.get(PREFIX+f"/users?q={users[1].username}", headers=headers).json()["items"][0]
    assert (row["project_count"], row["chapter_count"], row["word_count"], row["task_count"]) == (1, 1, 5, 1)
    assert row["metrics"]["run_count"] == 4 and row["metrics"]["input_tokens"] == 115
    legacy = client.get(PREFIX+f"/runs/{runs[4].id}", headers=headers).json()
    assert legacy["detail_missing"] and legacy["prompt_missing"] and legacy["detail"]["data"] is None
    filtered = client.get(PREFIX+f"/tasks?user_id={users[1].id}&status=failed", headers=headers).json()
    assert filtered["total"] == 0 and filtered["items"] == []
    empty = client.get(PREFIX+f"/projects?user_id={users[1].id}&offset=1", headers=headers).json()
    assert empty["total"] == 1 and empty["items"] == []


def test_actual_registration_and_login_accept_exactly_eight_characters(admin_data):
    from myink.invitations import create_invitation
    username = f"eight-{uuid.uuid4().hex}"
    with new_session() as db:
        invitation, code = create_invitation(db, expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
        db.commit()
    try:
        response = client.post("/api/v1/auth/register", json={"username":username, "password":"abcd1234", "invitation_code":code})
        assert response.status_code == 201, response.text
        login = client.post("/api/v1/auth/token", json={"username":username, "password":"abcd1234"})
        assert login.status_code == 200, login.text
        assert login.json()["role"] == "user"
    finally:
        with new_session() as db:
            db.query(User).filter(User.username == username).delete()
            db.query(Invitation).filter(Invitation.id == invitation.id).delete()
            db.commit()


def test_admin_run_read_bounds_and_scrubs_lossless_business_detail(admin_data):
    import json
    from myink.admin_observability import capture_detail
    users, _, _, runs, _ = admin_data
    original = {"password": "LEGACY-CONTROL-SECRET", "goals": ["scene " * 500] * 100}
    stored = capture_detail({"plan": original, "plan_attempt": 7, "writing_mode": "manual",
                             "messages": [{"role": "user", "content": "prompt " * 5000}] * 100})
    assert stored["plan"] == original
    with new_session() as db:
        db.get(AgentRun, runs[0].id).detail = stored
        db.commit()
    response = client.get(PREFIX+f"/runs/{runs[0].id}", headers=bearer(users[0]))
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    data = response.json()["detail"]
    assert data["truncated"] and "LEGACY-CONTROL-SECRET" not in response.text
    assert len(json.dumps(data).encode()) <= 65536


def test_user_cost_includes_account_level_runs(admin_data, temp_user, temp_project):
    """Review Focus 5：没有书的调用（建书对话）也要算进这个人的花费，且点得进去看明细。"""
    users, *_ = admin_data
    with new_session() as db:
        db.execute(text("UPDATE projects SET user_id = :uid WHERE id = :pid"),
                   {"uid": temp_user, "pid": temp_project})
        db.add(AgentRun(user_id=uuid.UUID(temp_user), node="short_creation", role="Planner",
                        model_id="m", input_tokens=10, output_tokens=20, cost_est=7.5))
        db.commit()

    # 管理端点要的是 **admin 的令牌**：`temp_user` 只是被查的对象，不是查询者。
    # 不加这个头，四条请求全是 401，测试会以「哪都没坏」的样子红掉。
    headers = bearer(users[0])

    rows = client.get(PREFIX + "/users", params={"q": temp_user}, headers=headers).json()["items"]
    assert rows[0]["metrics"]["cost_est"] >= 7.5

    runs = client.get(PREFIX + "/runs", params={"user_id": temp_user}, headers=headers).json()
    assert any(run["node"] == "short_creation" for run in runs["items"])
    account_run = next(run for run in runs["items"] if run["node"] == "short_creation")
    assert account_run["project_id"] is None
    assert account_run["project_title"] is None
    assert account_run["username"] is not None       # 账号名兜底填上，列表不会开天窗

    detail = client.get(PREFIX + f"/runs/{account_run['id']}", headers=headers)
    assert detail.status_code == 200                 # 详情页也要能直接打开


def test_admin_runs_list_excludes_orphan_rows(admin_data):
    """孤儿 run（project_id 指向已不存在的书、user_id 为 NULL）不能被外连接带进响应。

    有效归属 coalesce(Project.user_id, AgentRun.user_id) 为空，而 AdminRun.user_id 非空 →
    ResponseValidationError（admin 中间件再转成 503 ADMIN_REPORT_UNAVAILABLE）。
    列表要跳过它（200），孤儿详情报 404（与旧内连接一致）。
    """
    users, *_ = admin_data
    with new_session() as db:
        orphan = AgentRun(project_id=uuid.uuid4(), user_id=None, node="orphan",
                          input_tokens=1, output_tokens=1, cost_est=0.1)
        db.add(orphan)
        db.commit()
        orphan_id = orphan.id
    try:
        headers = bearer(users[0])
        response = client.get(PREFIX + "/runs", headers=headers)
        assert response.status_code == 200, response.text
        assert all(run["node"] != "orphan" for run in response.json()["items"])
        assert client.get(PREFIX + f"/runs/{orphan_id}", headers=headers).status_code == 404
    finally:
        with new_session() as db:
            db.query(AgentRun).filter(AgentRun.id == orphan_id).delete()
            db.commit()


def test_admin_user_detail_returns_one_user(admin_data):
    users, *_ = admin_data
    response = client.get(PREFIX + f"/users/{users[1].id}", headers=bearer(users[0]))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(users[1].id)
    assert body["username"] == users[1].username
    assert body["role"] == "user"
    assert "metrics" in body


def test_admin_user_detail_matches_the_list_row(admin_data):
    """详情页与列表行必须逐字段相同——两边共用一条 statement，抽函数时列/别名一动就分叉。"""
    users, *_ = admin_data
    headers = bearer(users[0])
    listed = client.get(PREFIX + "/users", params={"q": users[1].username},
                        headers=headers).json()["items"][0]
    detail = client.get(PREFIX + f"/users/{users[1].id}", headers=headers).json()
    assert detail == listed


def test_admin_user_detail_404s_on_an_unknown_id(admin_data):
    users, *_ = admin_data
    response = client.get(PREFIX + f"/users/{uuid.uuid4()}", headers=bearer(users[0]))
    assert response.status_code == 404
    assert response.json()["detail"] == "NOT_FOUND"


def test_admin_user_detail_404s_on_a_malformed_id(admin_data):
    """地址栏手改 / 旧书签会把 id 写成随便一串。

    路径参数若收 uuid 类型，FastAPI 会先把它挡成 422「请求参数不合法」，而面板要的是
    「没这个人」——所以路由收 str 自己解析，格式不对照样 404。
    """
    users, *_ = admin_data
    response = client.get(PREFIX + "/users/not-a-uuid", headers=bearer(users[0]))
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "NOT_FOUND"


def test_overview_metrics_agree_with_the_runs_list(admin_data):
    """M-9：全局 metrics 与「全部运行」列表同口径——列表能看到多少行，全局就计多少。

    `agent_runs.project_id` 无 FK，删账号会留下「指向已删的书 + user_id 也没了」的行。
    这类行在运行列表里被 `owner IS NOT NULL` 挡掉（不然 AdminRun.user_id 非空字段会炸成
    503），全局却一直算着它们，于是两块页面的花费对不上。
    """
    users, *_ = admin_data
    headers = bearer(users[0])
    overview = client.get(PREFIX + "/overview", headers=headers).json()["metrics"]
    listed = client.get(PREFIX + "/runs", params={"limit": 1}, headers=headers).json()["total"]
    assert overview["run_count"] == listed


def test_overview_drops_runs_that_have_no_owner(admin_data):
    """三行边界里只有两行有归属：无主的孤儿不许进全局合计。

    用增量断言（加行前后的差）而不是绝对值——这套用例跑在长期复用的测试库上，
    绝对值会被别的套件留下的行搅乱，差额才是不随库里存量漂移的那个量。
    """
    users, books, *_ = admin_data
    headers = bearer(users[0])

    def overview_metrics() -> dict:
        return client.get(PREFIX + "/overview", headers=headers).json()["metrics"]

    before = overview_metrics()
    with new_session() as db:
        rows = [
            AgentRun(project_id=books[1].id, user_id=users[1].id, node="attributed",
                     input_tokens=1, output_tokens=1, cost_est=0.5),
            AgentRun(project_id=None, user_id=users[1].id, node="account_only",
                     input_tokens=1, output_tokens=1, cost_est=0.25),
            AgentRun(project_id=uuid.uuid4(), user_id=None, node="ownerless_orphan",
                     input_tokens=1, output_tokens=1, cost_est=0.125),
        ]
        db.add_all(rows)
        db.commit()
        created = [row.id for row in rows]
    try:
        after = overview_metrics()
        assert after["run_count"] - before["run_count"] == 2          # 孤儿那行不算
        assert after["cost_est"] - before["cost_est"] == pytest.approx(0.75)
    finally:
        with new_session() as db:
            db.query(AgentRun).filter(AgentRun.id.in_(created)).delete()
            db.commit()
