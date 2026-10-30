"""Craft publication uses selected messages; historical selections remain frozen."""
from copy import deepcopy

from myink.workflow import prompts
from myink.writing_resource_runtime import bind_resources


def definitions(monkeypatch):
    monkeypatch.setattr('myink.platform_configuration.load_configuration', lambda: {})
    from myink.writing_resource_seed import builtin_resources
    return {r['id']: r for r in builtin_resources()}


def test_craft_instruction_is_in_real_selected_writer_path_and_opt_out(monkeypatch):
    from myink.chapter_craft import CHAPTER_CONTINUITY_RULES, CRAFT_LESSON
    entries = definitions(monkeypatch)
    rules = [entries[rid] for rid in ('genre:xianshi', 'writing-rule:continuity', 'genre-rule:craft-realism-suspense')]
    frozen = deepcopy(rules)
    with bind_resources({'configured': True, 'selections': rules}):
        messages = prompts.write_messages({}, {'expected_events': ['本章一起核对转账，尚未付款']})
    text = '\n'.join(m['content'] for m in messages)
    assert text.count(CHAPTER_CONTINUITY_RULES) == 1
    assert text.count(CRAFT_LESSON) == 1
    assert '本章一起核对转账' in text
    assert rules == frozen
    with bind_resources({'configured': True, 'selections': []}):
        empty = str(prompts.write_messages({}, {}))
    assert CHAPTER_CONTINUITY_RULES not in empty
    assert CRAFT_LESSON not in empty
    assert '=== CONTENT ===' in text and '=== CONTENT ===' in empty


def test_fallback_and_seed_do_not_contradict_genre_specific_endings(monkeypatch):
    from myink.chapter_craft import CHAPTER_CONTINUITY_RULES
    entries = definitions(monkeypatch)
    assert CHAPTER_CONTINUITY_RULES in prompts.SYSTEM_WRITE
    assert '不得是「入睡/休息/原地等待」' not in prompts.SYSTEM_PLAN
    assert '章末不得以「入睡/合眼/闭眼' not in prompts.SYSTEM_WRITE
    for role in ('writer', 'planner', 'audit'):
        assert CHAPTER_CONTINUITY_RULES in entries['writing-rule:continuity']['body']['roles'][role]
    assert '一般表达与节奏建议保持 minor/hint' in entries['writing-rule:continuity']['body']['roles']['audit']


def test_craft_lesson_is_scoped_to_supported_genres(monkeypatch):
    from myink.chapter_craft import CRAFT_LESSON
    entries = definitions(monkeypatch)
    for genre_id, expected in [('xianshi', True), ('xuanyi-naodong', True), ('xiuxian', False)]:
        selected = [entries['genre:' + genre_id], entries['genre-rule:craft-realism-suspense']]
        with bind_resources({'configured': True, 'selections': selected}):
            text = '\n'.join(m['content'] for m in prompts.write_messages({}, {}))
        assert (CRAFT_LESSON in text) is expected
    # An unrelated action genre keeps its selected expression rules and private
    # voice, without receiving the unproven longer style candidates.
    assert 'pov' not in entries['style:natural-narration']['body']['profile']


def test_legacy_role_publication_does_not_restore_deselected_optional_rules():
    from myink.legacy_writing_fragments import LEGACY_LONG_OPTIONAL_FRAGMENT
    from myink.prompt_catalog import split_template
    legacy = ('你是长篇网文创作系统的【写作 Agent】。依据章节计划写出正文。\n'
              '要求：严格遵循注入的设定与硬约束；贴合注入的文风档案与句式禁忌。\n'
              + LEGACY_LONG_OPTIONAL_FRAGMENT + prompts.SYSTEM_WRITE[prompts.SYSTEM_WRITE.index('如需核实'):])
    editable, _ = split_template('system_write', legacy)
    snapshot = {'configured': True, 'selections': [], 'role_prompts': {
        'writer': {'body': {'templates': {'system_write': editable}}}}}
    frozen = deepcopy(snapshot)
    with bind_resources(snapshot):
        messages = prompts.write_messages({}, {})
    text = '\n'.join(m['content'] for m in messages)
    assert '句式禁令（任何题材' not in text
    assert '章末不得以「入睡/合眼/闭眼' not in text
    assert '=== CONTENT ===' in text
    assert snapshot == frozen


def test_old_planner_end_preference_is_controlled_by_selected_resource(monkeypatch):
    from myink.chapter_craft import CHAPTER_CONTINUITY_RULES
    from myink.legacy_writing_fragments import LEGACY_LONG_OPTIONAL_FRAGMENT
    from myink.prompt_catalog import split_template
    old_line = '- 章末钩子必须是剧情推进或悬念事件，不得是「入睡/休息/原地等待」这类静止收束；'
    current_line = next(line for line in prompts.SYSTEM_PLAN.splitlines() if line.startswith('- 章末应兑现'))
    legacy_plan = prompts.SYSTEM_PLAN.replace(current_line, old_line)
    editable, _ = split_template('system_plan', legacy_plan)
    role = {'planner': {'body': {'templates': {'system_plan': editable}}}}
    entries = definitions(monkeypatch)
    for configured, selections, expect_old in [
        (True, [entries['writing-rule:continuity']], False),
        (True, [], False),
        (True, [{'kind': 'writing_rule', 'body': {'roles': {'planner': LEGACY_LONG_OPTIONAL_FRAGMENT}}}], True),
        (False, [], True),
    ]:
        snapshot = {'configured': configured, 'selections': selections, 'role_prompts': role}
        frozen = deepcopy(snapshot)
        with bind_resources(snapshot):
            text = '\n'.join(m['content'] for m in prompts.plan_messages({}))
        assert ('不得是「入睡/休息/原地等待」' in text) is (not configured)
        assert ('章末不得以「入睡/合眼/闭眼' in text) is (configured and expect_old)
        assert (CHAPTER_CONTINUITY_RULES in text) is bool(selections and not expect_old)
        assert snapshot == frozen


def test_writer_and_full_revision_keep_planned_results_after_context():
    plan = {'expected_events': ['沈宁与周梅已经坐在桌旁核对课表，申请未签字。']}
    context = {'short_context': [{'kind': 'prev_chapter_tail', 'tail': 'PREVIOUS_SCENE'}]}
    frozen = deepcopy(plan)
    for messages in (
        prompts.write_messages(context, plan),
        prompts.revise_messages('原稿', [], 2, context=context, plan=plan),
    ):
        user = next(m['content'] for m in reversed(messages) if m['role'] == 'user')
        end = user.rfind('【本章收笔前应实际兑现】')
        assert end > user.index('PREVIOUS_SCENE')
        assert plan['expected_events'][0] in user[end:]
        assert user.count('【本章收笔前应实际兑现】') == 1
        if '待修正文' in user:
            assert end > user.index('待修正文')
    assert plan == frozen
