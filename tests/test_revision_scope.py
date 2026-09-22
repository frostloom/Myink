"""Routing and real graph regression for the independent patch channel."""
import uuid
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from myink.db import tenant_session
from myink.models import AgentRun, Chapter
from myink.providers.base import FallbackChain, ModelProvider, ModelResponse
from myink.workflow import nodes
from myink.workflow.chapter_graph import build_chapter_graph, node_reset_replan, route_after_audit


def local_state():
    finding = {"conflict_key": "ban", "conflict_type": "style", "severity": "critical",
               "scope": "local", "source": "L1", "evidence": [], "suggestion": "剑名用青剑"}
    return {"report": {"summary": {"critical": 1}, "findings": [finding]},
            "unresolved": [finding], "audit_verdict": {"verdict": "pass"}}


def test_local_critical_cannot_pass_or_consume_rewrite_budget():
    state = {**local_state(), "revision_count": 2}
    assert route_after_audit(state) == "patch"
    assert route_after_audit({**state, "patch_count": 2}) == "needs_review"


@pytest.mark.parametrize("scope", ["structural", "unknown", None])
def test_nonlocal_keeps_original_rewrite_budget(scope):
    state = local_state()
    state["report"]["findings"][0]["scope"] = scope
    assert route_after_audit(state) == "revise"
    assert route_after_audit({**state, "revision_count": 2}) == "needs_review"


def test_semantic_local_rewrite_uses_patch():
    assert route_after_audit({"audit_verdict": {"verdict": "rewrite",
        "findings": [{"severity": "major", "scope": "local"}]}}) == "patch"


def test_word_count_only_rule_does_not_become_a_hard_gate():
    assert route_after_audit({"report": {"summary": {}, "findings": [
        {"severity": "major", "scope": "local", "source": "L1"}]},
        "audit_verdict": {"verdict": "pass"}}) == "persist"


def test_replan_clears_patch_transients():
    result = node_reset_replan({"patch_count": 2, "patch_applied": 1,
                              "patch_rejected_reason": "拒绝"})
    assert result["patch_count"] == 0
    assert result["patch_applied"] == 0
    assert result["patch_rejected_reason"] is None


def test_new_attempt_clears_checkpoint_patch_transients(temp_project):
    previous = {"project_id": temp_project, "patch_count": 2, "revision_count": 2,
                "patch_applied": 1, "patch_skipped": 2, "revise_mode": "patch",
                "patch_rejected_reason": "旧失败"}
    merged = {**previous, **nodes.node_load_state(previous)}
    assert merged["patch_count"] == merged["patch_applied"] == merged["patch_skipped"] == 0
    assert merged["revise_mode"] == "full" and merged["patch_rejected_reason"] is None
    assert route_after_audit({**merged, **local_state()}) == "patch"


PATCH = """=== PATCHES ===
--- PATCH 1 ---
TARGET_TEXT:
他握着旧剑。
REPLACEMENT_TEXT:
他握着青剑。
--- END PATCH ---
=== RESPONSES ===
[{"conflict_key":"ban","outcome":"fixed","note":"剑名已统一"}]"""
DRAFT = ("掌柜从柜底取出账簿，翻到去年冬天的那页。窗外传来车轮碾过石板的声音。"
         "他握着旧剑。伙计认出剑柄上的铜纹，伸手关紧了临街的门。"
         "账上那笔欠款旁，留着一枚已经褪色的手印。")


class PatchProvider(ModelProvider):
    def __init__(self, patch=PATCH):
        self.patch = patch
        self.calls = []

    def name(self):
        return "revision-test"

    def generate(self, messages, *, model_id, **kwargs):
        system = messages[0]["content"]
        if "局部修订" in system:
            node, content = "patch", self.patch
            assert kwargs["max_tokens"] == 4096
            assert not kwargs.get("tools")
        elif "记忆抽取" in system:
            node, content = "extract", '{"candidates":[]}'
            assert "他握着青剑。" in str(messages)
            assert "他握着旧剑。" not in str(messages)
        elif "审核中枢" in system:
            node, content = "audit", '{"verdict":"pass","findings":[],"reasons":["已修复"],"confidence":0.9}'
        elif "章节摘要" in system:
            node, content = "summarize", '{"summary":"剑名已统一"}'
        else:
            raise AssertionError("Unexpected generation stage")
        self.calls.append(node)
        return ModelResponse(content=content, model_id=model_id, input_tokens=17, output_tokens=11, duration_ms=2)


