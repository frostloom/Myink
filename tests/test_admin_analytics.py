"""分析页下钻：用户 → 书 → 任务 → 章 → 快照。

重点是两级聚合（按任务先汇总再平均，不是按 run 行平均）与「列表不出正文、只有快照详情
接口出正文」这条边界。种数据时 agent_runs/tasks 无 RLS（观测表）走 new_session()；
generation_snapshots 带 project_id，在隔离清单里，必须走 tenant_session。
"""
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from myink.api import auth
from myink.api.main import app
from myink.config import settings
from myink.db import new_session, tenant_session
from myink.models import AgentRun, GenerationSnapshot, Project, Task, User

client = TestClient(app, raise_server_exceptions=False)
PREFIX = "/api/v1/admin"
# 单章任务的目标章号（run 挂在裸 task_id 上，靠 Task.chapter_seq 归章）
SINGLE_CHAPTER = 7
BATCH_CHAPTERS = (1, 2, 3)
PLAN_TEXT = "本章计划正文（不该出现在列表接口里）"


@pytest.fixture
def analytics_data(monkeypatch):
    monkeypatch.setattr(auth, "settings", replace(settings, jwt_secret="admin-test-secret-at-least-32-characters"))
    with new_session() as db:
        admin = User(username=f"an-{uuid.uuid4().hex}", role="admin")
        owner = User(username=f"an-{uuid.uuid4().hex}", role="user")
        stranger = User(username=f"an-{uuid.uuid4().hex}", role="user")
        db.add_all([admin, owner, stranger])
        db.flush()
        book = Project(user_id=owner.id, title="有任务的书")
        empty_book = Project(user_id=owner.id, title="没有任务的书")
        stranger_book = Project(user_id=stranger.id, title="别人的书")
        db.add_all([book, empty_book, stranger_book])
        db.flush()
        single = Task(project_id=book.id, task_type="chapter_generate", status="done",
                      chapter_seq=SINGLE_CHAPTER)
        batch = Task(project_id=book.id, task_type="batch_generate", status="done")
        db.add_all([single, batch])
        db.flush()
        runs = [
            # 单章任务：2 行，每行 ¥1.0 / 100ms → Σ¥2.0 / 200ms
            AgentRun(project_id=book.id, task_id=str(single.id), node=node,
                     input_tokens=10, output_tokens=20, cost_est=1.0, duration_ms=100)
            for node in ("write", "validate")
        ]
        for seq in BATCH_CHAPTERS:
            # 批次：每章 4 行，每行 ¥0.1 / 10ms
            runs += [AgentRun(project_id=book.id, task_id=f"{batch.id}:ch{seq}", node=node,
                              input_tokens=1, output_tokens=2, cost_est=0.1, duration_ms=10)
                     for node in ("recall", "write", "audit", "patch")]
        # book 级 run（裸 batch_id）：有成本但不是任何一章的
        runs.append(AgentRun(project_id=book.id, task_id=str(batch.id), node="batch_plan",
                             input_tokens=1, output_tokens=1, cost_est=0.5, duration_ms=50))
        # 别人的书：一条没有对应 Task 的 run，用来看「无任务 → 均值为 null」
        runs.append(AgentRun(project_id=stranger_book.id, task_id=str(uuid.uuid4()), node="write",
                             cost_est=99.0, duration_ms=9999))
        db.add_all(runs)
        db.commit()
        project_ids = [book.id, empty_book.id, stranger_book.id]
    with tenant_session(book.id) as db:
        snapshots = [
            GenerationSnapshot(project_id=book.id, task_id=str(single.id), chapter_seq=SINGLE_CHAPTER,
                               stage="write", attempt=1, model_id="m1", cost_est=1.0, duration_ms=100,
                               payload={"prompt": {"sections": [
                                   {"name": "章节计划", "policy": "full", "text": PLAN_TEXT},
                                   {"name": "题材参考文档", "policy": "hash", "bytes": 400, "sha256": "ab"}]},
                                   "output": {"bytes": 12, "sha256": "cd", "excerpt": "正文开头"}}),
            GenerationSnapshot(project_id=book.id, task_id=str(single.id), chapter_seq=SINGLE_CHAPTER,
                               stage="validate", attempt=1,
                               payload={"findings": [
                                   {"finding_id": "f1", "conflict_key": "k1", "conflict_type": "character",
                                    "severity": "major", "scope": "local", "source": "L1",
                                    "suggestion": "改回旧名", "evidence": [{"chapter": SINGLE_CHAPTER, "quote": "旧剑"}]},
                                   {"severity": "hint", "evidence": []}]}),
            # 早于快照上线那类：只有标量没有正文
            GenerationSnapshot(project_id=book.id, task_id=f"{batch.id}:ch2", chapter_seq=2,
                               stage="write", attempt=1, model_id="m2", cost_est=0.1, duration_ms=10),
        ]
        db.add_all(snapshots)
        db.commit()
        snapshot_ids = [snapshot.id for snapshot in snapshots]
    try:
        yield admin, owner, stranger, book, empty_book, single, batch, snapshot_ids
    finally:
        with tenant_session(book.id) as db:
            db.query(GenerationSnapshot).filter(GenerationSnapshot.project_id == book.id).delete()
            db.commit()
        with new_session() as db:
            db.query(AgentRun).filter(AgentRun.project_id.in_(project_ids)).delete()
            db.query(Task).filter(Task.project_id.in_(project_ids)).delete()
            db.query(Project).filter(Project.id.in_(project_ids)).delete()
            db.query(User).filter(User.id.in_([admin.id, owner.id, stranger.id])).delete()
            db.commit()


