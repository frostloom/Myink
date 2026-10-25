from copy import deepcopy
import json
import pytest
from myink.writing_resource_runtime import bind_resources, current_resources, reference_read
from myink.workflow import prompts
from myink.providers.base import FallbackChain, ModelProvider, ModelResponse


def snapshot():
    return {"configured":True,"revision":1,"selections":[
        {"kind":"writing_rule","name":"choice","body":{"roles":{
            "writer":"ONLY_CHOSEN_WRITER","planner":"ONLY_CHOSEN_PLANNER","audit":"ONLY_CHOSEN_AUDIT"}}},
        {"kind":"style","name":"style","body":{"profile":{"sentence_style":"CHOSEN_STYLE"}}},
        {"kind":"reference","name":"ref","body":{"files":[{"path":"chosen.md","content":"# Chosen\nFROZEN_BODY"}]}}]}


class Capture(ModelProvider):
    def __init__(self): self.messages = []
    def name(self): return "capture"
    def generate(self, messages, **kwargs):
        self.messages.append(deepcopy(messages))
        return ModelResponse(content="ok",model_id="stub")


@pytest.mark.parametrize("stream", [False,True])
@pytest.mark.parametrize("stage,role", [
    ("write","WRITER"),("revise","WRITER"),("patch","WRITER"),
    ("short_write","WRITER"),("short_revise","WRITER"),("short_continue","WRITER"),
    ("plan","PLANNER"),("book_setup","PLANNER"),("book_outline","PLANNER"),("short_plan","PLANNER"),("short_plan_review","PLANNER"),
    ("audit","AUDIT"),("short_review","AUDIT")])
def test_actual_provider_messages_use_frozen_resources(stage, role, stream):
    brief={"chapter_count":1,"chars_per_chapter":100,"style_profile":{"sentence_style":"PRIVATE_STYLE"}}
    builders={
        "write":lambda:prompts.write_messages({}, {},style_profile=brief["style_profile"]),
        "revise":lambda:prompts.revise_messages("draft",[],1,style_profile=brief["style_profile"]),
        "patch":lambda:prompts.patch_messages({"chapter_seq":1,"draft":"draft"}),
        "short_write":lambda:prompts.short_write_messages(brief),
        "short_revise":lambda:prompts.short_revise_messages(brief,"draft",{}),
        "short_continue":lambda:prompts.short_continue_messages(brief,"draft",[1]),
        "plan":lambda:prompts.plan_messages({}),
        "book_setup":lambda:prompts.book_setup_messages("oldgenre","premise"),
        "book_outline":lambda:prompts.book_outline_messages("oldgenre","premise",10,"story"),
        "short_plan":lambda:prompts.short_plan_messages("oldgenre","premise",1,100),
        "short_plan_review":lambda:prompts.short_plan_review_messages({},1),
        "audit":lambda:prompts.audit_messages("draft",{}, {},1),
        "short_review":lambda:prompts.short_review_messages(brief,"draft")}
    snap=snapshot()
    provider=Capture(); chain=FallbackChain(provider,["stub"])
    with bind_resources(snap):
        snap["selections"][0]["body"]["roles"]["writer"]="CHANGED_PLATFORM"
        messages=builders[stage]()
        if stream: chain.generate_stream(messages,on_delta=lambda _:None)
        else: chain.generate(messages)
        text=json.dumps(provider.messages,ensure_ascii=False)
        assert "ONLY_CHOSEN_"+role in text
        assert "CHOSEN_STYLE" in text
        if stage in {"write", "revise", "short_write", "short_revise", "short_continue", "short_review"}:
            assert "PRIVATE_STYLE" in text
        assert "CHANGED_PLATFORM" not in text
        assert "句式禁令（任何题材" not in text
        assert reference_read("chosen.md")["content"].endswith("FROZEN_BODY")
        assert "error" in reference_read("templates/genres/修仙.md")
    assert current_resources() is None


def test_explicit_empty_disables_optional_bans_but_legacy_keeps_them():
    from myink.validation.l1 import _prose_ban_quotes
    text="不是梦，是现实。"
    assert _prose_ban_quotes(text)
    with bind_resources({"configured":True,"selections":[]}):
        assert not _prose_ban_quotes(text)
        messages=prompts.write_messages({}, {})
        assert "=== CONTENT ===" in messages[0]["content"]
        assert "句式禁令" not in messages[0]["content"]
    assert _prose_ban_quotes(text)


