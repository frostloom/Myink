"""用户反馈：提交（描述 + 图片/视频附件）、体积与类型闸门、归属隔离、管理端列表与状态。

需要一个活库（DATABASE_URL/ADMIN_DATABASE_URL，见 .local/env-test.sh）。附件写盘目录被
换成 pytest 的 tmp_path，既不污染仓库也不受并发运行影响。
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from myink.api import auth
from myink.api import routes_feedback
from myink.api.main import app
from myink.config import settings
from myink.db import get_admin_engine, new_session
from myink.models import Feedback, User

client = TestClient(app, raise_server_exceptions=False)
PREFIX = "/api/v1/feedback"
ADMIN_PREFIX = "/api/v1/admin/feedback"


def _token(user: User) -> str:
    return auth.create_access_token(user.id, auth_version=user.auth_version)


def bearer(user: User) -> dict[str, str]:
    return {"Authorization": "Bearer " + _token(user)}


@pytest.fixture
def people(tmp_path, monkeypatch):
    """两个普通账号 + 一个管理员；附件目录指向 tmp_path。"""
    monkeypatch.setattr(routes_feedback, "settings", replace(settings, feedback_dir=str(tmp_path)))
    Feedback.__table__.create(get_admin_engine(), checkfirst=True)
    tag = uuid.uuid4().hex
    with new_session() as db:
        owner = User(username=f"fb-owner-{tag}", role="user")
        other = User(username=f"fb-other-{tag}", role="user")
        admin = User(username=f"fb-admin-{tag}", role="admin")
        db.add_all([owner, other, admin])
        db.commit()
    try:
        yield owner, other, admin
    finally:
        with new_session() as db:
            db.query(Feedback).filter(Feedback.user_id.in_([owner.id, other.id, admin.id])).delete()
            db.query(User).filter(User.id.in_([owner.id, other.id, admin.id])).delete()
            db.commit()


def _submit(user: User, description="生成时第 3 章卡住了", **over):
    body = {"description": description, "category": over.pop("category", "bug"),
            "contact": over.pop("contact", ""), "page_url": over.pop("page_url", "/long")}
    return client.post(PREFIX, data=body, headers=bearer(user), **over)


def _png() -> tuple[str, bytes, str]:
    # 内容不是真 PNG：路由只认 mime 与体积，不解析图片，这正是要测的边界
    return ("现场截图.png", b"\x89PNG\r\n\x1a\n" + b"x" * 64, "image/png")


def test_text_only_submission_and_own_list(people):
    owner, _, _ = people
    created = _submit(owner)
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["status"] == "open"
    assert payload["category"] == "bug"
    assert payload["attachments"] == []
    assert payload["description"] == "生成时第 3 章卡住了"

    mine = client.get(PREFIX, headers=bearer(owner))
    assert mine.status_code == 200, mine.text
    ids = [row["id"] for row in mine.json()["items"]]
    assert payload["id"] in ids


def test_image_and_video_attachments_round_trip(people, tmp_path):
    owner, _, _ = people
    created = client.post(
        PREFIX,
        data={"description": "上传后播放器黑屏", "category": "bug", "contact": "me@example.com"},
        files=[
            ("files", _png()),
            ("files", ("复现.mp4", b"\x00\x00\x00\x18ftypmp42" + b"v" * 128, "video/mp4")),
        ],
        headers=bearer(owner),
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert [a["name"] for a in payload["attachments"]] == ["现场截图.png", "复现.mp4"]
    assert [a["index"] for a in payload["attachments"]] == [0, 1]
    assert payload["attachments"][1]["mime"] == "video/mp4"
    assert payload["contact"] == "me@example.com"

    folder = tmp_path / payload["id"]
    assert len(list(folder.iterdir())) == 2  # 字节确实落盘

    got = client.get(f"{PREFIX}/{payload['id']}/attachments/1", headers=bearer(owner))
    assert got.status_code == 200, got.text
    assert got.headers["content-type"] == "video/mp4"
    assert got.headers["cache-control"] == "private, no-store"
    assert got.content.startswith(b"\x00\x00\x00\x18ftypmp42")


def test_oversize_attachment_is_rejected_and_disk_is_cleaned(people, tmp_path, monkeypatch):
    owner, _, _ = people
    monkeypatch.setattr(
        routes_feedback, "settings",
        replace(settings, feedback_dir=str(tmp_path), feedback_video_max_bytes=32),
    )
    rejected = client.post(
        PREFIX,
        data={"description": "大文件"},
        files=[("files", ("大.mp4", b"v" * 4096, "video/mp4"))],
        headers=bearer(owner),
    )
    assert rejected.status_code == 400, rejected.text
    assert "ATTACHMENT_TOO_LARGE" in rejected.json()["detail"]
    # 半个文件与空目录都不该留下：库里没有这条反馈，盘上也不该有
    assert list(tmp_path.iterdir()) == []


def test_bad_mime_and_empty_description_and_too_many_files(people, monkeypatch):
    owner, _, _ = people
    bad = client.post(
        PREFIX, data={"description": "x"},
        files=[("files", ("x.exe", b"MZ", "application/x-msdownload"))],
        headers=bearer(owner),
    )
    assert bad.status_code == 400, bad.text
    assert "UNSUPPORTED_MEDIA_TYPE" in bad.json()["detail"]

    blank = client.post(PREFIX, data={"description": "   "}, headers=bearer(owner))
    assert blank.status_code == 400, blank.text

    monkeypatch.setattr(routes_feedback, "settings", replace(settings, feedback_max_files=1))
    many = client.post(
        PREFIX, data={"description": "两个附件"},
        files=[("files", _png()), ("files", _png())],
        headers=bearer(owner),
    )
    assert many.status_code == 400, many.text
    assert "TOO_MANY_FILES" in many.json()["detail"]


def test_attachment_is_owner_scoped_admin_exempt(people):
    owner, other, admin = people
    created = client.post(
        PREFIX, data={"description": "带图"}, files=[("files", _png())], headers=bearer(owner),
    )
    fid = created.json()["id"]
    assert client.get(f"{PREFIX}/{fid}/attachments/0", headers=bearer(other)).status_code == 404
    assert client.get(f"{PREFIX}/{fid}/attachments/0", headers=bearer(admin)).status_code == 200
    # 越界下标同样 404，而不是 500
    assert client.get(f"{PREFIX}/{fid}/attachments/9", headers=bearer(owner)).status_code == 404

    assert [r["id"] for r in client.get(PREFIX, headers=bearer(other)).json()["items"]] == []


def test_admin_list_and_status_transition(people):
    owner, other, admin = people
    created = _submit(owner, description="管理端要能看到这条", category="suggestion")
    fid = created.json()["id"]

    assert client.get(ADMIN_PREFIX, headers=bearer(other)).status_code == 403

    listing = client.get(ADMIN_PREFIX + "?limit=100", headers=bearer(admin))
    assert listing.status_code == 200, listing.text
    row = next((r for r in listing.json()["items"] if r["id"] == fid), None)
    assert row is not None
    assert row["username"] == owner.username  # 管理端要看得见是谁提的
    assert row["category"] == "suggestion"

    patched = client.patch(f"{ADMIN_PREFIX}/{fid}", json={"status": "resolved"}, headers=bearer(admin))
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "resolved"
    with new_session() as db:
        assert db.scalar(select(Feedback.status).where(Feedback.id == uuid.UUID(fid))) == "resolved"

    assert client.patch(
        f"{ADMIN_PREFIX}/{fid}", json={"status": "closed"}, headers=bearer(admin)
    ).status_code == 400
    assert client.patch(
        f"{ADMIN_PREFIX}/{fid}", json={"status": "resolved"}, headers=bearer(owner)
    ).status_code == 403
