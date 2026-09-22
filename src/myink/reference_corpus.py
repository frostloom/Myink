"""题材参考语料（third_party/webnovel-writer，原样收录）的定位与读取。

来源与许可见 NOTICE.md。这一层只管磁盘：题材名 → 文档相对路径、按小节切片、
按字符数截断。谁读它（Writer 的只读工具、提示词里的文档指针）都不在这里决定。

语料是只读文件、不进 DB，所以「路径穿越」和「体积上限」得自己扛：resolve() 之后
断言落在语料根之内（符号链接一并被解析掉），再按字符数截断——单份题材模板 3–8KB
能整份读完，素材 CSV 近百 KB 则必然截断，靠 section 分次读。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

CORPUS_ROOT = Path(__file__).resolve().parent / "third_party" / "webnovel-writer"

# 单次读取返回的字符上限（约合 6–8k token，控上下文）
MAX_READ_CHARS = 12000
GENRE_TEMPLATE_DIR = "templates/genres"

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.M)


def corpus_files() -> list[tuple[str, int]]:
    """语料内全部文件的 (相对路径, 字节数)。语料未安装时返回空表。"""
    if not CORPUS_ROOT.is_dir():
        return []
    return [
        (p.relative_to(CORPUS_ROOT).as_posix(), p.stat().st_size)
        for p in sorted(CORPUS_ROOT.rglob("*"))
        if p.is_file()
    ]


def genre_template_path(name: str | None) -> str | None:
    """题材名 → 该题材模板的相对路径；语料里没有同名模板则 None。"""
    genre = str(name or "").strip()
    if not genre or "/" in genre or "\\" in genre:
        return None
    rel = f"{GENRE_TEMPLATE_DIR}/{genre}.md"
    return rel if (CORPUS_ROOT / rel).is_file() else None


def markdown_sections(text: str, max_level: int = 6) -> list[str]:
    """文档里到 max_level 为止的标题文字。列清单时用 max_level=2：
    只给可独立选取的一级小节，`###` 子标题列进去只会把清单撑长。
    """
    return [m.group(2) for m in _HEADING.finditer(text) if len(m.group(1)) <= max_level]


def slice_section(text: str, section: str) -> str | None:
    """取某个小节：从匹配的标题起，到下一个同级或更高级标题为止。"""
    heads = list(_HEADING.finditer(text))
    key = section.strip()
    for i, head in enumerate(heads):
        if key not in head.group(2):
            continue
        level = len(head.group(1))
        end = len(text)
        for nxt in heads[i + 1:]:
            if len(nxt.group(1)) <= level:
                end = nxt.start()
                break
        return text[head.start():end].strip()
    return None


def sections_of(rel: str) -> list[str]:
    """某份文档的小节标题清单；不存在或读不动时返回空表。

    语料是随版本发布的只读快照，进程内缓存即可（运行期不会变）。
    """
    return _sections_of(rel)


@lru_cache(maxsize=256)
def _sections_of(rel: str) -> list[str]:
    try:
        text = (CORPUS_ROOT / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return markdown_sections(text, max_level=2)


def read_reference(rel: str, section: str | None = None) -> dict:
    """读一份参考文档。返回 dict（含错误情形），不抛异常。

    路径越界、文件不存在、小节不存在都返回带 `error` 的 dict，由调用方决定怎么呈现。
    """
    files = corpus_files()
    if not files:
        return {"error": "题材参考语料未安装"}
    if not rel:
        return {
            "file_count": len(files),
            "files": [{"path": k, "bytes": n} for k, n in files[:80]],
            "hint": "用 path 读具体文件；markdown 可再用 section 只读一节，避免整份读。",
        }
    root = CORPUS_ROOT.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return {"error": f"没有这个参考文档：{rel}", "hint": "不传 path 可列出全部文档。"}
    text = target.read_text(encoding="utf-8", errors="replace")
    total = len(text)
    key = str(section or "").strip()
    if key:
        sliced = slice_section(text, key)
        if sliced is None:
            return {"error": f"{rel} 里没有小节「{key}」",
                    "sections": markdown_sections(text, max_level=2)}
        text = sliced
    out: dict = {"path": rel, "total_chars": total, "content": text[:MAX_READ_CHARS]}
    if len(text) > MAX_READ_CHARS:
        out["truncated"] = True
        out["note"] = f"只返回前 {MAX_READ_CHARS} 字；用 section 取某一节，别整份要。"
    return out


__all__ = [
    "CORPUS_ROOT", "MAX_READ_CHARS", "GENRE_TEMPLATE_DIR",
    "corpus_files", "genre_template_path", "markdown_sections", "slice_section",
    "sections_of", "read_reference",
]
