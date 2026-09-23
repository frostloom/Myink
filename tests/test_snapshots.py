"""生成快照：选择性留存（静态素材只留哈希、动态素材留全文）与同键合并写入。

留存口径见 src/myink/snapshot.py；写入路径见 nodes.record_snapshot。纯投影部分不碰库，
写入部分用内存 sqlite 建一张 generation_snapshots（同 test_admin_observability 的做法）。
"""
from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from myink import snapshot
from myink.models import GenerationSnapshot
from myink.providers import ModelResponse
from myink.workflow import nodes


@pytest.fixture
def snapshot_db():
    engine = create_engine("sqlite:///:memory:")
    GenerationSnapshot.__table__.create(engine)
    with Session(engine, autoflush=False) as db:
        yield db


def _state(**overrides) -> dict:
    state = {"project_id": str(uuid.uuid4()), "task_id": "task-1", "chapter_seq": 3,
             "replan_count": 0}
    state.update(overrides)
    return state


def _rows(db) -> list[GenerationSnapshot]:
    db.flush()  # record_snapshot 只 add 不 flush，autoflush=False 时查询看不见待写入行
    return db.query(GenerationSnapshot).order_by(GenerationSnapshot.id).all()


# ---- 纯投影（不碰库）----

def test_sections_split_on_line_leading_labels():
    text = "模板前言\n\n【世界观硬约束】\nA\n【章节计划】\n{}\n"
    assert [s["name"] for s in snapshot.split_sections(text)] == [None, "世界观硬约束", "章节计划"]


def test_inline_label_mention_does_not_split():
    """正文里引用标签名（「见【近期上下文】中…」）不是节边界，否则节数会被撑爆。"""
    sections = snapshot.split_sections("见【近期上下文】中上一章结尾。\n【近期上下文】\n真内容\n")
    assert [s["name"] for s in sections] == [None, "近期上下文"]
    assert "见【近期上下文】" in sections[0]["text"]


def test_static_material_keeps_hash_instead_of_text():
    proj = snapshot.project_prompt([{"role": "system", "content": "前言\n【题材参考文档】\n很长的语料\n"}])
    section = proj["sections"][1]
    assert section["policy"] == "hash" and "text" not in section
    assert section["bytes"] == len("\n很长的语料\n".encode())
    assert section["sha256"] == hashlib.sha256("\n很长的语料\n".encode()).hexdigest()


def test_unknown_section_is_kept_in_full():
    """标签名不认识按 full 处理：新增的段不该因为规则没跟上就被丢掉。"""
    section = snapshot.project_prompt([{"role": "system", "content": "【新加的段】\n内容\n"}])["sections"][0]
    assert section["policy"] == "full" and "内容" in section["text"]


def test_section_over_cap_is_truncated_but_still_hashed():
    body = "\n" + "中" * 5000 + "\n"
    section = snapshot.project_prompt([{"role": "user", "content": "【章节计划】" + body}])["sections"][0]
    assert section["truncated"] and len(section["text"].encode()) <= snapshot.SECTION_BYTE_CAP
    assert section["bytes"] == len(body.encode())
    assert section["sha256"] == hashlib.sha256(body.encode()).hexdigest()


def test_prompt_budget_degrades_later_sections_to_hash():
    content = "".join(f"【第{i}段】\n" + "中" * 3900 + "\n" for i in range(10))
    proj = snapshot.project_prompt([{"role": "system", "content": content}])
    kept = sum(len(s.get("text", "").encode()) for s in proj["sections"])
    assert proj["truncated"] and kept <= snapshot.PROMPT_BYTE_BUDGET
    assert any(s.get("omitted") == "budget" and s["policy"] == "hash" for s in proj["sections"])


def test_recall_excerpt_prefers_content_over_provenance():
    """摘录要取 content；按最长字段取会挑到 source=project_settings 这种来源标记。"""
    rec = snapshot.project_recall({"long_term_facts": [
        {"fact_id": "f1", "content": "不得引入仙佛鬼神", "is_hard": True, "source": "project_settings"}]})
    fact = rec["groups"]["long_term_facts"][0]
    assert fact["excerpt"] == "不得引入仙佛鬼神"
    assert fact["is_hard"] and fact["source"] == "project_settings" and fact["fact_id"] == "f1"


def test_recall_keeps_empty_groups_as_zero():
    """「这一章没召回到设定实体」本身就是结论。"""
    rec = snapshot.project_recall({"entity_snapshots": []})
    assert rec["counts"] == {"entity_snapshots": 0} and rec["groups"]["entity_snapshots"] == []


def test_recall_stats_keep_scalars_and_dicts():
    rec = snapshot.project_recall({"token_usage": 12, "recall_stats": {"share": 0.3}})
    assert rec["stats"] == {"token_usage": 12, "recall_stats": {"share": 0.3}}


def test_output_projection_is_length_hash_and_excerpt():
    out = snapshot.project_output("正" * 900)
    assert out["bytes"] == 2700 and out["sha256"] == hashlib.sha256(("正" * 900).encode()).hexdigest()
    assert len(out["excerpt"]) == snapshot.OUTPUT_EXCERPT_CHARS