def bearer(user):
    return {"Authorization": "Bearer " + auth.create_access_token(user.id, auth_version=user.auth_version)}


def test_task_averages_are_two_level_not_per_run(analytics_data):
    """按 run 行平均会让 13 次调用的批次凭次数压过 2 次调用的单章任务，均值就不再是
    「单次任务的平均」。这里两个任务：单章 Σ¥2.0/200ms，批次 Σ¥1.7/170ms。"""
    admin, owner, *_ = analytics_data
    headers = bearer(admin)
    row = client.get(PREFIX + f"/users?q={owner.username}", headers=headers).json()["items"][0]
    averages = row["task_averages"]
    assert averages == pytest.approx({"avg_cost_per_task": 1.85, "avg_duration_ms_per_task": 185.0,
                                      "avg_runs_per_task": 7.5})
    # 朴素「按 run 行平均」是 3.7/15 ≈ 0.25 —— 必须不是它
    assert averages["avg_cost_per_task"] != pytest.approx(3.7 / 15)
    book = client.get(PREFIX + f"/projects?user_id={owner.id}", headers=headers).json()["items"]
    assert {item["title"]: item["task_averages"]["avg_runs_per_task"] for item in book} == {
        "有任务的书": 7.5, "没有任务的书": None}


def test_generation_tasks_count_chapters_without_book_level_runs(analytics_data):
    """book 级 run（batch_plan 用裸 batch_id）不是章：批次的 12 行 :ch 行该报 3 章，不是 4。"""
    admin, _, _, book, empty_book, single, batch, _ = analytics_data
    headers = bearer(admin)
    page = client.get(PREFIX + f"/projects/{book.id}/generation-tasks", headers=headers).json()
    rows = {item["id"]: item for item in page["items"]}
    assert page["total"] == 2
    assert rows[str(single.id)]["chapter_count"] == 1
    assert rows[str(batch.id)]["chapter_count"] == len(BATCH_CHAPTERS)
    metrics = rows[str(batch.id)]["metrics"]
    assert {key: metrics[key] for key in ("run_count", "input_tokens", "output_tokens", "duration_ms")} == {
        "run_count": 13, "input_tokens": 13, "output_tokens": 25, "duration_ms": 170}
    assert metrics["cost_est"] == pytest.approx(1.7)
    assert (rows[str(single.id)]["snapshot_count"], rows[str(batch.id)]["snapshot_count"]) == (2, 1)
    assert client.get(PREFIX + f"/projects/{empty_book.id}/generation-tasks", headers=headers).json() == {
        "items": [], "total": 0, "limit": 25, "offset": 0}


def test_chapter_breakdown_attaches_snapshot_refs_without_shipping_text(analytics_data):
    """列表只带定位与标量：提示词正文/召回块只在 /snapshots/{id} 出。"""
    admin, _, _, book, _, single, batch, _ = analytics_data
    headers = bearer(admin)
    single_page = client.get(PREFIX + f"/tasks/{single.id}/chapters", headers=headers)
    assert single_page.status_code == 200, single_page.text
    chapter = single_page.json()["items"][0]
    assert (single_page.json()["total"], chapter["chapter_seq"], chapter["metrics"]["run_count"]) == (
        1, SINGLE_CHAPTER, 2)
    assert chapter["stages"] == ["validate", "write"]
    assert {ref["stage"] for ref in chapter["snapshots"]} == {"write", "validate"}
    assert PLAN_TEXT not in single_page.text

    batch_page = client.get(PREFIX + f"/tasks/{batch.id}/chapters", headers=headers).json()
    assert [(item["chapter_seq"], item["metrics"]["run_count"]) for item in batch_page["items"]] == [
        (seq, 4) for seq in BATCH_CHAPTERS]
    # ch2 的快照只有标量没有 payload，仍要作为指针出现（列表本来就不带正文）
    assert [ref["stage"] for ref in batch_page["items"][1]["snapshots"]] == ["write"]
    assert PLAN_TEXT not in str(batch_page)


