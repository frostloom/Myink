"""短篇建书流程的三处分叉（SHORT-FORM-PLAN Phase 2.2）。

短篇与长篇共用 `POST /projects`、`POST /outline-draft`、`PUT /outline` 三条路由，
按 `project.form` 分叉：章数区间不同、方案生成后要不要审纲、大纲校验与落库形状不同。
本文件盯的就是这三处——外加一条底线：长篇分支逐字节不变。

模式 A（monkeypatch `myink.api.routes_book` 里的生成函数）：路由测试不该真的调 LLM。
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from conftest import identity_headers
from myink.api.main import app
from myink.db import new_session
from myink.models import Project, User

client = TestClient(app)

SHORT_CHAPTERS = 5
SHORT_OUTLINE = {
    "objective": "林砚查清父亲之死，并让青溪渡停航",
    "chapter_count": SHORT_CHAPTERS,
    "volumes": [{
        "volume_seq": 1, "title": "全篇 · 最后一班渡船", "goal": "让渡口停航",
        "chapter_start": 1, "chapter_end": SHORT_CHAPTERS,
        "chapters": [{"chapter_seq": i, "title": f"第 {i} 章", "goal": f"第 {i} 章的目标"}
                     for i in range(1, SHORT_CHAPTERS + 1)],
    }],
}
LONG_OUTLINE = {
    "objective": "主角查明真相", "chapter_count": 50,
    "volumes": [{"title": "启程", "goal": "找到第一条线索", "chapter_start": 1,
                 "chapter_end": 50, "stages": [{"name": "探索", "goal": "调查",
                                                "chapter_start": 1, "chapter_end": 50}]}],
}


def _demo_user_id() -> uuid.UUID:
    with new_session() as db:
        uid = db.scalar(select(User.id).where(User.username == "demo"))
    assert uid is not None, "请先运行 `myink init --seed`"
    return uid


class BookFactory:
    """建书工厂：用毕按 id 清掉（projects FK 级联子表）。

    关掉每日建书数闸门（§13 bookcnt）——本组测试要建多本书，配额不是被测对象。
    """

    def __init__(self, headers: dict):
        self.headers = headers
        self.created: list[str] = []

    def post(self, **body):
        payload = {"title": f"short-test-{uuid.uuid4().hex[:8]}",
                   "premise": "渡口老人与最后一班船"}
        payload.update(body)
        return client.post("/api/v1/projects", headers=self.headers, json=payload)

    def __call__(self, **body) -> tuple[dict, dict]:
        response = self.post(**body)
        assert response.status_code == 200, response.text
        project = response.json()
        self.created.append(project["id"])
        return project, self.headers

    def drop(self, *project_ids: str) -> None:
        with new_session() as db:
            db.execute(delete(Project).where(
                Project.id.in_([uuid.UUID(p) for p in project_ids])))
            db.commit()


@pytest.fixture
def book_factory(monkeypatch):
    import myink.api.routes_book as book
    monkeypatch.setattr(book, "settings", replace(book.settings, books_per_day_max=100000))
    factory = BookFactory(identity_headers(_demo_user_id()))
    yield factory
    if factory.created:
        factory.drop(*factory.created)


@pytest.fixture
def short_book(book_factory):
    """短篇草稿书（form=short，5 章）——短篇分支的默认起点。"""
    return book_factory(form="short", chapter_count=SHORT_CHAPTERS)


@pytest.fixture
def short_ready_book(short_book):
    """短篇书推进到 setup_confirmed（确认大纲的前置）。"""
    project, headers = short_book
    assert client.put(f'/api/v1/projects/{project["id"]}/setup', headers=headers,
                      json={"world_rules": {"规则": "渡船夜航"}}).status_code == 200
    return project, headers


def _creation(project: dict, headers: dict) -> dict:
    return client.get(f'/api/v1/projects/{project["id"]}/creation', headers=headers).json()


# ---------- 建书：POST /projects ----------


def test_create_project_records_the_form_and_keeps_the_draft_lifecycle(short_book):
    """建短篇书就是建一部普通草稿书，只是形态记为 short（生命周期一字不改）。"""
    project, headers = short_book
    assert project["creation_status"] == "draft"
    context = _creation(project, headers)["context"]
    assert context["form"] == "short"
    assert context["chapter_count"] == SHORT_CHAPTERS


def test_create_project_defaults_to_long_form_for_legacy_clients(book_factory):
    """不传 form 的老客户端 = 长篇（与列 server_default 'long' 同一条语义）。"""
    project, headers = book_factory(chapter_count=50)
    assert _creation(project, headers)["context"]["form"] == "long"


def test_the_project_payload_carries_the_form(short_book, book_factory):
    """形态要能被**读到**，不能只有写的那一侧（Phase 7 工作台要按形态分支）。

    建书/列表/创建上下文三处读的是同一列 `projects.form`；工作台从 `GET /projects` 拿书，
    若那里没有 form，前端就只能再发一次 creation 请求去上下文里找。
    """
    project, headers = short_book
    long_project, _ = book_factory(chapter_count=50)

    listed = client.get("/api/v1/projects", headers=headers).json()
    by_id = {item["id"]: item for item in listed}
    assert by_id[project["id"]]["form"] == "short"
    assert by_id[long_project["id"]]["form"] == "long"
    assert project["form"] == "short"


@pytest.mark.parametrize("form,chapter_count", [
    ("short", 11), ("short", 50), ("long", 5), ("long", 49),
])
def test_create_project_rejects_chapter_count_outside_the_form_range(book_factory, form, chapter_count):
    """章数区间按形态选：短篇 1–10，长篇 50–1000。

    改前靠 `Field(ge=50, le=1000)` 拦，短篇的 5 直接 422；Field 拿不到 form，改成路由体内校验。
    测的这两个「擦边」值（11 / 49）都在放宽后的 Field 区间内，只有按 form 判才拦得住。
    """
    response = book_factory.post(form=form, chapter_count=chapter_count)
    assert response.status_code == 400, response.text


def test_create_project_rejects_unknown_form(book_factory):
    response = book_factory.post(form="epic", chapter_count=50)
    assert response.status_code == 400, response.text


# ---------- 出方案：POST /outline-draft ----------


@pytest.fixture
def short_generators(monkeypatch):
    """记录短篇出方案/审纲的调用序列，并支持按调用次数排队返回。

    队列用尽后重复最后一项（单次调用场景只写一条即可）。
    """
    import myink.api.routes_book as book

    plans: list = [(SHORT_OUTLINE, None)]
    reviews: list = [("pass", "")]
    calls: list = []

    def _plan(genre, premise, *, chapter_count, chars_per_chapter, storyline="",
              revision_reason="", genre_pack=None, project_id=None, db=None):
        calls.append(("plan", chapter_count, chars_per_chapter, revision_reason))
        idx = min(sum(1 for c in calls if c[0] == "plan") - 1, len(plans) - 1)
        return plans[idx]

    def _review(plan, *, chapter_count, project_id=None, db=None):
        calls.append(("review", chapter_count, plan.get("objective", ""), ""))
        idx = min(sum(1 for c in calls if c[0] == "review") - 1, len(reviews) - 1)
        return reviews[idx]

    monkeypatch.setattr(book, "generate_short_plan", _plan)
    monkeypatch.setattr(book, "review_short_plan", _review)
    return {"calls": calls, "plans": plans, "reviews": reviews}


def _draft(project: dict, headers: dict, **body):
    payload = {"premise": "渡口老人与最后一班船", "chapter_count": SHORT_CHAPTERS}
    payload.update(body)
    return client.post(f'/api/v1/projects/{project["id"]}/outline-draft', headers=headers, json=payload)


def test_outline_draft_picks_the_chapter_range_from_the_books_own_form(
        short_book, book_factory, short_generators, monkeypatch):
    """同一条路由，区间按 form 选：短篇 1–10（11 与 50 都要拦），长篇仍是 50–1000。"""
    project, headers = short_book
    assert _draft(project, headers, chapter_count=11).status_code == 400
    assert _draft(project, headers, chapter_count=50).status_code == 400
    assert _draft(project, headers, chapter_count=SHORT_CHAPTERS).status_code == 200
    assert [c[0] for c in short_generators["calls"]] == ["plan", "review"], "被拦的两次不该打 LLM"

    import myink.api.routes_book as book
    monkeypatch.setattr(book, "generate_book_outline", lambda *a, **kw: (LONG_OUTLINE, None))
    long_project, long_headers = book_factory(chapter_count=50)
    long_base = f'/api/v1/projects/{long_project["id"]}/outline-draft'
    assert client.post(long_base, headers=long_headers,
                       json={"premise": "x", "chapter_count": 5}).status_code == 400
    assert client.post(long_base, headers=long_headers,
                       json={"premise": "x", "chapter_count": 50}).status_code == 200


def test_short_outline_draft_runs_plan_then_review_and_ships_the_first_version(
        short_book, short_generators):
    """出完方案紧接着跑一次审纲（决策文档 §2 第 2 步）——审过就用第一版。"""
    project, headers = short_book
    response = _draft(project, headers)
    assert response.status_code == 200
    assert response.json() == {"outline": SHORT_OUTLINE, "error": None}
    assert [c[0] for c in short_generators["calls"]] == ["plan", "review"]
    # 方案拿到的必须是**归一后**的每章字数（5 章 × 8000 超 2 万 → 压到 4000）：
    # 逐章细纲的篇幅要照真实目标排，照用户原始输入排出来的方案落笔就写不下。
    assert short_generators["calls"][0][1:] == (SHORT_CHAPTERS, 4000, "")
    context = _creation(project, headers)["context"]
    assert context["outline_draft"] == SHORT_OUTLINE
    assert not context.get("outline_warning")


def test_short_outline_draft_rerolls_once_with_the_review_reason(short_book, short_generators):
    """审纲说 revise → 带上 reason 重出一次；第二版审过就换第二版。

    reason 必须真的进到第二次 plan 调用里——不带 reason 的重出就是同一份方案再掷一次骰子。
    """
    short_generators["plans"][:] = [(SHORT_OUTLINE, None),
                                    ({**SHORT_OUTLINE, "objective": "第二版"}, None)]
    short_generators["reviews"][:] = [("revise", "第三章没有章尾钩子"), ("pass", "")]

    project, headers = short_book
    response = _draft(project, headers)
    assert response.status_code == 200
    assert response.json()["outline"]["objective"] == "第二版"
    assert [(c[0], c[3]) for c in short_generators["calls"]] == [
        ("plan", ""), ("review", ""), ("plan", "第三章没有章尾钩子"), ("review", "")]
    context = _creation(project, headers)["context"]
    assert context["outline_draft"]["objective"] == "第二版"
    assert not context.get("outline_warning")


def test_short_outline_draft_keeps_v1_when_the_review_still_objects(short_book, short_generators):
    """两次都不过 → **保留第一版**并回一个 warning（对齐决策文档 §2 第 2 步「保留 v001」）。

    不 4xx、不 5xx：审纲是建议不是闸门，用户要的是能接着往下用的方案。
    """
    short_generators["plans"][:] = [(SHORT_OUTLINE, None),
                                    ({**SHORT_OUTLINE, "objective": "第二版"}, None)]
    short_generators["reviews"][:] = [("revise", "第三章没有章尾钩子"),
                                      ("revise", "收尾太仓促")]

    project, headers = short_book
    response = _draft(project, headers)
    assert response.status_code == 200
    assert response.json()["outline"] == SHORT_OUTLINE
    assert response.json()["error"] is None
    context = _creation(project, headers)["context"]
    assert context["outline_draft"] == SHORT_OUTLINE
    assert "收尾太仓促" in context["outline_warning"]


def test_short_outline_draft_skips_the_review_when_the_plan_call_failed(short_book, short_generators):
    """方案调用就失败了 → 没有可审的东西，别再打一次 LLM（§6.12 降级）。"""
    short_generators["plans"][:] = [({}, "provider down")]

    project, headers = short_book
    response = _draft(project, headers)
    assert response.status_code == 200
    assert response.json() == {"outline": {}, "error": "provider down"}
    assert [c[0] for c in short_generators["calls"]] == ["plan"]


def test_short_outline_draft_reports_the_compressed_lengths(short_book, short_generators):
    """§5 的 `章数 × 每章字数 ≤ 20000`：超了就压每章字数，并让前端拿得到这个事实。"""
    project, headers = short_book
    assert _draft(project, headers, chapter_count=10, chars_per_chapter=8000).status_code == 200
    context = _creation(project, headers)["context"]
    assert (context["chapter_count"], context["chars_per_chapter"]) == (10, 2000)
    assert context["lengths_compressed"] is True
    assert short_generators["calls"][0][1:3] == (10, 2000)


def test_short_outline_draft_leaves_a_fitting_length_alone(short_book, short_generators):
    project, headers = short_book
    assert _draft(project, headers, chapter_count=2, chars_per_chapter=8000).status_code == 200
    context = _creation(project, headers)["context"]
    assert (context["chapter_count"], context["chars_per_chapter"]) == (2, 8000)
    assert context["lengths_compressed"] is False


# ---------- 确认大纲：PUT /outline ----------


def test_short_outline_requires_confirmed_setup(short_book):
    """短篇分支不能顺手绕过建书生命周期（先确认设定、再确认大纲）。"""
    project, headers = short_book
    assert client.put(f'/api/v1/projects/{project["id"]}/outline', headers=headers,
                      json=SHORT_OUTLINE).status_code == 409


def test_confirming_a_short_outline_keeps_the_per_chapter_plan(short_ready_book):
    """逐章细纲是短篇写手一次成稿的唯一依据，落库读回都不能被折成 stages。

    长篇的 `build_persisted_outline` / `normalize_outline` 会把卷内 chapters 折叠成
    约 30 章一段的 stages（老数据兼容路径），短篇走这条路等于把方案吃了。
    """
    project, headers = short_ready_book
    base = f'/api/v1/projects/{project["id"]}'
    response = client.put(base + "/outline", headers=headers, json=SHORT_OUTLINE)
    assert response.status_code == 200, response.text
    assert _creation(project, headers)["project"]["creation_status"] == "ready"
    assert client.get(base + "/access?write=true", headers=headers).status_code == 200

    outline = client.get(base + "/outline", headers=headers).json()["outline"]
    assert outline["chapter_count"] == SHORT_CHAPTERS
    assert len(outline["volumes"]) == 1
    chapters = outline["volumes"][0]["chapters"]
    assert [c["chapter_seq"] for c in chapters] == list(range(1, SHORT_CHAPTERS + 1))
    assert chapters[0]["goal"] == "第 1 章的目标"


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda p: p.update(chapter_count=50, volumes=[{
        **p["volumes"][0], "chapter_end": 50, "chapters": []}]), id="long-shaped"),
    pytest.param(lambda p: p["volumes"].append({**p["volumes"][0], "volume_seq": 2}),
                 id="two-volumes"),
    pytest.param(lambda p: p["volumes"][0].pop("chapters"), id="no-per-chapter"),
    pytest.param(lambda p: p["volumes"][0]["chapters"].pop(2), id="missing-chapter"),
])
def test_confirming_a_short_outline_rejects_a_payload_the_short_writer_cannot_use(
        short_ready_book, mutate):
    """短篇校验比长篇严在「必须逐章」这一条：缺了它，写手只能自己编。"""
    project, headers = short_ready_book
    base = f'/api/v1/projects/{project["id"]}'
    payload = copy.deepcopy(SHORT_OUTLINE)
    mutate(payload)
    assert client.put(base + "/outline", headers=headers, json=payload).status_code == 400
    assert client.get(base + "/outline", headers=headers).json()["outline"] is None
    assert _creation(project, headers)["project"]["creation_status"] == "setup_confirmed"


def test_long_books_still_go_through_the_long_validator(book_factory):
    """长篇分支逐字节不变：同一份短篇形状的 payload，到长篇书仍按长篇口径拒（5 章 < 50）。"""
    long_project, headers = book_factory(chapter_count=50)
    base = f'/api/v1/projects/{long_project["id"]}'
    assert client.put(base + "/setup", headers=headers,
                      json={"world_rules": {"规则": "灵气充盈"}}).status_code == 200
    assert client.put(base + "/outline", headers=headers, json=SHORT_OUTLINE).status_code == 400
    assert client.put(base + "/outline", headers=headers, json=LONG_OUTLINE).status_code == 200
    assert _creation(long_project, headers)["project"]["creation_status"] == "ready"