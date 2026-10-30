"""节点级自修复重试（§6.12 调用层兜底第 4 档）：非法 JSON / 空正文 / 跑偏时重发 + 修正指令。

用户实测（2026-08-22）：`plan_chapter 输出解析失败`、`DeepSeek 返回空白/空内容` 把整章
一次判死。补 `_llm_checked`：check(content) 抛异常 → 追加 system 修正指令重发（默认重试
2 次）；resp.error 直接透传不重试（降级链已用尽，且 test_flow BatchFailStub 语义不能被吃）。

模式：monkeypatch `nodes._llm`（test_autocard 同款桩），返回坏→好序列，验证重试机制；
再经真实 `node_plan_chapter`（temp_project）验证节点级重试落回 {"plan": ...}。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from myink.workflow import nodes

_PLAN = {
    "goals": ["查明玉佩异动"],
    "scenes": [],
    "characters": [],
    "hooks_to_plant": [],
    "hooks_to_resolve": [],
    "expected_events": ["玉佩示警"],
    "hard_constraints": [],
}


def _queued_llm(monkeypatch, contents):
    """mock nodes._llm：按队列依次返回 content（或 Exception → resp.error），记录次数与 messages。

    content 与 _llm 桩的 __getitem__ 对齐——第 1 次取 contents[0]，重试取后续，越界报错
    （测「不该重试却重试」）。
    """
    calls = {"n": 0, "messages": []}

    def fake_llm(db, state, node, role, chain, messages, **kw):
        calls["n"] += 1
        calls["messages"].append(messages)
        item = contents[calls["n"] - 1]
        if isinstance(item, Exception):
            resp = SimpleNamespace(error=str(item), content="")
        else:
            resp = SimpleNamespace(error=None, content=item)
        return resp, []

    monkeypatch.setattr(nodes, "_llm", fake_llm)
    return calls


def test_llm_checked_retries_parse_failure_then_succeeds(monkeypatch):
    """解析失败 → 第 2 次带修正指令重发 → 成功返回（一次坏输出不再判死整章）。"""
    calls = _queued_llm(monkeypatch, ["not json{{", json.dumps(_PLAN, ensure_ascii=False)])

    def _check(content):
        return json.loads(content)["goals"]

    _, _, result, err = nodes._llm_checked(
        None, {"project_id": "x"}, "plan_chapter", "Planner", None,
        [{"role": "user", "content": "u"}], check=_check)
    assert err is None and result == _PLAN["goals"]
    assert calls["n"] == 2
    assert calls["messages"][1][-1]["role"] == "user"
    assert "未通过 JSON" in calls["messages"][1][-1]["content"], "重试应追加 JSON 修正指令"
    assert calls["messages"][1][-2] == {"role": "assistant", "content": "not json{{"}, \
        "JSON 重试必须带回上一版错误输出，才能定点修复而不是从头重复规划"


def test_llm_checked_all_fail_returns_error_at_limit(monkeypatch):
    """始终解析失败 → 初始 + 重试 max_attempts 次后 error 带次数与末次 content 片段。"""
    calls = _queued_llm(monkeypatch, ["bad{{{", "worse{{{", "nope"])

    def _check_json(content):
        return json.loads(content)["ok"]  # 三个输出都非法 → 每次都抛

    _, _, result, err = nodes._llm_checked(
        None, {"project_id": "x"}, "write", "Writer", None,
        [{"role": "user", "content": "u"}], check=_check_json,
        json_mode=False, corrective="请重输出正文。")
    assert result is None
    assert err is not None and "write 输出多次不合格（已重试 2 次）" in err
    assert "content[:120]=" in err, "最终失败应带末次 content 片段供排查"
    assert calls["n"] == 3, "初始 1 次 + 重试 2 次（_LLM_CHECK_RETRIES=2）"


def test_llm_checked_passthrough_resp_error_no_retry(monkeypatch):
    """resp.error 直接透传、不重试（降级链已用尽；BatchFailStub「失败一次→批次失败」语义不被吃掉）。"""
    calls = _queued_llm(monkeypatch, [RuntimeError("provider down")])
    _, _, result, err = nodes._llm_checked(
        None, {"project_id": "x"}, "plan_chapter", "Planner", None,
        [{"role": "user", "content": "u"}], check=lambda c: c)
    assert err == "provider down" and result is None
    assert calls["n"] == 1, "resp.error 不应触发节点级重试"


def test_llm_checked_text_mode_default_corrective(monkeypatch):
    """json_mode=False（write/revise 正文路径）默认用文本修正指令，且空正文触发重试。"""
    calls = _queued_llm(monkeypatch, ["", "=== CONTENT ===\n正文"])
    _, _, draft, err = nodes._llm_checked(
        None, {"project_id": "x"}, "write", "Writer", None,
        [{"role": "user", "content": "u"}], check=nodes._check_draft,
        json_mode=False, disable_thinking=True)
    assert err is None and draft == "正文"
    assert calls["n"] == 2
    assert "纯文本散文" in calls["messages"][1][-1]["content"], "文本路径默认用 _RETRY_CORRECTIVE_TEXT"


def test_llm_checked_text_noise_triggers_retry(monkeypatch):
    """正文跑偏（工具调用文本）→ 判噪声重试（_check_draft 的显式失败是可重试的）。"""
    calls = _queued_llm(monkeypatch,
                        ["=== CONTENT ===\n<invoke name=\"inspect_facts\">",
                         "=== CONTENT ===\n夜色沉沉，林砚推门而出。"])
    _, _, draft, err = nodes._llm_checked(
        None, {"project_id": "x"}, "write", "Writer", None,
        [{"role": "user", "content": "u"}], check=nodes._check_draft,
        json_mode=False, disable_thinking=True)
    assert err is None and draft == "夜色沉沉，林砚推门而出。"
    assert calls["n"] == 2


def test_node_plan_chapter_retries_bad_json(temp_project, monkeypatch, stub_provider):
    """真实节点：plan_chapter 坏 JSON → _llm_checked 重发 → 落回 {"plan": ...}（chapter_seq 补全）。"""
    stub_provider("金丹", "金丹")
    calls = _queued_llm(monkeypatch, ["not json{{", json.dumps(_PLAN, ensure_ascii=False)])
    out = nodes.node_plan_chapter({"project_id": temp_project, "chapter_seq": 1, "context": {}})
    assert "error" not in out, out.get("error")
    assert out["plan"]["chapter_seq"] == 1
    assert out["plan"]["goals"] == _PLAN["goals"]
    assert calls["n"] == 2, "坏 JSON 应重发一次而不是直接判失败"


def test_node_plan_chapter_repairs_missing_comma_without_model_retry(temp_project, monkeypatch, stub_provider):
    """Planner 只漏一个结构逗号时本地修复，不能让用户看到整份 Plan 连续重写。"""
    stub_provider("金丹", "金丹")
    malformed = json.dumps(_PLAN, ensure_ascii=False).replace('], "scenes"', '] "scenes"', 1)
    calls = _queued_llm(monkeypatch, [malformed])

    out = nodes.node_plan_chapter({"project_id": temp_project, "chapter_seq": 1, "context": {}})

    assert "error" not in out, out.get("error")
    assert out["plan"]["goals"] == _PLAN["goals"]
    assert calls["n"] == 1, "可确定修复的漏逗号不应再次调用 Planner"


def test_node_plan_chapter_repairs_inexact_anchor_without_model_retry(temp_project, monkeypatch, stub_provider):
    """生成计划误引或改写章尾时只替换证据字段，不重新规划场景。"""
    stub_provider("金丹", "金丹")
    tail = "众人收好物资。\n桥下忽然传来三声短促的敲击，林眠抬手示意所有人噤声。"
    plan = {
        **_PLAN,
        "transition": {
            "mode": "continue",
            "anchor_quote": "桥下传来敲击声，大家安静下来",
            "pending_action": "查明桥下敲击来源",
            "opening_beat": "林眠靠近桥栏辨认声音方位",
            "bridge": "",
        },
    }
    calls = _queued_llm(monkeypatch, [json.dumps(plan, ensure_ascii=False)])

    out = nodes.node_plan_chapter({
        "project_id": temp_project,
        "chapter_seq": 2,
        "context": {"short_context": [{"kind": "prev_chapter_tail", "chapter": 1, "tail": tail}]},
    })

    assert "error" not in out, out.get("error")
    assert out["plan"]["transition"]["anchor_quote"] == tail.splitlines()[-1]
    assert out["plan"]["scenes"] == _PLAN["scenes"]
    assert calls["n"] == 1, "可从章尾确定性纠正的引文不应重跑 Planner"


def test_truncated_valid_audit_json_cannot_be_accepted_as_final_verdict(monkeypatch):
    """A syntactically valid prefix is still incomplete when the provider says length."""
    from myink.providers.base import ModelResponse
    replies = iter([
        ModelResponse(content='{"verdict":"pass"}', model_id='stub', finish_reason='length'),
        ModelResponse(content='{"verdict":"rewrite"}', model_id='stub', finish_reason='stop'),
    ])
    checked = []
    monkeypatch.setattr(nodes, '_llm', lambda *a, **kw: (next(replies), []))

    def validate(content):
        checked.append(content)
        return json.loads(content)['verdict']

    _, _, verdict, error = nodes._llm_checked(
        None, {'project_id': 'test'}, 'audit', 'Audit', None,
        [{'role': 'user', 'content': '待审稿'}], check=validate)
    assert error is None
    assert verdict == 'rewrite'
    assert checked == ['{"verdict":"rewrite"}']


def test_truncated_prose_exhaustion_keeps_incomplete_text_out_of_result(monkeypatch):
    from myink.providers.base import ModelResponse
    monkeypatch.setattr(nodes, '_llm', lambda *a, **kw: (
        ModelResponse(content='=== CONTENT ===\n他伸手推开门，', model_id='stub', finish_reason='length'), []))
    _, _, result, error = nodes._llm_checked(
        None, {'project_id': 'test'}, 'write', 'Writer', None,
        [{'role': 'user', 'content': '写作'}], check=nodes._check_draft,
        json_mode=False, max_attempts=0)
    assert result is None
    assert error is not None


def test_truncated_prose_recovers_with_failed_then_complete_artifacts(monkeypatch):
    from myink.providers.base import ModelResponse
    from myink.workflow.streaming import bind_artifact_sink
    replies = iter([
        ModelResponse(content="他推开门，", model_id="stub", finish_reason="length"),
        ModelResponse(content="=== CONTENT ===\n他推开门，走进院子。", model_id="stub", finish_reason="stop"),
    ])
    messages_seen = []
    def respond(db, state, node, role, chain, messages, **kwargs):
        messages_seen.append(messages)
        response = next(replies)
        kwargs["streamer"].feed(response.content)
        return response, []
    monkeypatch.setattr(nodes, "_llm", respond)
    events = []
    with bind_artifact_sink(events.append):
        _, _, draft, error = nodes._llm_checked(
            None, {"project_id": "test", "chapter_seq": 1}, "write", "Writer", None,
            [{"role": "user", "content": "写作"}], check=nodes._check_draft, json_mode=False)
    assert error is None
    assert draft == "他推开门，走进院子。"
    assert "长度上限" in messages_seen[1][-1]["content"]
    assert [e["event"] for e in events] == [
        "artifact_reset", "artifact_delta", "artifact_failed",
        "artifact_reset", "artifact_delta", "artifact_complete",
    ]
    assert events[2]["artifact_id"] != events[-1]["artifact_id"]


def test_continuous_truncation_exhausts_default_three_attempts(monkeypatch):
    from myink.providers.base import ModelResponse
    attempts = []
    def respond(db, state, node, role, chain, messages, **kwargs):
        attempts.append(messages)
        return ModelResponse(content="未完，", model_id="stub", finish_reason="length"), []
    monkeypatch.setattr(nodes, "_llm", respond)
    _, _, draft, error = nodes._llm_checked(
        None, {"project_id": "test"}, "write", "Writer", None,
        [{"role": "user", "content": "写作"}], check=nodes._check_draft, json_mode=False)
    assert draft is None
    assert error is not None and "长度上限" in error
    assert len(attempts) == 3


def test_json_retry_starts_new_anthropic_user_turn_instead_of_assistant_prefill(monkeypatch):
    from myink.providers.anthropic import _convert_messages
    calls = _queued_llm(monkeypatch, ['{"wrong": true}', '{"ok": true}'])
    def validate(content):
        return json.loads(content)['ok']
    _, _, result, error = nodes._llm_checked(
        None, {'project_id': 'test'}, 'audit', 'Audit', None,
        [{'role': 'system', 'content': '返回严格JSON'}, {'role': 'user', 'content': '核对正文'}],
        check=validate)
    assert result is True and error is None
    _, wire = _convert_messages(calls['messages'][1], json_mode=True)
    assert wire[-1]['role'] == 'user'
    assert '具体校验错误' in wire[-1]['content']
    assert wire[-2] == {'role': 'assistant', 'content': '{"wrong": true}'}


def _patch_response(monkeypatch, finish_reason, *, error=None):
    from contextlib import nullcontext
    from myink.providers.base import ModelResponse
    from myink.workflow.streaming import bind_artifact_sink

    original = "前文不动。" * 30 + "他握着旧剑。" + "后文不动。" * 30
    response = ModelResponse(content=(
        "=== PATCHES ===\n--- PATCH 1 ---\nTARGET_TEXT:\n他握着旧剑。\n"
        "REPLACEMENT_TEXT:\n他握着青剑。\n--- END PATCH ---\n"
        "=== RESPONSES ===\n["
    ), model_id="stub", finish_reason=finish_reason, error=error)
    monkeypatch.setattr(nodes, "tenant_session", lambda _: nullcontext(None))
    monkeypatch.setattr(nodes, "make_chain", lambda *a, **kw: None)
    monkeypatch.setattr(nodes, "_llm", lambda *a, **kw: (response, []))
    monkeypatch.setattr(nodes.prompts, "patch_messages", lambda _: [
        {"role": "user", "content": "修正剑名"}])
    recorded = []
    monkeypatch.setattr(nodes, "record_run_detail", lambda *a, **kw: recorded.append(kw))
    monkeypatch.setattr(nodes, "record_snapshot", lambda *a, **kw: recorded.append(kw))
    events = []
    with bind_artifact_sink(events.append):
        result = nodes.node_patch({"project_id": "test", "chapter_seq": 1, "draft": original})
    return original, result, events, recorded


def test_truncated_patch_prefix_cannot_be_applied_or_completed(monkeypatch):
    original, result, events, recorded = _patch_response(monkeypatch, "length")
    assert "error" in result and "长度上限" in result["error"]
    assert "draft" not in result
    assert recorded == []
    assert [event["event"] for event in events] == ["artifact_reset", "artifact_failed"]


def test_complete_patch_still_applies_without_advisory_responses(monkeypatch):
    original, result, events, recorded = _patch_response(monkeypatch, "stop")
    assert result["draft"] == original.replace("他握着旧剑。", "他握着青剑。")
    assert result["patch_applied"] == 1
    assert result["revise_responses"] == []
    assert events[-1]["event"] == "artifact_complete"
    assert recorded


def test_patch_provider_error_takes_priority_over_truncation(monkeypatch):
    _, result, events, recorded = _patch_response(
        monkeypatch, "length", error="provider unavailable")
    assert result == {"error": "provider unavailable"}
    assert recorded == []
    assert [event["event"] for event in events] == ["artifact_reset", "artifact_failed"]
