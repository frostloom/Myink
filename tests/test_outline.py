"""整书大纲（§11 建书 ③：题材/梗概/大致章节数/大致故事线 → Objective + 卷 + 逐章目标）测试。

三层递进骨架（对齐 inkos volume_map 的递归 OKR）：全书 Objective → 卷（主题/卷目标/关键结果/
卷末事件）→ 逐章目标。Planner 按目标章节数自动分卷，卷内章总数 == chapter_count。

范围：
- 草稿：POST outline-draft stub 合法 JSON → {outline, error:None} 且不落库（DB 断言）、
  记 agent_runs(node=book_outline)；provider 抛错 / 坏 JSON / 形状不符（volumes 缺失）→
  {outline:{}, error} 200 降级（§6.12）；premise 空 400；章节数越界 400；
- 落库：PUT outline → volume_outlines 单行（volume_seq=1）整体替换、逐章补全局 seq（跨卷连续）、
  空章/空卷丢弃、volume_seq 重编号；GET outline 读回；无大纲 → {outline: null} 不 500；
- 注入：plan_messages / write_messages 带新切片 {objective, volume, current} → 渲染全书 Objective /
  当前卷（卷目标+KR+卷末事件）/ 本章大纲位；write 点明「开场须扣住本大纲位」且不再注入上一章开头
  （§11 开头雷同的根治是大纲位不同，不是 prev_chapter_opening hack）；
- 越权矩阵：缺失身份 / 伪造他人 403，项目不存在 404。

模式：同 test_book_setup book_stub（monkeypatch aiink.providers.default_provider）。
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from aiink.api.main import app
from aiink.db import new_session, tenant_session
from aiink.models import AgentRun, Project, User, VolumeOutline
from aiink.providers.base import ModelProvider, ModelResponse
from aiink.workflow import prompts
from aiink.workflow.outline import normalize_outline

client = TestClient(app)

_OUTLINE = {
    "objective": "从杂役修士成为宗门长老并公开父辈冤案真相",
    "volumes": [
        {
            "volume_seq": 1,
            "title": "第一卷 · 青云山下",
            "theme": "立身",
            "goal": "入宗立足并发现玉佩疑点",
            "key_results": ["通过入门试炼", "拜入长老座下", "发现玉佩疑点"],
            "end_event": "主角被迫离开青云宗",
            "chapters": [
                {"title": "第一章 玉佩", "goal": "得玉佩、初入青云宗", "beats": ["得玉佩", "遇苏瑶"]},
                {"title": "第二章 试炼", "goal": "入宗试炼立威", "beats": ["试炼", "结怨赵天行"]},
                {"title": "", "goal": ""},  # 空条目 → 落库时丢弃
            ],
        },
        {
            "volume_seq": 2,
            "title": "第二卷 · 北境",
            "theme": "流亡",
            "goal": "查明真相并攒下复仇资本",
            "key_results": ["追查玉佩源头", "结识盟友", "获得一战后盾"],
            "end_event": "宗门惊变、真相大白",
            "chapters": [
                {"title": "第三章 北境", "goal": "流落北境立足", "beats": ["北境遇险", "结识盟友"]},
            ],
        },
    ],
}


def _demo_user_id() -> uuid.UUID:
    with new_session() as db:
        u = db.query(User).filter(User.username == "demo").first()
        assert u is not None, "请先运行 `aiink init`（demo 用户未建）"
        return u.id


def _h(uid: str | uuid.UUID | None) -> dict:
    return {"X-AiInk-User": str(uid)} if uid is not None else {}


class _OutlineStub(ModelProvider):
    """假 provider：outline-draft 返回固定 JSON；可配抛错 / 坏原文 / 形状不符（测降级 §6.12）。"""

    def __init__(self, payload=None, *, raw=None, raise_error=False):
        self._payload = payload
        self._raw = raw
        self._raise_error = raise_error

    def name(self) -> str:
        return "outline-stub"

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False,
                 tools=None, disable_thinking=False):
        if self._raise_error:
            raise RuntimeError("provider down")
        import json as _json
        content = self._raw if self._raw is not None else _json.dumps(self._payload or {}, ensure_ascii=False)
        return ModelResponse(content=content, model_id=model_id, input_tokens=10, output_tokens=20)


def _outline_run_count(pid: str) -> int:
    with new_session() as db:
        return db.query(AgentRun).filter(
            AgentRun.project_id == uuid.UUID(pid), AgentRun.node == "book_outline").count()


# ---- 草稿：POST outline-draft ----


def test_outline_draft_returns_draft_not_persisted(temp_project, monkeypatch):
    """草稿返回合法 JSON 且不落库（volume_outlines 无行）；记 agent_runs(node=book_outline)。"""
    import json as _json
    import aiink.providers as providers_mod

    stub = _OutlineStub(_OUTLINE)
    monkeypatch.setattr(providers_mod, "default_provider", stub)
    resp = client.post(f"/internal/v1/projects/{temp_project}/outline-draft",
                       headers=_h(_demo_user_id()),
                       json={"premise": "少年得玉佩追寻真相", "chapter_count": 20,
                             "storyline": "前期宗门、中期追查、后期决战"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] is None
    outline = data["outline"]
    assert outline["objective"] == _OUTLINE["objective"]
    assert len(outline["volumes"]) == 2
    assert len(outline["volumes"][0]["chapters"]) == 3
    with tenant_session(temp_project) as db:
        assert db.query(VolumeOutline).count() == 0, "草稿不落库"
    assert _outline_run_count(temp_project) == 1, "应记 book_outline agent_run（§6.8）"


def test_outline_draft_degraded_on_provider_error(temp_project, monkeypatch):
    import aiink.providers as providers_mod
    monkeypatch.setattr(providers_mod, "default_provider", _OutlineStub(raise_error=True))
    resp = client.post(f"/internal/v1/projects/{temp_project}/outline-draft",
                       headers=_h(_demo_user_id()),
                       json={"premise": "少年追查玉佩真相", "chapter_count": 10})
    assert resp.status_code == 200
    assert resp.json() == {"outline": {}, "error": "provider down"}


def test_outline_draft_degraded_on_bad_json(temp_project, monkeypatch):
    import aiink.providers as providers_mod
    monkeypatch.setattr(providers_mod, "default_provider",
                        _OutlineStub(raw="not json{{{", raise_error=False))
    resp = client.post(f"/internal/v1/projects/{temp_project}/outline-draft",
                       headers=_h(_demo_user_id()),
                       json={"premise": "少年追查玉佩真相", "chapter_count": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["outline"] == {}
    assert data["error"] is not None and "parse_error" in data["error"]


def test_outline_draft_degraded_wrong_shape(temp_project, monkeypatch):
    """合法 JSON 但缺 volumes（旧版 arc 形状 / 幻觉）→ 形状守卫降级，不落脏大纲。"""
    import aiink.providers as providers_mod
    monkeypatch.setattr(providers_mod, "default_provider",
                        _OutlineStub({"arc": ["起"], "chapters": [{"goal": "x"}]}))
    resp = client.post(f"/internal/v1/projects/{temp_project}/outline-draft",
                       headers=_h(_demo_user_id()),
                       json={"premise": "少年追查玉佩真相", "chapter_count": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["outline"] == {}
    assert data["error"] is not None and "unexpected_shape" in data["error"]


def test_outline_draft_validation_400(temp_project, monkeypatch):
    import aiink.providers as providers_mod
    monkeypatch.setattr(providers_mod, "default_provider", _OutlineStub(_OUTLINE))
    url = f"/internal/v1/projects/{temp_project}/outline-draft"
    assert client.post(url, headers=_h(_demo_user_id()),
                       json={"premise": "  ", "chapter_count": 10}).status_code == 400
    assert client.post(url, headers=_h(_demo_user_id()),
                       json={"premise": "少年", "chapter_count": 0}).status_code == 400
    assert client.post(url, headers=_h(_demo_user_id()),
                       json={"premise": "少年", "chapter_count": 201}).status_code == 400


def test_outline_draft_ownership(temp_project):
    url = f"/internal/v1/projects/{temp_project}/outline-draft"
    body = {"premise": "少年追查玉佩真相", "chapter_count": 10}
    assert client.post(url, json=body).status_code == 403
    assert client.post(url, headers=_h(uuid.uuid4()), json=body).status_code == 403
    assert client.post(f"/internal/v1/projects/{uuid.uuid4()}/outline-draft",
                       headers=_h(_demo_user_id()), json=body).status_code == 404


# ---- 落库 / 读取：PUT + GET outline ----


def test_put_outline_persists_with_global_seq_and_empty_dropped(temp_project):
    """PUT 落库 volume_outlines 单行：逐章补全局 seq（跨卷连续）、空章/空卷丢弃、GET 读回。"""
    body = {
        "objective": _OUTLINE["objective"],
        "volumes": _OUTLINE["volumes"],
        "premise": "少年得玉佩追寻真相",
        "chapter_count": 20,
        "storyline": "前期宗门、中期追查、后期决战",
    }
    resp = client.put(f"/internal/v1/projects/{temp_project}/outline",
                      headers=_h(_demo_user_id()), json=body)
    assert resp.status_code == 200
    saved = resp.json()["outline"]
    assert saved["objective"] == _OUTLINE["objective"]
    assert [v["volume_seq"] for v in saved["volumes"]] == [1, 2], "volume_seq 重新编号"
    v1, v2 = saved["volumes"]
    assert [c["seq"] for c in v1["chapters"]] == [1, 2], "空条目丢弃，补 seq"
    assert [c["seq"] for c in v2["chapters"]] == [3], "全局 seq 跨卷连续编号"
    assert v1["chapters"][0]["beats"] == ["得玉佩", "遇苏瑶"]
    assert v1["key_results"] == _OUTLINE["volumes"][0]["key_results"]

    got = client.get(f"/internal/v1/projects/{temp_project}/outline",
                     headers=_h(_demo_user_id()))
    assert got.status_code == 200
    assert got.json()["outline"] == saved

    with tenant_session(temp_project) as db:
        row = db.query(VolumeOutline).filter(VolumeOutline.volume_seq == 1).first()
        assert row is not None and row.outline["chapter_count"] == 20


def test_put_outline_drops_all_empty_volume(temp_project):
    """整卷章全空的卷 → 整卷丢弃（防空卷落库污染大纲）。"""
    body = {
        "objective": "终局",
        "volumes": [
            {"title": "有效卷", "goal": "推进", "chapters": [{"title": "章", "goal": "目标"}]},
            {"title": "空卷", "goal": "废卷", "chapters": [{"title": "", "goal": ""}]},
        ],
        "premise": "", "chapter_count": 1, "storyline": "",
    }
    resp = client.put(f"/internal/v1/projects/{temp_project}/outline",
                      headers=_h(_demo_user_id()), json=body)
    saved = resp.json()["outline"]
    assert len(saved["volumes"]) == 1
    assert saved["volumes"][0]["volume_seq"] == 1 and saved["volumes"][0]["title"] == "有效卷"


def test_put_outline_overwrites_existing(temp_project):
    body = {"objective": "旧终局", "volumes": [{"title": "旧卷", "goal": "旧目标",
                                                "chapters": [{"title": "旧章", "goal": "旧目标"}]}], "premise": ""}
    client.put(f"/internal/v1/projects/{temp_project}/outline",
               headers=_h(_demo_user_id()), json=body)
    body2 = {"objective": "新终局", "volumes": [{"title": "新卷", "goal": "新目标",
                                                 "chapters": [{"title": "新章", "goal": "新目标"}]}], "premise": ""}
    client.put(f"/internal/v1/projects/{temp_project}/outline",
               headers=_h(_demo_user_id()), json=body2)
    got = client.get(f"/internal/v1/projects/{temp_project}/outline",
                     headers=_h(_demo_user_id())).json()
    assert got["outline"]["objective"] == "新终局", "整体替换，不留旧行残留"
    with tenant_session(temp_project) as db:
        assert db.query(VolumeOutline).count() == 1, "单行 upsert，不重复建行"


def test_get_outline_empty_project_null(temp_project):
    resp = client.get(f"/internal/v1/projects/{temp_project}/outline",
                      headers=_h(_demo_user_id()))
    assert resp.status_code == 200
    assert resp.json() == {"outline": None}


def test_outline_ownership_matrix(temp_project):
    url = f"/internal/v1/projects/{temp_project}/outline"
    assert client.get(url).status_code == 403
    assert client.get(url, headers=_h(uuid.uuid4())).status_code == 403
    assert client.get(f"/internal/v1/projects/{uuid.uuid4()}/outline",
                      headers=_h(_demo_user_id())).status_code == 404
    body = {"objective": "", "volumes": []}
    assert client.put(url, json=body).status_code == 403
    assert client.put(url, headers=_h(uuid.uuid4()), json=body).status_code == 403


# ---- 存量旧形状向后兼容（normalize_outline） ----


def test_normalize_outline_old_flat_shape_wrapped():
    """旧版 {arc, chapters} 扁平大纲 → 并入「全书主线」单卷；新版三层原样；非 dict → None。"""
    old = {"arc": ["起", "承"], "chapters": [{"seq": 1, "title": "第一章", "goal": "入宗"},
                                            {"seq": 2, "title": "第二章", "goal": "试炼"}],
           "premise": "少年得玉佩"}
    out = normalize_outline(old)
    assert out["objective"] == ""
    assert len(out["volumes"]) == 1
    assert out["volumes"][0]["title"] == "全书主线"
    assert [c["seq"] for c in out["volumes"][0]["chapters"]] == [1, 2]
    assert out["premise"] == "少年得玉佩", "非 arc/chapters 字段保留"
    assert "arc" not in out and "chapters" not in out

    assert normalize_outline(_OUTLINE) is _OUTLINE, "新版三层原样返回（不重包）"
    assert normalize_outline(None) is None
    assert normalize_outline("nope") is None


def test_get_outline_normalizes_legacy_flat_shape(temp_project):
    """存量旧形状大纲 GET 归一为新三层（前端/注入对新旧数据一致）。

    旧形状是新版 PUT 前的落库格式，本测试直接种 DB 行模拟存量数据。
    """
    with tenant_session(temp_project) as db:
        db.add(VolumeOutline(project_id=uuid.UUID(temp_project), volume_seq=1, title="全书大纲",
                             outline={"arc": ["起", "承"],
                                      "chapters": [{"seq": 1, "title": "旧章", "goal": "旧目标"}],
                                      "premise": ""}))
        db.commit()
    got = client.get(f"/internal/v1/projects/{temp_project}/outline",
                     headers=_h(_demo_user_id())).json()
    assert got["outline"]["volumes"][0]["title"] == "全书主线"
    assert got["outline"]["volumes"][0]["chapters"][0]["goal"] == "旧目标"


# ---- 注入：plan / write 带三层大纲切片 ----


def test_plan_messages_injects_outline_slice():
    """plan_messages 带 {objective, volume, current} → 系统层渲染全书 Objective + 当前卷 + 本章大纲位。"""
    ctx = {}
    outline = {
        "objective": "成为宗门长老并公开真相",
        "volume": {"volume_seq": 1, "title": "第一卷 · 青云山下", "goal": "入宗立足",
                   "key_results": ["通过试炼", "拜入长老座下"], "end_event": "被迫离开青云宗"},
        "current": {"seq": 3, "goal": "宗门惊变", "beats": ["宗门遇袭", "玉佩示警"]},
    }
    msgs = prompts.plan_messages(ctx, None, outline=outline)
    sys_content = msgs[0]["content"]
    assert "全书 Objective" in sys_content and "成为宗门长老并公开真相" in sys_content
    assert "当前卷 · 第一卷 · 青云山下" in sys_content
    assert "通过试炼" in sys_content and "被迫离开青云宗" in sys_content
    assert "本章大纲位 · 第 3 章" in sys_content
    assert "宗门遇袭" in sys_content
    assert "以已写正文为准" in sys_content


def test_plan_messages_no_outline_no_section():
    msgs = prompts.plan_messages({}, None)
    assert "全书 Objective" not in msgs[0]["content"]


def test_write_messages_injects_outline_and_no_prev_opening():
    """write_messages：当前卷 + 本章大纲位 + 「开场扣住本大纲位」；不再注入上一章开头（hack 已废弃）。"""
    ctx = {
        "short_context": [{"kind": "prev_chapter_summary", "chapter": 2, "summary": "第二章摘要"}],
    }
    outline = {"volume": {"volume_seq": 1, "title": "第一卷 · 青云山下", "goal": "入宗立足",
                          "key_results": ["通过试炼"]},
               "current": {"seq": 3, "goal": "宗门惊变", "beats": ["遇袭"]}}
    msgs = prompts.write_messages(ctx, {}, outline=outline)
    sys_content = msgs[0]["content"]
    user_content = msgs[1]["content"]
    assert "当前卷 · 第一卷 · 青云山下" in sys_content
    assert "本章大纲位 · 第 3 章" in sys_content
    assert "宗门惊变" in sys_content
    assert "开场须扣住" in sys_content
    assert "prev_chapter_opening" not in user_content
    assert "严禁与之重复" not in user_content
    assert "清晨的雾气" not in user_content


# ---- 提示词契约（§11 InkOS 化）：未给故事线自推 + 细纲场景级 ----

def test_outline_prompt_contract():
    """SYSTEM_BOOK_OUTLINE 契约：作者未提供故事线时 Planner 自行推导；每章 beats 为场景级细纲。"""
    sys_outline = prompts.SYSTEM_BOOK_OUTLINE
    assert "自行推导" in sys_outline, "作者未提供【大致故事线】时须由 Planner 自推整书故事线"
    assert "章末钩子" in sys_outline, "每章 beats 须含章末钩子/悬念（场景级细纲）"
    assert "不得复述 goal" in sys_outline, "细纲不得复述本章 goal"
    assert "复用同一套路" in sys_outline, "开场/收尾节拍不得连续复用同一套路（§11 章节雷同根治）"


def test_write_prompt_opening_contract():
    """SYSTEM_WRITE 开头契约（§11）：从上一章结尾片段接续 + 天气不作万能开场 + 各章不共用开场景。"""
    sys_write = prompts.SYSTEM_WRITE
    assert "上一章结尾片段" in sys_write, "写章须从上一章结尾片段的具体情境接续展开"
    assert "作万能开场" in sys_write, "天色/时辰/天气不得作万能开场（相关时才可）"
    assert "不得与其他章共用开场景" in sys_write, "各章开头不得与其他章共用开场景/意象/句式"
    assert "唤醒" in sys_write, "不得以「醒来/被叫醒/睁眼/天亮」等被动唤醒作开场动作（§11 每章醒来→入睡框架根治）"
    assert "静止收束" in sys_write, "章末不得以「入睡/闭眼/原地等待」静止收束作结尾，须落剧情推进或悬念"


def test_plan_prompt_repetition_contract():
    """SYSTEM_PLAN 规则契约（§11）：开场不重复上一章、章末钩子非静止收束、历史相似事件只参照不照搬。"""
    sys_plan = prompts.SYSTEM_PLAN
    assert "开场节拍不得与上一章开场动作重复" in sys_plan, "连续以「被吵醒」开场被禁止"
    assert "静止收束" in sys_plan, "章末钩子不得是入睡/休息/原地等待"
    assert "照搬" in sys_plan, "【前情事件】相似事件仅供呼应/差异化参照，不得照搬桥段结构"