def test_builtins_are_real_and_no_output_protocol(monkeypatch):
    from myink import writing_resource_seed as seed
    monkeypatch.setattr("myink.platform_configuration.load_configuration",lambda:{"genre_packs":{},"prompts":{}})
    items=seed.builtin_resources()
    assert sum(x["kind"]=="genre" for x in items)==37
    assert sum(x["kind"]=="genre_rule" for x in items)==6
    assert sum(x["kind"]=="style" for x in items)==4
    assert any(x["kind"]=="reference" for x in items)
    for item in items:
        if item["kind"] in {"writing_rule","expression_rule"}:
            text=json.dumps(item["body"],ensure_ascii=False)
            assert "=== CONTENT ===" not in text
            assert "输出标记" not in text


def test_children_capture_parent_snapshot_without_reading_platform(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import uuid
    from myink.workflow.runner import new_task
    stored=[]
    class DB:
        def get(self, model, key): return SimpleNamespace(user_id=uuid.uuid4())
        def add(self, row): stored.append(row)
        def flush(self): pass
    @contextmanager
    def session(_): yield DB()
    monkeypatch.setattr("myink.workflow.runner.tenant_session",session)
    monkeypatch.setattr("myink.task_budget.ensure_task_budget",lambda *a:None)
    def unexpected(*a): raise AssertionError("Child dynamically fetched platform")
    monkeypatch.setattr("myink.writing_resources.capture_task_resources",unexpected)
    snap=snapshot()
    with bind_resources(snap):
        for kind in ("chapter_generate","batch_generate","short_generate"):
            new_task(project_id=str(uuid.uuid4()),task_type=kind,payload={},budget_snapshot={})
    assert len(stored)==3
    assert all(row.payload["writing_resources"]==snap for row in stored)
    stored[0].payload["writing_resources"]["revision"]=99
    assert stored[1].payload["writing_resources"]["revision"]==1


def test_selection_budget_fails_before_provider(monkeypatch):
    from dataclasses import replace
    from myink.config import settings
    from myink.context_budget import ContextBudgetExceeded
    monkeypatch.setattr(prompts,"settings",replace(settings,request_token_budget=2000))
    snap=snapshot()
    snap["selections"][0]["body"]["roles"]["writer"]="very long selected rule "*10000
    with bind_resources(snap), pytest.raises(ContextBudgetExceeded):
        prompts.write_messages({}, {})


def test_synchronous_project_planner_binds_snapshot(monkeypatch):
    from myink.writing_resource_runtime import project_resources
    snap=snapshot()
    monkeypatch.setattr("myink.writing_resources.capture_task_resources",lambda db,pid:snap)
    @project_resources
    def call(*,project_id,db):
        snap["revision"]=42
        return current_resources()
    captured=call(project_id="test",db=object())
    assert captured["revision"]==1
    assert current_resources() is None


def test_private_style_survives_empty_platform_style_and_genre_rules_match():
    snap={"configured":True,"selections":[
        {"kind":"genre_rule","name":"unmatched","body":{"genre_ids":["xiuxian"],"roles":{"writer":"UNMATCHED_RULE"}}}]}
    with bind_resources(snap):
        text=json.dumps(prompts.write_messages({}, {},style_profile={"sentence_style":"PRIVATE_STYLE"}),ensure_ascii=False)
        assert "PRIVATE_STYLE" in text
        assert "UNMATCHED_RULE" not in text
        snap["selections"].append({"kind":"genre","name":"修仙","body":{"catalog_id":"xiuxian","fields":{}}})
    with bind_resources(snap):
        assert "UNMATCHED_RULE" in json.dumps(prompts.write_messages({},{}),ensure_ascii=False)


def test_actual_tool_dispatch_is_limited_to_selected_frozen_files():
    from myink.workflow.tools import execute_tool
    import uuid
    snap=snapshot()
    with bind_resources(snap):
        snap["selections"][-1]["body"]["files"][0]["content"]="CHANGED_AFTER_ADMISSION"
        allowed=json.loads(execute_tool(None,uuid.uuid4(),"read_genre_reference",{"path":"chosen.md"}))
        assert "FROZEN_BODY" in allowed["content"]
        for path in ("../secrets", "/etc/passwd", "templates/genres/修仙.md"):
            assert "error" in json.loads(execute_tool(None,uuid.uuid4(),"read_genre_reference",{"path":path}))
        listing=json.loads(execute_tool(None,uuid.uuid4(),"read_genre_reference",{}))
        assert [x["path"] for x in listing["files"]]==["chosen.md"]


def test_seed_preserves_existing_platform_overrides(monkeypatch):
    from myink.writing_resource_seed import builtin_resources
    monkeypatch.setattr("myink.platform_configuration.load_configuration",lambda:{
        "genre_packs":{"xiuxian":{"pacing":"ADMIN_PACING"}},"prompts":{"writer":"ADMIN_CREATIVE_RULE"}})
    items=builtin_resources()
    assert next(x for x in items if x["id"]=="genre:xiuxian")["body"]["fields"]["pacing"]=="ADMIN_PACING"
    assert next(x for x in items if x["id"]=="writing-rule:platform:writer")["body"]["roles"]["writer"]=="ADMIN_CREATIVE_RULE"


@pytest.mark.parametrize("operation,expected_role", [
    ("short_plan_review", "planner"), ("summary", "summarize"),
    ("extract", "extract"), ("ledger", "validator_l2")])
def test_real_workflow_call_site_matches_rule_role(monkeypatch, operation, expected_role):
    """Observe make_chain from the production operation, not the wrapper role table."""
    from contextlib import contextmanager
    from types import SimpleNamespace
    import uuid
    from myink import book_setup
    from myink.workflow import nodes
    from myink.validation import ledger_l2
    provider=Capture()
    observed=[]
    def chain(role, **kwargs):
        observed.append(role)
        return FallbackChain(provider,["stub"])
    monkeypatch.setattr("myink.providers.make_chain", chain)
    monkeypatch.setattr(nodes,"make_chain",chain)
    monkeypatch.setattr(ledger_l2,"make_chain",chain)
    monkeypatch.setattr(nodes,"record_run",lambda *a,**kw:None)
    def llm(db,state,node,role,chain,messages,**kwargs):
        return chain.generate(messages), None
    monkeypatch.setattr(nodes,"_llm",llm)
    def checked(db,state,node,role,chain,messages,**kwargs):
        resp=chain.generate(messages)
        return resp,None,[],None
    monkeypatch.setattr(nodes,"_llm_checked",checked)
    @contextmanager
    def session(_): yield object()
    monkeypatch.setattr(nodes,"tenant_session",session)
    monkeypatch.setattr(nodes.repo,"get_chapter",lambda *a:SimpleNamespace(status="confirmed",summary=""))
    monkeypatch.setattr(ledger_l2,"build_judgment_set",lambda *a,**kw:[{
        "kind":"character_state","key":"test","entity_name":"name","field":"location",
        "ledger":"old","new_value":"new"}])
    snap=snapshot()
    snap["selections"][0]["body"]["roles"]={r:"RULE_FOR_"+r for r in ("writer","planner","audit","extract","summarize","validator_l2")}
    snap["selections"].append({"kind":"genre","name":"GENERIC_GENRE","body":{"fields":{}}})
    pid=str(uuid.uuid4())
    with bind_resources(snap):
        if operation=="short_plan_review":
            book_setup.review_short_plan({},chapter_count=1)
        elif operation=="summary":
            nodes.node_summarize({"project_id":pid,"chapter_seq":1,"draft":"draft"})
        elif operation=="extract":
            nodes.extract_candidates_from_draft(None,project_id=pid,chapter_seq=1,draft="draft")
        else:
            ledger_l2.run_ledger_l2(None,project_id=pid,chapter_seq=1,candidates=[],draft="draft")
    assert observed==[expected_role]
    assert provider.messages
    text=json.dumps(provider.messages,ensure_ascii=False)
    assert "RULE_FOR_"+expected_role in text
    assert "RULE_FOR_writer" not in text
    assert "RULE_FOR_audit" not in text
    if expected_role!="planner":
        assert "CHOSEN_STYLE" not in text
        assert "GENERIC_GENRE" not in text
        assert "chosen.md" not in text
        assert "JSON" in text


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("stage", ["write", "plan", "audit", "short_write", "patch"])
def test_provider_receives_primary_secondary_genre_priority(stage, stream):
    from myink.writing_resource_runtime import selected_genre
    snap={"configured":True,"selections":[
        {"kind":"genre","name":"主修仙","body":{"catalog_id":"xiuxian","fields":{"selling_point":"PRIMARY_FIELDS"},"setup_caps":{"power_scaling":True}}},
        {"kind":"genre","name":"辅现实","body":{"catalog_id":"xianshi","fields":{"selling_point":"SECONDARY_FIELDS"},"setup_caps":{"power_scaling":False}}},
        {"kind":"genre_rule","name":"主精调","body":{"genre_ids":["xiuxian"],"roles":dict.fromkeys(("writer","planner","audit"),"PRIMARY_REFINEMENT")}},
        {"kind":"genre_rule","name":"辅精调","body":{"genre_ids":["xianshi"],"roles":dict.fromkeys(("writer","planner","audit"),"SECONDARY_REFINEMENT")}}]}
    builders={"write":lambda:prompts.write_messages({},{}),"plan":lambda:prompts.plan_messages({}),
              "audit":lambda:prompts.audit_messages("draft",{},{},1),
              "short_write":lambda:prompts.short_write_messages({"chapter_count":1}),
              "patch":lambda:prompts.patch_messages({"chapter_seq":1,"draft":"draft"})}
    provider=Capture();chain=FallbackChain(provider,["stub"])
    with bind_resources(snap):
        assert selected_genre()["_resource_caps"]["power_scaling"] is True
        messages=builders[stage]()
        if stream: chain.generate_stream(messages,on_delta=lambda _:None)
        else: chain.generate(messages)
    text="\n".join(m["content"] for m in provider.messages[0])
    assert "主辅比例：7:3" in text
    assert "主题材：主修仙" in text
    assert "辅题材：辅现实" in text
    assert "辅题材不得覆盖主题材硬约束" in text
    assert "主题材精调（七成）：PRIMARY_REFINEMENT" in text
    assert "辅题材精调（合计三成，服从主题材）：SECONDARY_REFINEMENT" in text
    assert text.index("PRIMARY_FIELDS") < text.index("SECONDARY_FIELDS")


@pytest.mark.parametrize("stage", ["revise", "short_review"])
def test_selected_resources_do_not_edit_rule_fragments_quoted_in_user_draft(stage):
    from myink.writing_resource_seed import optional_fragments
    quoted=optional_fragments()[0]
    with bind_resources({"configured":True,"selections":[]}):
        messages=(prompts.revise_messages(quoted,[],1) if stage=="revise"
                  else prompts.short_review_messages({"chapter_count":1},quoted))
    assert any(quoted in m["content"] for m in messages if m["role"]=="user")


def test_reference_index_is_bounded_even_for_legacy_snapshots():
    files = [{'path': f'{i}.md', 'content': '# ' + 'x' * 500} for i in range(100)]
    with bind_resources({'configured': True, 'selections': [
        {'kind': 'reference', 'body': {'files': files}}]}):
        result = reference_read('')
    assert len(result['files']) <= 80
    assert len(json.dumps(result, ensure_ascii=False)) <= 12000
    assert result['truncated'] is True


@pytest.mark.parametrize('configured', [False, True])
def test_automatic_library_hint_uses_final_budget(configured, monkeypatch):
    from dataclasses import replace
    from myink.config import settings
    from myink.context_budget import estimate_tokens
    monkeypatch.setattr(prompts, 'settings', replace(settings, request_token_budget=8000))
    with bind_resources({'configured':configured,'selections':[], 'reference_library':[{'files':[{'path':'methods.md'}]}]}):
        messages = prompts.write_messages({}, {})
    assert '基础写作资料库' in json.dumps(messages,ensure_ascii=False)
    assert estimate_tokens(messages) <= prompts._tool_prompt_budget()


@pytest.mark.parametrize('count,path_size', [(81,10), (50,500)])
def test_automatic_library_directory_bounded_without_database(count,path_size):
    paths=[{'path':str(i)+'x'*path_size+'.md'} for i in range(count)]
    with bind_resources({'configured':False, 'reference_library':[{'resource_id':'frozen','version':1,'files':paths}]}):
        listing=reference_read('')
        assert len(listing['files'])<=80
        assert len(json.dumps(listing,ensure_ascii=False))<=12000
        assert listing['truncated']
        assert 'error' in reference_read('unfrozen.md')


def test_legacy_task_does_not_implicitly_use_automatic_library(monkeypatch):
    from myink.workflow.tools import execute_tool
    monkeypatch.setattr('myink.workflow.tools.read_reference',lambda *args:{'content':'LEGACY'})
    with bind_resources({}):
        assert json.loads(execute_tool(None,None,'read_genre_reference',{'path':'x.md'}))['content']=='LEGACY'
    with bind_resources({'configured':True,'selections':[]}):
        assert 'error' in json.loads(execute_tool(None,None,'read_genre_reference',{'path':'x.md'}))