def install_provider(monkeypatch, provider):
    monkeypatch.setattr(nodes, "make_chain", lambda *args, **kwargs: FallbackChain(provider, ["revision-test"]))


def test_patch_node_preserves_text_records_metrics_and_budget(temp_project, monkeypatch):
    provider = PatchProvider()
    install_provider(monkeypatch, provider)
    tid = str(uuid.uuid4())
    state = {**local_state(), "project_id": temp_project, "chapter_seq": 1,
             "task_id": tid, "draft": DRAFT, "revision_count": 1}
    result = nodes.node_patch(state)
    assert result["draft"] == DRAFT.replace("他握着旧剑。", "他握着青剑。")
    assert result["patch_count"] == 1 and result["patch_applied"] == 1
    assert "revision_count" not in result
    assert provider.calls == ["patch"]
    with tenant_session(temp_project) as db:
        row = db.query(AgentRun).filter_by(task_id=tid, node="patch").one()
        assert row.role == "Writer" and row.input_tokens == 17
        assert row.detail["patch_applied"] == 1
        assert row.detail["revise_mode"] == "patch"


@pytest.mark.parametrize("output", ["=== CONTENT ===\n整章改坏", PATCH.replace("他握着旧剑。", "根本没有这个句子")])
def test_rejected_output_retains_original_and_does_not_claim_fixed(temp_project, monkeypatch, output):
    install_provider(monkeypatch, PatchProvider(output))
    result = nodes.node_patch({**local_state(), "project_id": temp_project, "chapter_seq": 1,
                               "draft": DRAFT, "task_id": str(uuid.uuid4())})
    assert result["draft"] == DRAFT
    assert result["patch_count"] == 1
    assert result["patch_applied"] == 0 and result["patch_rejected_reason"]
    assert result["revise_responses"] == []


def test_partly_malformed_output_cannot_claim_all_responses_fixed(temp_project, monkeypatch):
    output = PATCH.replace("=== RESPONSES ===", "--- PATCH 2 ---\nTARGET_TEXT:\n坏块\n--- END PATCH ---\n=== RESPONSES ===")
    install_provider(monkeypatch, PatchProvider(output))
    result = nodes.node_patch({**local_state(), "project_id": temp_project, "chapter_seq": 1,
                               "draft": DRAFT, "task_id": str(uuid.uuid4())})
    assert result["patch_applied"] == 1 and result["patch_skipped"] == 1
    assert result["revise_responses"] == []


def test_real_graph_reextracts_and_reaudits_before_persist(temp_project, monkeypatch, fake_embedder):
    provider = PatchProvider()
    install_provider(monkeypatch, provider)
    tid = str(uuid.uuid4())
    state = {**local_state(), "project_id": temp_project, "chapter_seq": 1,
             "draft": DRAFT, "task_id": tid, "settings": {}, "candidates": [
                 {"kind": "event", "source_chapter": 1, "confidence": 0.9, "payload": {"summary": "旧稿事件"}}]}
    graph = build_chapter_graph(checkpointer=InMemorySaver(), entry="route")
    result = graph.invoke(state, {"configurable": {"thread_id": tid}})
    assert provider.calls == ["patch", "extract", "audit", "summarize"], result.get("report")
    assert result["candidates"] == [] and result["persisted"]
    assert result["patch_count"] == 1
    with tenant_session(temp_project) as db:
        chapter = db.query(Chapter).filter_by(chapter_seq=1).one()
        assert chapter.content == DRAFT.replace("他握着旧剑。", "他握着青剑。")
        recorded = [r.node for r in db.query(AgentRun).filter_by(task_id=tid).order_by(AgentRun.id)]
        assert recorded[:6] == ["route", "patch", "extract", "validate", "audit", "route"]
