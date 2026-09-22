"""题材参考语料：定位、小节切片、路径穿越加固、读取上限。

纯文件系统，不碰 DB——语料是随包发布的只读快照（见 NOTICE.md）。
"""

from __future__ import annotations

import json
from pathlib import Path

from myink.genre_catalog import PACKS, reference_hint
from myink.reference_corpus import (
    CORPUS_ROOT,
    MAX_READ_CHARS,
    corpus_files,
    genre_template_path,
    markdown_sections,
    read_reference,
    sections_of,
)


def test_corpus_is_installed():
    files = dict(corpus_files())
    assert len(files) >= 78, f"语料未安装或不完整：{CORPUS_ROOT}"
    assert len([p for p in files if p.startswith("templates/genres/")]) == 37
    # GPL-3 §5：分发时须随附许可全文
    assert (CORPUS_ROOT / "LICENSE").is_file()


def test_every_pack_has_a_template():
    """reference_hint 靠 pack 的中文名找模板；哪个题材没有同名模板，指针就静默变空。"""
    assert [pid for pid, p in PACKS.items() if genre_template_path(p["name"]) is None] == []


def test_genre_template_path_resolves_and_rejects():
    assert genre_template_path("修仙") == "templates/genres/修仙.md"
    assert genre_template_path("不存在的题材") is None
    assert genre_template_path("") is None
    assert genre_template_path(None) is None
    # 名字里带路径分隔符的，在拼路径之前就被挡掉
    assert genre_template_path("../../etc/passwd") is None
    assert genre_template_path("..\\..\\win.ini") is None


def test_index_lists_files_when_path_absent():
    got = read_reference("")
    assert got["file_count"] == len(corpus_files())
    assert any(f["path"].endswith("修仙.md") for f in got["files"])


def test_reads_a_template():
    got = read_reference("templates/genres/修仙.md")
    assert got["path"] == "templates/genres/修仙.md"
    assert got["total_chars"] > 0
    assert "修仙" in got["content"]
    assert "truncated" not in got


def test_section_slice_narrows_the_read():
    full = read_reference("templates/genres/修仙.md")["content"]
    part = read_reference("templates/genres/修仙.md", "大纲结构")
    assert "大纲结构" in part["content"]
    assert len(part["content"]) < len(full)
    # 只该拿到这一节：前一节的内容不能跟进来
    assert "核心流派细分" not in part["content"]


def test_unknown_section_lists_available_sections():
    got = read_reference("templates/genres/修仙.md", "根本没有这一节")
    assert "error" in got
    assert "大纲结构" in "".join(got["sections"])


def test_path_traversal_is_refused():
    """语料根之外存在的文件也不能读到——这才是真的在测防线，不是测文件不存在。"""
    outside = "../../../../pyproject.toml"
    assert (CORPUS_ROOT / outside).resolve().is_file()
    for bad in (outside, "../pyproject.toml", "templates/../../README.md"):
        got = read_reference(bad)
        assert "error" in got, bad


def test_missing_file_reports_error():
    assert "error" in read_reference("templates/genres/没有这个.md")


def test_big_table_is_truncated():
    """近百 KB 的素材表必然超上限；截断要显式告知，不能静默丢内容。"""
    big = max(corpus_files(), key=lambda kv: kv[1])[0]
    got = read_reference(big)
    assert got["truncated"] is True
    assert len(got["content"]) == MAX_READ_CHARS
    assert got["note"]


def test_package_data_covers_every_corpus_file():
    """漏进 wheel 的语料 = 镜像里 read_genre_reference 直接读不到。

    这条是补出来的：第一版 patterns 只写了 `references/*.md`，
    `references/*.json` 两个文件静默漏掉，只有真去 build 一次 wheel 才看得见。
    """
    import tomllib
    from pathlib import PurePosixPath

    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = pyproject["tool"]["setuptools"]["package-data"]["myink"]

    uncovered = [
        rel for rel, _ in corpus_files()
        if not any(PurePosixPath(f"third_party/webnovel-writer/{rel}").match(p) for p in patterns)
    ]
    assert uncovered == [], f"这些语料文件进不了包：{uncovered}"


def test_sections_list_is_top_level_only():
    """清单只列到 ##：### 子标题列进去会把提示词撑长。"""
    text = (CORPUS_ROOT / "templates/genres/修仙.md").read_text(encoding="utf-8")
    assert "凡人流 (Mortal)" in markdown_sections(text, max_level=6)
    assert "凡人流 (Mortal)" not in sections_of("templates/genres/修仙.md")


def test_reference_hint_points_at_this_books_template():
    hint = reference_hint(PACKS["xiuxian"])
    assert "templates/genres/修仙.md" in hint
    assert "read_genre_reference" in hint
    assert "大纲结构" in hint
    # 没对应模板时给空串，调用方据此整段不注入
    assert reference_hint({"name": "不存在的题材"}) == ""
    assert reference_hint(None) == ""


def test_tool_is_registered_and_dispatches():
    """走工具注册表：project_id 由服务端绑定，语料读取不依赖它，传 None 也能读。"""
    from myink.workflow.tools import TOOL_SCHEMAS, execute_tool

    assert "read_genre_reference" in [t["function"]["name"] for t in TOOL_SCHEMAS]
    got = json.loads(execute_tool(None, None, "read_genre_reference",
                                  {"path": "templates/genres/修仙.md"}))
    assert "修仙" in got["content"]
    bad = json.loads(execute_tool(None, None, "read_genre_reference",
                                  {"path": "../../../../pyproject.toml"}))
    assert "error" in bad


def test_write_prompt_carries_the_pointer():
    """写章提示词只带路径与小节，不带正文——正文由 Writer 自己按需取。"""
    from myink.workflow.prompts import write_messages

    msgs = write_messages({}, {"chapter": 1}, genre_pack=PACKS["xiuxian"])
    system = msgs[0]["content"]
    assert "【题材参考文档】" in system
    assert "templates/genres/修仙.md" in system
    # 模板正文没被整份塞进来
    assert "黑暗森林法则" not in system

    # 没选题材时不注入这一段
    plain = write_messages({}, {"chapter": 1})
    assert "【题材参考文档】" not in plain[0]["content"]
