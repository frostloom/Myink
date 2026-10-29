"""Private book style must survive audit/patch preparation through the provider boundary."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace

import pytest

from myink.config import settings
from myink.context_budget import ContextBudgetExceeded
from myink.providers.base import FallbackChain, ModelProvider, ModelResponse
from myink.workflow import nodes, prompts
from myink.writing_resource_runtime import bind_resources


class Capture(ModelProvider):
    def name(self):
        return "private-style-capture"

    def generate(self, messages, **kwargs):
        self.messages = deepcopy(messages)
        return ModelResponse(content="ok", model_id="stub")


def build(stage, profile):
    if stage == "audit":
        return prompts.audit_messages("原稿", {}, {}, 1, style_profile=profile)
    return prompts.patch_messages({"chapter_seq": 1, "draft": "原稿", "style_profile": profile})


@pytest.mark.parametrize("stage", ["audit", "patch"])
@pytest.mark.parametrize("configured", [False, True])
def test_private_style_reaches_provider_after_role_and_resource_wrapping(stage, configured):
    role, template = (("audit", "system_audit") if stage == "audit"
                      else ("writer", "system_revise_patch"))
    snapshot = {"configured": configured, "selections": [
        {"kind": "style", "body": {"profile": {"sentence_style": "GENERIC_STYLE"}}}],
        "role_prompts": {role: {"body": {"templates": {template: "EDITED_ROLE"}}}}}
    if configured:
        snapshot["selections"].append(
            {"kind": "writing_rule", "body": {"roles": {role: "SELECTED_RULE"}}})
    profile = {"sentence_style": "PRIVATE_STYLE", "reference_excerpts": ["PRIVATE_EXAMPLE"]}
    before = deepcopy((snapshot, profile))
    provider = Capture()
    with bind_resources(snapshot):
        FallbackChain(provider, ["stub"]).generate(build(stage, profile))
    system = "\n".join(m["content"] for m in provider.messages if m["role"] == "system")
    assert "EDITED_ROLE" in system
    assert "PRIVATE_STYLE" in system
    assert "PRIVATE_EXAMPLE" in system
    assert "私有" in system and "优先" in system
    assert system.count("GENERIC_STYLE") == int(configured)
    assert system.count("SELECTED_RULE") == int(configured)
    assert (snapshot, profile) == before
    assert ("scope" if stage == "audit" else "TARGET_TEXT") in system


@pytest.mark.parametrize("stage", ["audit", "patch"])
def test_empty_private_style_keeps_existing_prompt(stage):
    with bind_resources({"configured": True, "selections": []}):
        default = (prompts.audit_messages("原稿", {}, {}, 1) if stage == "audit"
                   else prompts.patch_messages({"chapter_seq": 1, "draft": "原稿"}))
        assert build(stage, {}) == default
        assert build(stage, None) == default


@pytest.mark.parametrize("stage", ["audit", "patch"])
@pytest.mark.parametrize("configured", [False, True])
def test_private_style_cannot_be_silently_trimmed_to_fit_budget(monkeypatch, stage, configured):
    monkeypatch.setattr(prompts, "settings", replace(settings, request_token_budget=5000))
    with bind_resources({"configured": configured, "selections": []}):
        with pytest.raises(ContextBudgetExceeded):
            build(stage, {"sentence_style": "不可截断的私有文风" * 1000})


def test_audit_node_passes_loaded_private_style_to_provider(monkeypatch):
    provider = Capture()
    @contextmanager
    def session(_):
        yield object()
    def checked(db, state, node, role, chain, messages, **kwargs):
        chain.generate(messages)
        return None, [], None, "stop after observing provider"
    monkeypatch.setattr(nodes, "tenant_session", session)
    monkeypatch.setattr(nodes, "make_chain", lambda *a, **kw: FallbackChain(provider, ["stub"]))
    monkeypatch.setattr(nodes, "_llm_checked", checked)
    state = {"project_id": "test", "chapter_seq": 1, "draft": "原稿",
             "style_profile": {"sentence_style": "LOADED_PRIVATE_STYLE"}}
    before = deepcopy(state)
    with bind_resources({"configured": True, "selections": []}):
        nodes.node_audit(state)
    assert "LOADED_PRIVATE_STYLE" in "\n".join(m["content"] for m in provider.messages)
    assert state == before
