"""Python API 读端点测试（2026-08-09，前端接入暴露的契约回归）。

list_chapters 曾引用 Chapter 模型不存在的 target_words → 真实 API 500
（Go 网关测试用假 Python 服务测不到，前端接真 API 才暴露）。
回归：章节列表返回可序列化、字段合法。
"""

from __future__ import annotations

from aiink.api.main import list_chapters, list_projects


def test_list_projects_returns_books():
    """项目列表返回多本（seed 补建示例书后 demo 用户 ≥3 本）。"""
    projects = list_projects()
    assert len(projects) >= 3, f"应有多本（示例书已补建），实际 {len(projects)}"
    titles = {p["title"] for p in projects}
    assert "九州问天" in titles and "长安夜行" in titles and "星舰远征" in titles


def test_list_chapters_fields_valid(project_id):
    """章节列表字段合法（回归：target_words 曾致 500）。"""
    chapters = list_chapters(project_id)
    assert isinstance(chapters, list)
    for c in chapters:
        assert "chapter_seq" in c and "status" in c and "id" in c
        assert "target_words" not in c, "target_words 是 Project 字段，章节列表不应携带"
