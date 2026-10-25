"""Seed the bundled, attributed resources without editing published versions."""
from copy import deepcopy

def optional_fragments():
    from myink.workflow import prompts as p
    return [p.SYSTEM_WRITE[p.SYSTEM_WRITE.index("句式禁令"):p.SYSTEM_WRITE.index("如需核实")],
            p.SYSTEM_SHORT_WRITER[p.SYSTEM_SHORT_WRITER.index("句式禁令"):p.SYSTEM_SHORT_WRITER.index("落笔依据")]]

def builtin_resources():
    from myink.genre_catalog import PACKS, FIELD_KEYS, _REFINE, setup_capabilities
    from myink.seed import STYLE_PRESETS
    from myink.reference_corpus import CORPUS_ROOT, corpus_files
    from myink.workflow.prose_rules import PROSE_RULES, PROSE_REVIEW_RULES
    def entry(key, name, kind, source, body):
        return dict(id=key, name=name, kind=kind, source=source, body=body)
    from myink.platform_configuration import load_configuration
    config = load_configuration()
    packs = deepcopy(PACKS)
    for key, fields in config.get("genre_packs", {}).items():
        if key in packs:
            packs[key].update(fields)
    PROSE_RULES = PROSE_RULES[:PROSE_RULES.index("- 输出前")].rstrip()
    items = [entry("genre:"+key, pack["name"], "genre", "genre_catalog.py", {
        "catalog_id": key, "fields": deepcopy({k:pack[k] for k in FIELD_KEYS}),
        "setup_caps": setup_capabilities({"source_id":key})}) for key,pack in packs.items()]
    items += [entry("genre-rule:"+key, PACKS[key]["name"]+"精调", "genre_rule", "genre_catalog.py:_REFINE", {
        "genre_ids":[key], "roles":dict.fromkeys(("writer","planner","audit"), text)}) for key,text in _REFINE.items()]
    items += [entry("style:"+p["id"], p["name"], "style", "seed.py:STYLE_PRESETS", {"profile":deepcopy(p["style_profile"])}) for p in STYLE_PRESETS]
    items += [entry("reference:"+path, path, "reference", "third_party/webnovel-writer (GPL-3; NOTICE.md)",
                    {"files":[{"path":path,"content":(CORPUS_ROOT/path).read_text(encoding="utf-8",errors="replace")}]}) for path,_ in corpus_files()]
    long, short = optional_fragments()
    ban = long[:long.index("开篇规则")]
    creation = long[long.index("开篇规则"):]
    items += [entry("writing-rule:continuity", "章节衔接与收尾", "writing_rule", "workflow/prompts.py:SYSTEM_WRITE", {"roles":dict.fromkeys(("writer","planner","audit"), creation)}),
              entry("expression-rule:bans", "句式偏好", "expression_rule", "workflow/prompts.py:SYSTEM_WRITE", {"roles":dict.fromkeys(("writer","audit"), ban), "validation":{"not_is":True,"parallel":True}}),
              entry("expression-rule:prose", "中文小说表达", "expression_rule", "workflow/prose_rules.py; docs/PROSE-RULES.md", {"roles":{"writer":PROSE_RULES,"audit":PROSE_REVIEW_RULES}})]
    for role, text in config.get("prompts", {}).items():
        if text.strip():
            items.append(entry("writing-rule:platform:"+role, "平台创作补充（"+role+"）", "writing_rule",
                               "platform_configuration.prompts", {"roles":{role:text}}))
    from myink.prompt_catalog import prompt_catalog
    role_names = {"writer":"写作与修订", "planner":"故事规划", "audit":"内容审核",
                  "extract":"记忆与文风提炼", "summarize":"章节摘要", "validator_l2":"台账语义校验"}
    items += [entry("role-prompt:" + g["role"], "角色创作要求（" + role_names[g["role"]] + "）", "role_prompt",
                    "workflow/prompts.py", {"role":g["role"], "supplement":config.get("prompts", {}).get(g["role"], ""),
                                            "templates":{t["id"]:t["editable_content"] for t in g["templates"]}})
              for g in prompt_catalog()]
    return items
