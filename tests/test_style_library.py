"""账号级文风库：表形状 + 端点（端点部分在后一个任务补齐）。"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.exc import IntegrityError

from conftest import identity_headers
from myink.api.main import app
from myink.db import ensure_user_environment, new_session
from myink.models import AgentRun, StyleLibraryItem, User
from myink.providers.base import ModelProvider, ModelResponse

# 建表是幂等的；不调它，单独跑本模块时 accounts 的 environment 列可能还没补上。
ensure_user_environment()
client = TestClient(app)

_BUILTIN_IDS = {"builtin:xianxia-jiuzhou", "builtin:changan-yexing",
                "builtin:xingjian-yuanzheng", "builtin:dushi-yiguan"}


def test_style_library_item_roundtrip():
    with new_session() as db:
        user = User(username=f"style-{uuid.uuid4().hex[:8]}")
        db.add(user)
        db.commit()
        uid = user.id
    try:
        with new_session() as db:
            item = StyleLibraryItem(user_id=uid, name="渡口冷白描",
                                    profile={"pov": "第三人称限知"}, sample_chars=3200)
            db.add(item)
            db.commit()
            item_id = item.id
        with new_session() as db:
            row = db.scalar(select(StyleLibraryItem).where(StyleLibraryItem.id == item_id))
            assert row is not None
            assert row.name == "渡口冷白描"
            assert row.profile["pov"] == "第三人称限知"
            assert row.sample_chars == 3200
    finally:
        with new_session() as db:
            db.execute(sa_delete(StyleLibraryItem).where(StyleLibraryItem.user_id == uid))
            db.execute(sa_delete(User).where(User.id == uid))
            db.commit()


def test_style_library_has_no_project_id_column():
    """账号级表不能有 project_id 列。

    db.enable_row_level_security() 会给任何带 project_id 的表套 FORCE RLS +
    tenant_isolation 策略；账号级查询没设 app.tenant_id，会被策略静默过滤成空。
    """
    assert "project_id" not in StyleLibraryItem.__table__.columns


def test_style_library_item_note_roundtrip():
    with new_session() as db:
        user = User(username=f"style-{uuid.uuid4().hex[:8]}")
        db.add(user)
        db.commit()
        uid = user.id
    try:
        with new_session() as db:
            item = StyleLibraryItem(user_id=uid, name="渡口冷白描", note="渡口那篇的冷白描",
                                    profile={"pov": "第三人称限知"}, sample_chars=3200)
            db.add(item)
            db.commit()
            item_id = item.id
        with new_session() as db:
            row = db.scalar(select(StyleLibraryItem).where(StyleLibraryItem.id == item_id))
            assert row is not None
            assert row.note == "渡口那篇的冷白描"
        with new_session() as db:
            plain = StyleLibraryItem(user_id=uid, name="没备注的档",
                                     profile={}, sample_chars=100)
            db.add(plain)
            db.commit()
            plain_id = plain.id
        with new_session() as db:
            row = db.scalar(select(StyleLibraryItem).where(StyleLibraryItem.id == plain_id))
            assert row is not None
            assert row.note == ""
    finally:
        with new_session() as db:
            db.execute(sa_delete(StyleLibraryItem).where(StyleLibraryItem.user_id == uid))
            db.execute(sa_delete(User).where(User.id == uid))
            db.commit()


def test_style_library_duplicate_name_rejected():
    """同一 user 下重名不能落库：唯一约束在 (user_id, name) 上。"""
    with new_session() as db:
        user = User(username=f"style-{uuid.uuid4().hex[:8]}")
        db.add(user)
        db.commit()
        uid = user.id
    try:
        with new_session() as db:
            db.add(StyleLibraryItem(user_id=uid, name="重名档", profile={}, sample_chars=10))
            db.commit()
        with new_session() as db:
            db.add(StyleLibraryItem(user_id=uid, name="重名档", profile={}, sample_chars=20))
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()
    finally:
        with new_session() as db:
            db.execute(sa_delete(StyleLibraryItem).where(StyleLibraryItem.user_id == uid))
            db.execute(sa_delete(User).where(User.id == uid))
            db.commit()


class _StyleStub(ModelProvider):
    def __init__(self, payload: dict | None = None, *, raw: str | None = None, raise_error: bool = False):
        self._payload, self._raw, self._raise_error, self.calls = payload, raw, raise_error, 0

    def name(self) -> str:
        return "style-stub"

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False,
                 tools=None, disable_thinking=False):
        self.calls += 1
        if self._raise_error:
            raise RuntimeError("provider down")
        content = self._raw if self._raw is not None else json.dumps(self._payload or {}, ensure_ascii=False)
        return ModelResponse(content=content, model_id=model_id, input_tokens=10, output_tokens=20)


@pytest.fixture
def style_stub(monkeypatch):
    import myink.providers as providers_mod

    def _install(payload=None, *, raw=None, raise_error=False) -> _StyleStub:
        stub = _StyleStub(payload, raw=raw, raise_error=raise_error)
        monkeypatch.setattr(providers_mod, "default_provider", stub)
        return stub

    return _install


def test_get_returns_the_four_builtins_first(temp_user):
    with new_session() as db:
        db.add(StyleLibraryItem(user_id=uuid.UUID(temp_user), name="渡口冷白描",
                                profile={"pov": "限知"}, sample_chars=1200))
        db.commit()
    items = client.get("/api/v1/style-library", headers=identity_headers(temp_user)).json()["items"]
    builtins, mine = items[:4], items[4:]
    assert {item["id"] for item in builtins} == _BUILTIN_IDS
    assert all(item["builtin"] and not item["removable"] and item["created_at"] is None
               for item in builtins)
    assert [item["name"] for item in mine] == ["渡口冷白描"]
    assert mine[0]["builtin"] is False and mine[0]["removable"] is True


def test_save_round_trips_the_note(temp_user):
    created = client.post("/api/v1/style-library",
                          json={"name": "渡口冷白描", "profile": {"pov": "限知"},
                                "note": "冷白描，少形容", "sample_chars": 1200},
                          headers=identity_headers(temp_user))
    assert created.status_code == 200, created.text
    assert created.json()["note"] == "冷白描，少形容"
    items = client.get("/api/v1/style-library", headers=identity_headers(temp_user)).json()["items"]
    assert [i for i in items if not i["builtin"]][0]["note"] == "冷白描，少形容"


def test_crud_is_scoped_to_the_owner(temp_user):
    """内置预设对每个账号都在，所以隔离断言只看「自己的项」。"""
    with new_session() as db:
        other = User(username=f"style-{uuid.uuid4().hex[:8]}")
        db.add(other)
        db.commit()
        other_id = other.id
    try:
        created = client.post("/api/v1/style-library",
                              json={"name": "渡口冷白描", "profile": {"pov": "限知"}, "sample_chars": 1200},
                              headers=identity_headers(temp_user))
        assert created.status_code == 200, created.text
        item_id = created.json()["id"]

        peer = client.get("/api/v1/style-library", headers=identity_headers(other_id)).json()["items"]
        assert [i for i in peer if not i["builtin"]] == []
        # 删别人的：不能删掉，也不能借 404 反推 id 存在
        assert client.delete(f"/api/v1/style-library/{item_id}",
                             headers=identity_headers(other_id)).status_code == 404
        assert client.delete(f"/api/v1/style-library/{item_id}",
                             headers=identity_headers(temp_user)).status_code == 200
        left = client.get("/api/v1/style-library", headers=identity_headers(temp_user)).json()["items"]
        assert [i for i in left if not i["builtin"]] == []
    finally:
        with new_session() as db:
            db.execute(sa_delete(StyleLibraryItem).where(StyleLibraryItem.user_id == other_id))
            db.execute(sa_delete(User).where(User.id == other_id))
            db.commit()


def test_rejects_a_duplicate_name(temp_user):
    """重名必须 409，不能靠唯一约束崩成 500。"""
    body = {"name": "渡口冷白描", "profile": {"pov": "限知"}, "sample_chars": 10}
    assert client.post("/api/v1/style-library", json=body,
                       headers=identity_headers(temp_user)).status_code == 200
    again = client.post("/api/v1/style-library", json=body, headers=identity_headers(temp_user))
    assert again.status_code == 409
    assert again.json()["detail"] == "NAME_TAKEN"


def test_delete_of_a_builtin_or_a_stranger_is_404(temp_user):
    assert client.delete("/api/v1/style-library/builtin:xianxia-jiuzhou",
                         headers=identity_headers(temp_user)).status_code == 404
    assert client.delete(f"/api/v1/style-library/{uuid.uuid4()}",
                         headers=identity_headers(temp_user)).status_code == 404


def test_extract_needs_at_least_one_non_blank_sample(temp_user):
    resp = client.post("/api/v1/style-library/samples", json={"samples": ["   "]},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 400


def test_save_rejects_a_blank_name(temp_user):
    resp = client.post("/api/v1/style-library",
                       json={"name": "   ", "profile": {}, "sample_chars": 0},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 400


def test_save_rejects_a_non_dict_profile(temp_user):
    resp = client.post("/api/v1/style-library",
                       json={"name": "渡口", "profile": "不是对象", "sample_chars": 0},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 422                      # pydantic 在进 handler 前就挡了
    items = client.get("/api/v1/style-library", headers=identity_headers(temp_user)).json()["items"]
    assert [i for i in items if not i["builtin"]] == []  # 确认没落库


def test_extract_records_an_account_level_run(temp_user, style_stub):
    """没有作品的提取也要记账，且归属到账号（agent_runs.user_id）。"""
    style_stub({"pov": "第三人称限知"})
    resp = client.post("/api/v1/style-library/samples",
                       json={"samples": ["渡口的老人守着最后一班船。"]},
                       headers=identity_headers(temp_user))
    assert resp.status_code == 200, resp.text
    with new_session() as db:
        row = db.scalar(select(AgentRun).where(AgentRun.user_id == uuid.UUID(temp_user)))
    assert row is not None and row.node == "style_extract" and row.project_id is None
