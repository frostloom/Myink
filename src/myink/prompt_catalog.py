"""Inventory and editable business boundaries of workflow system templates.

Administrators publish role-specific business prose through writing resources;
output schemas and parser/tool contracts remain fixed in the workflow code.
No project content, credentials, or generated runtime context enters this catalog.
"""
from itertools import product

from pydantic import BaseModel


class PromptTemplateOut(BaseModel):
    id: str
    title: str
    content: str
    source: str
    editable_content: str
    fixed_content: str
    description: str
    when: str


class PromptRoleTemplatesOut(BaseModel):
    role: str
    templates: list[PromptTemplateOut]


# Role assignments follow make_chain/make_user_chain at each workflow call site.
_TEMPLATES = {
    'writer': (
        ('SYSTEM_WRITE', '长篇正文写作'),
        ('SYSTEM_REVISE', '长篇全文修订'),
        ('SYSTEM_REVISE_PATCH', '长篇局部修订'),
        ('SYSTEM_SHORT_WRITER', '短篇整篇写作'),
        ('SYSTEM_SHORT_REVISER', '短篇整篇改稿'),
        ('SYSTEM_SHORT_CONTINUER', '短篇缺章补写'),
    ),
    'planner': (
        ('SYSTEM_BATCH_PLAN', '长篇批次推进规划'),
        ('SYSTEM_PLAN', '长篇章节规划'),
        ('SYSTEM_CAST', '长篇出场人物规划'),
        ('SYSTEM_BOOK_OUTLINE', '整书卷级大纲'),
        ('SYSTEM_SHORT_PLAN', '短篇逐章方案'),
        ('SYSTEM_SHORT_PLAN_REVIEW', '短篇方案审核'),
        ('SYSTEM_SHORT_CREATION', '短篇建书对话'),
    ),
    'validator_l2': (('SYSTEM_LEDGER_L2', '正文与台账语义比对'),),
    'extract': (
        ('SYSTEM_EXTRACT', '章节记忆抽取'),
        ('SYSTEM_STYLE_EXTRACT', '样本文风提炼'),
    ),
    'audit': (
        ('SYSTEM_AUDIT', '长篇单章审核'),
        ('SYSTEM_REFLEXION', '跨章问题复盘'),
        ('SYSTEM_GLOBAL_AUDIT', '卷级进展审计'),
        ('SYSTEM_SHORT_DRAFT_REVIEW', '短篇整篇审稿'),
    ),
    'summarize': (('SYSTEM_SUMMARIZE', '章节摘要'),),
}
_SOURCE = 'src/myink/workflow/prompts.py'


def prompt_catalog() -> list[dict]:
    from myink.workflow import prompts

    result = []
    for role, entries in _TEMPLATES.items():
        templates = [
            {'id': symbol.lower(), 'title': title, 'content': getattr(prompts, symbol),
             'source': f'{_SOURCE}:{symbol}'}
            for symbol, title in entries
        ]
        if role == 'planner':
            for flags in product((False, True), repeat=3):
                caps = dict(zip(('power_scaling', 'numerical_system', 'era_research'), flags))
                labels = [f'{name}{"开启" if enabled else "关闭"}'
                          for name, enabled in zip(('等级', '数值', '考据'), flags)]
                templates.append({
                    'id': 'book_setup_' + ''.join(str(int(flag)) for flag in flags),
                    'title': '建书设定（' + '、'.join(labels) + '）',
                    'content': prompts.book_setup_system(caps),
                    'source': f'{_SOURCE}:book_setup_system',
                })
        for template in templates:
            editable, fixed = split_template(template['id'], template['content'])
            template.update(editable_content=editable, fixed_content=fixed,
                            description=template['title'] + '的创作职责与判断要求；输出协议由系统保留。',
                            when='执行' + template['title'] + '时自动使用该角色已发布版本。')
        result.append({'role': role, 'templates': templates})
    return result


# Explicit protocol boundaries for each real workflow template. The schema block
# and its parser/tool constraints stay in code, outside administrator documents.
_PROTOCOL_START = {
    'system_batch_plan': '输出严格 JSON',
    'system_plan': '输出严格 JSON', 'system_cast': '输出严格 JSON',
    'system_write': '如需核实', 'system_book_outline': '输出严格 JSON',
    'system_short_plan': '输出严格 JSON', 'system_short_plan_review': '输出严格 JSON',
    'system_short_writer': '输出格式（', 'system_short_draft_review': '输出严格 JSON',
    'system_short_reviser': '- 章数、章序', 'system_short_continuer': '- **只输出缺失',
    'system_extract': '输出严格 JSON', 'system_summarize': '输出严格 JSON',
    'system_revise': '输出格式：', 'system_revise_patch': 'TARGET_TEXT 从原稿',
    'system_audit': '输出严格 JSON', 'system_reflexion': '输出严格 JSON',
    'system_global_audit': '输出严格 JSON', 'system_ledger_l2': '输出严格 JSON',
    'system_style_extract': '输出严格 JSON', 'system_short_creation': '输出严格 JSON',
}


def split_template(template_id, content):
    """Expose business prose while preserving schemas and parser instructions.

    JSON examples deliberately retain their field documentation as part of the
    schema contract. Post-schema creative rules are editable unless they mention
    concrete protocol keys, routing values, tools or output encoding.
    """
    import re
    marker = '输出严格 JSON' if template_id.startswith('book_setup_') else _PROTOCOL_START[template_id]
    if marker not in content:
        return content, ""
    start = content.index(marker)
    if 'JSON' in marker:
        brace = content.index('{', start)
        depth = 0
        end = len(content)
        for i in range(brace, len(content)):
            if content[i] == '{': depth += 1
            elif content[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
    elif template_id == 'system_short_writer':
        end = content.index('三条硬要求', start)
    elif template_id == 'system_short_continuer':
        end = content.index('\n', start)
    else:
        end = len(content)
    if template_id == 'system_batch_plan':
        end = len(content)  # The trailing N-item count is part of the parser contract.
    editable = [content[:start].strip()]
    fixed = [content[start:end].strip()]
    for line in content[end:].splitlines():
        if not line.strip():
            continue
        # These identifiers and output/tool instructions are a protocol contract,
        # including capability-dependent fields in book_setup.
        protocol = re.search(r'[A-Za-z_]{2,}|JSON|纯文本|代码块|只读|工具|输出空数组|不承诺|建书由作者', line)
        (fixed if protocol else editable).append(line)
    return '\n'.join(editable), '\n'.join(fixed)


def apply_role_prompts(messages, role, snapshot):
    """Use only the admitted immutable publication; old snapshots stay legacy."""
    from copy import deepcopy
    publication = (snapshot or {}).get('role_prompts', {}).get(role)
    if not publication:
        return messages
    replacements = publication['body'].get('templates', {})
    group = next(g for g in prompt_catalog() if g['role'] == role)
    output = deepcopy(messages)
    # One pass over non-overlapping full templates handles composed revision
    # messages and prevents shorter book_setup variants matching a longer phase.
    import re
    by_content = {t['content']: t for t in group['templates']}
    pattern = re.compile('|'.join(re.escape(text) for text in sorted(by_content, key=len, reverse=True)))
    def replace(match):
        template = by_content[match.group()]
        edited = replacements.get(template['id'])
        if edited is None or edited == template['editable_content']:
            return match.group()
        return edited + '\n\n【固定输出与工具规范】\n' + template['fixed_content']
    for message in output:
        if message.get('role') == 'system':
            message['content'] = pattern.sub(replace, message.get('content', ''))
    return output
