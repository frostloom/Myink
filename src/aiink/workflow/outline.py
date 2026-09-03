"""整书大纲形状归一（§11）：旧版 {arc, chapters} 扁平形状 → 新版 {objective, volumes} 三层。

历史数据：整书大纲初版是「主线弧 + 逐章」扁平骨架（无卷层），存量大纲可能仍是该形状。
读取/注入前统一归一为新三层（旧章并入「全书主线」单卷），保证前端展示与写作注入对新旧数据一致。
"""

from __future__ import annotations


def normalize_outline(outline: dict | None) -> dict | None:
    """整书大纲归一：新版三层原样返回；旧版扁平 {arc, chapters} 并入单卷；无法识别原样返回。"""
    if not isinstance(outline, dict):
        return None
    volumes = outline.get("volumes")
    if isinstance(volumes, list):
        return outline  # 已是新三层形状
    chapters = outline.get("chapters")
    if not isinstance(chapters, list):
        return outline  # 无法识别 → 原样返回（调用方各自容错）
    return {
        **{k: v for k, v in outline.items() if k not in ("arc", "chapters")},
        "objective": "",
        "volumes": [
            {
                "volume_seq": 1,
                "title": "全书主线",
                "theme": "",
                "goal": "",
                "key_results": [],
                "end_event": "",
                "chapters": [c for c in chapters if isinstance(c, dict)],
            }
        ],
    }
