"""Reference-only access for creation stages without chapter inspection tools."""
from types import SimpleNamespace


def reference_tools():
    from myink.writing_resource_runtime import has_reference_material
    if not has_reference_material():
        return None
    from myink.workflow.tools import READ_TOOLS
    return [tool for tool in READ_TOOLS if tool['function']['name'] == 'read_genre_reference']


def generate_with_references(db, project_id, node, role, chain, messages, *,
                             task_id=None, user_id=None, generate=None, **options):
    """Keep admission/streaming/accounting and freeze resource reads for every round.

    The caller records the final response with returned tool_trace; the shared loop
    records intermediate model responses, so cost is neither lost nor double counted.
    Account callers supply their admitted generate function, used on EVERY round.
    """
    from myink.config import settings
    from myink.workflow import nodes
    runner = (SimpleNamespace(chain=getattr(chain, 'chain', []), generate=generate or chain.generate)
              if generate or not hasattr(chain, 'chain') else chain)
    tools = reference_tools()
    if not tools:
        return nodes._bounded_generate(runner, messages, **options), []
    return nodes._run_tool_loop(db,
        {'project_id': project_id, 'user_id': user_id, 'task_id': task_id}, node, role,
        runner, messages, tools=tools, max_tool_calls=settings.max_tool_calls,
        max_tokens=options.get('max_tokens'), final_json=options.get('json_mode', True),
        streamer=options.get('streamer'), disable_thinking=options.get('disable_thinking', False),
        record_final=False,
        final_instruction='请基于查阅结果遵循原始输出格式直接输出最终结果，不要再调用工具。')