def test_snapshot_detail_is_the_only_endpoint_that_ships_text(analytics_data):
    """快照详情出正文且标出「选择性留存」；早于快照上线的行标 snapshot_missing，不做假回填。"""
    admin, _, _, _, _, _, _, snapshot_ids = analytics_data
    headers = bearer(admin)
    write_snapshot_id, _, legacy_snapshot_id = snapshot_ids
    detail = client.get(PREFIX + f"/snapshots/{write_snapshot_id}", headers=headers)
    assert detail.status_code == 200 and detail.headers["cache-control"] == "no-store"
    body = detail.json()
    assert (body["stage"], body["chapter_seq"], body["snapshot_missing"]) == ("write", SINGLE_CHAPTER, False)
    sections = {section["name"]: section for section in body["payload"]["data"]["prompt"]["sections"]}
    assert sections["章节计划"]["text"] == PLAN_TEXT
    assert sections["题材参考文档"]["policy"] == "hash" and "text" not in sections["题材参考文档"]

    legacy = client.get(PREFIX + f"/snapshots/{legacy_snapshot_id}", headers=headers).json()
    assert legacy["snapshot_missing"] is True and legacy["payload"]["data"] is None
    assert client.get(PREFIX + "/snapshots/99999999", headers=headers).status_code == 404


def test_findings_flatten_from_validate_snapshots_with_filters(analytics_data):
    """发现按条分页，不是按快照分页；severity/chapter_seq 是服务端过滤。"""
    admin, _, _, book, _, _, _, snapshot_ids = analytics_data
    headers = bearer(admin)
    page = client.get(PREFIX + f"/projects/{book.id}/findings", headers=headers).json()
    assert page["total"] == 2, page
    finding = next(item for item in page["items"] if item["severity"] == "major")
    assert (finding["snapshot_id"], finding["chapter_seq"], finding["conflict_key"]) == (
        snapshot_ids[1], SINGLE_CHAPTER, "k1")
    assert finding["confidence"] is None and finding["evidence"] == [
        {"chapter": SINGLE_CHAPTER, "quote": "旧剑"}]
    assert len(page["items"][1]["evidence"]) == 0, "缺 evidence 的发现要照原样给出，不能丢"
    filtered = client.get(PREFIX + f"/projects/{book.id}/findings?severity=major", headers=headers).json()
    assert filtered["total"] == 1 and filtered["items"][0]["severity"] == "major"
    assert client.get(PREFIX + f"/projects/{book.id}/findings?chapter_seq=1", headers=headers).json()["total"] == 0


@pytest.mark.parametrize("path", ["users", "generation-tasks", "chapters", "findings", "snapshots"])
def test_analytics_reads_require_admin(analytics_data, path):
    admin, owner, _, book, _, single, _, snapshot_ids = analytics_data
    target = {"users": PREFIX + "/users", "generation-tasks": f"{PREFIX}/projects/{book.id}/generation-tasks",
              "chapters": f"{PREFIX}/tasks/{single.id}/chapters",
              "findings": f"{PREFIX}/projects/{book.id}/findings",
              "snapshots": f"{PREFIX}/snapshots/{snapshot_ids[0]}"}[path]
    response = client.get(target, headers=bearer(owner))
    assert response.status_code == 403 and response.headers["cache-control"] == "no-store"


def test_analytics_reads_are_audited_and_bounded(analytics_data):
    admin, _, _, book, _, _, _, _ = analytics_data
    headers = bearer(admin)
    assert client.get(PREFIX + f"/projects/{book.id}/generation-tasks?limit=101", headers=headers).status_code == 422
    logs = client.get(PREFIX + "/access-logs?limit=100", headers=headers).json()["items"]
    assert any(log["action"] == "admin.generation_tasks" and f"project_id={book.id}" == log["target"]
               for log in logs)
    assert any(log["action"] == "admin.users" and log["target"] == "collection" for log in logs)