def test_finalize_scrubs_credentials_and_keeps_earlier_flags():
    first = snapshot.finalize({"prompt": {"sections": [{"text": "api_key=sk-abcdefgh1234"}]}})
    assert "sk-abcdefgh1234" not in json.dumps(first, ensure_ascii=False)
    assert first["_capture"]["redacted"] is True
    assert snapshot.finalize({"applied_spans": []}, previous=first)["_capture"]["redacted"] is True
    assert snapshot.finalize({"a": 1})["_capture"]["redacted"] is False


# ---- 写入路径（内存 sqlite）----

def test_write_snapshot_keeps_dynamic_sections_and_hashes_static_ones(snapshot_db):
    resp = ModelResponse(content="正文" * 10, model_id="m1", input_tokens=5, output_tokens=7,
                         duration_ms=120, cache_hit=True, retry_count=1)
    nodes.record_snapshot(snapshot_db, state=_state(), stage="write", resp=resp, messages=[
        {"role": "system", "content": "模板前言\n【题材参考文档】\n静态语料\n"
                                      "【文风要求（project_settings.style_profile）】\n第一人称\n"},
        {"role": "user", "content": "【章节计划】\n{\"goals\": []}\n"},
    ])
    row = _rows(snapshot_db)[0]
    sections = {s["name"]: s for s in row.payload["prompt"]["sections"]}
    assert sections["文风要求（project_settings.style_profile）"]["policy"] == "full"
    assert "第一人称" in sections["文风要求（project_settings.style_profile）"]["text"]
    assert sections["题材参考文档"]["policy"] == "hash" and "text" not in sections["题材参考文档"]
    assert row.payload["output"]["bytes"] == len(("正文" * 10).encode())
    assert row.payload["prompt"]["sections"][-1]["role"] == "user"
    assert (row.stage, row.attempt, row.chapter_seq) == ("write", 1, 3)
    assert (row.model_id, row.input_tokens, row.output_tokens, row.duration_ms) == ("m1", 5, 7, 120)
    assert row.cache_hit and row.retry_count == 1 and row.cost_est == resp.cost_est


def test_patch_snapshot_merges_applied_spans_into_the_prompt_row(snapshot_db):
    state = _state()
    nodes.record_snapshot(snapshot_db, state=state, stage="patch",
                          messages=[{"role": "user", "content": "【章节计划】\n{}\n"}],
                          resp=ModelResponse(content="补丁输出", model_id="m1"))
    nodes.record_snapshot(snapshot_db, state=state, stage="patch",
                          payload={"applied_spans": [{"target": "旧剑", "replacement": "青剑"}]})
    rows = _rows(snapshot_db)
    assert len(rows) == 1, "同键两笔写入必须合并成一行，不能把提示词那半挤掉"
    assert rows[0].payload["applied_spans"] == [{"target": "旧剑", "replacement": "青剑"}]
    assert rows[0].payload["prompt"]["sections"][0]["text"].strip() == "{}"
    assert rows[0].payload["output"]["excerpt"] == "补丁输出"


def test_same_stage_rerun_keeps_one_row_per_plan_version(snapshot_db):
    state = _state()
    nodes.record_snapshot(snapshot_db, state=state, stage="plan_chapter",
                          messages=[{"role": "user", "content": "【第一版】\nA\n"}])
    nodes.record_snapshot(snapshot_db, state=state, stage="plan_chapter",
                          messages=[{"role": "user", "content": "【第二版】\nB\n"}])
    rows = _rows(snapshot_db)
    assert len(rows) == 1 and rows[0].payload["prompt"]["sections"][0]["name"] == "第二版"
    # 重规划是新版本，另起一行：两版输入要能并排比对
    nodes.record_snapshot(snapshot_db, state={**state, "replan_count": 1}, stage="plan_chapter",
                          messages=[{"role": "user", "content": "【重规划版】\nC\n"}])
    rows = _rows(snapshot_db)
    assert [r.attempt for r in rows] == [1, 2]


def test_snapshot_skips_unstaged_nodes_and_missing_keys(snapshot_db):
    nodes.record_snapshot(snapshot_db, state=_state(), stage="extract",
                          messages=[{"role": "user", "content": "x"}])
    nodes.record_snapshot(snapshot_db, state=_state(task_id=None), stage="write",
                          messages=[{"role": "user", "content": "x"}])
    nodes.record_snapshot(snapshot_db, state=_state(chapter_seq=None), stage="write",
                          messages=[{"role": "user", "content": "x"}])
    assert _rows(snapshot_db) == []


def test_snapshot_payload_scrubs_credentials(snapshot_db):
    nodes.record_snapshot(snapshot_db, state=_state(), stage="write", resp=ModelResponse(
        content="Bearer LEAK-SECRET", model_id="m1"), messages=[
        {"role": "system", "content": "【文风要求（project_settings.style_profile）】\napi_key=sk-abcdefgh1234\n"}])
    row = _rows(snapshot_db)[0]
    encoded = json.dumps(row.payload, ensure_ascii=False)
    assert "sk-abcdefgh1234" not in encoded and "LEAK-SECRET" not in encoded
    assert row.payload["_capture"]["redacted"] is True
