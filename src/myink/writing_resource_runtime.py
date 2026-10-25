"""Frozen project writing choices, scoped to one execution and its tools."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import json

_resources = ContextVar("writing_resources", default=None)

def current_resources():
    return deepcopy(_resources.get())

def configured():
    return bool((_resources.get() or {}).get("configured"))

@contextmanager
def bind_resources(snapshot):
    token = _resources.set(deepcopy(snapshot))
    try:
        yield
    finally:
        _resources.reset(token)

def selected(kind):
    return [s for s in (_resources.get() or {}).get("selections", []) if s["kind"] == kind]

def selected_genre():
    genres = selected("genre")
    if not genres:
        return {}
    body = genres[0]["body"]
    return {**deepcopy(body.get("fields", {})), "source_id":body.get("catalog_id"),
            "source_name":genres[0]["name"], "_resource_caps":body.get("setup_caps", {})}

def validation_flag(name):
    if not configured():
        return True
    return any(s["body"].get("validation", {}).get(name, False)
               for s in selected("expression_rule") + selected("writing_rule"))

def reference_read(path, section=None, db=None):
    from myink.reference_corpus import MAX_READ_CHARS, markdown_sections, slice_section
    from myink.writing_resources import is_writing_reference
    files = {f["path"]: f["content"] for s in selected("reference")
             for f in s["body"].get("files", [])}
    pointers = {}
    for entry in (_resources.get() or {}).get("reference_library", []):
        for f in entry.get("files", []):
            if is_writing_reference(f["path"]):
                pointers.setdefault(f["path"], entry)
    if not path:
        result = {"files": [], "truncated": False}
        for p in dict.fromkeys([*files, *pointers]):
            entry = {"path": p}
            if p in files:
                entry['sections'] = markdown_sections(files[p][:MAX_READ_CHARS], 2)
            result["files"].append(entry)
            if len(result["files"]) > 80 or len(json.dumps(result, ensure_ascii=False)) > 12000:
                result["files"].pop()
                result["truncated"] = True
                break
        return result
    if path.startswith('/') or "\\" in path or any(p in ('', '.', '..') for p in path.split('/')):
        return {"error": "Invalid reference path"}
    text = files.get(path)
    if text is None and path in pointers:
        if db is None:
            from myink.db import new_session
            with new_session() as read_db:
                return reference_read(path, section, db=read_db)
        from myink.models.writing_resource import WritingResourceRevision
        pointer = pointers[path]
        revision = db.get(WritingResourceRevision, (pointer['resource_id'], pointer['version']))
        if revision is not None:
            text = next((f['content'] for f in revision.document['body'].get('files', [])
                         if f['path'] == path), None)
    if text is None:
        return {"error": "Reference is not available for this task"}
    if section:
        text = slice_section(text, section)
        if text is None:
            return {"error": "Section not found"}
    return {"path": path, "content": text[:MAX_READ_CHARS], "truncated": len(text) > MAX_READ_CHARS}


def has_reference_material():
    return (any(entry.get('files') for entry in (_resources.get() or {}).get('reference_library', []))
            or any(entry['body'].get('files') for entry in selected('reference')))


def automatic_reference_messages(role):
    if role in {"writer", "planner", "audit"} and has_reference_material():
        directory = reference_read('')
        paths = [entry['path'] for entry in directory['files']]
        return [{"role": "system", "content": (
            "【基础写作资料库的使用时机】当本环节需要设计或判断人物动机与关系、桥段、题材机制、"
            "爽点节奏、命名或故事结构时，先用 read_genre_reference 查相关方法，再形成创作结果；"
            "不要只凭印象声称参考过资料。首次不知道路径时，空参数获取目录，再按返回路径读取相关文件或小节。"
            "只查当前问题需要的资料，不要遍历整个资料库；同一轮已查过且内容够用时不要重复读取。"
            "若当前环节只是依据明确要求做局部文字修订、不需要这些写作方法，可不查询。"
            "资料是写作方法与示例，本书人物事实与作者设定优先，作品私有参考资料优先。"
            "\n【本任务可查阅的准确路径】下面只列目录，不含资料正文。优先从这些路径直接读取，"
            "不要猜测或缩写文件名；已看到目录时不要重复请求相同目录。"
            + ("这里只列部分路径，需要其他资料时可再查完整目录。" if directory.get('truncated') else "")
            + "\n" + json.dumps(paths, ensure_ascii=False)) }]
    return []



def with_reference_library(messages, role):
    # Keep the original leading role instructions and final user request in place.
    hints = automatic_reference_messages(role)
    if not hints:
        return messages
    index = next((i for i, message in enumerate(messages) if message.get('role') == 'user'), len(messages))
    return messages[:index] + hints + messages[index:]


def resource_messages(builder, role):
    @wraps(builder)
    def wrapped(*args, **kwargs):
        import inspect
        bound = inspect.signature(builder).bind(*args, **kwargs)
        bound.apply_defaults()
        if configured():
            if "genre_pack" in bound.arguments:
                bound.arguments["genre_pack"] = selected_genre()
            if "genre" in bound.arguments:
                bound.arguments["genre"] = "、".join(s["name"] for s in selected("genre"))
            if "brief" in bound.arguments:
                brief = deepcopy(bound.arguments["brief"])
                brief.update(genre_pack=selected_genre(),
                             genre="、".join(s["name"] for s in selected("genre")))
                bound.arguments["brief"] = brief
            messages = builder(*bound.args, **bound.kwargs)
        else:
            messages = builder(*args, **kwargs)
        from myink.prompt_catalog import apply_role_prompts
        messages = apply_role_prompts(messages, role, current_resources())
        if not configured():
            # Automatic role publications also consume the final request budget.
            # Rebuild from each trimmed context so optional recall can make room;
            # role instructions, fixed schemas and required input are never cut.
            from myink.context_budget import fit_prompt
            from myink.workflow.prompts import _tool_prompt_budget
            def render_automatic(context):
                if "context" in bound.arguments:
                    bound.arguments["context"] = context
                from myink.workflow.prose_rules import with_legacy_prose
                rendered = apply_role_prompts(builder(*bound.args, **bound.kwargs), role, current_resources())
                return with_reference_library(with_legacy_prose(rendered, builder.__name__), role)
            return fit_prompt(bound.arguments.get("context") or {}, render_automatic, _tool_prompt_budget())
        from myink.writing_resource_seed import optional_fragments
        messages = deepcopy(messages)
        for message in messages:
            if message.get("role") != "system":
                continue
            for fragment in optional_fragments():
                message["content"] = message.get("content", "").replace(fragment, "")
        parts = []
        genres = selected("genre")
        primary_id = genres[0]["body"].get("catalog_id") if genres else None
        if len(genres) > 1 and role in {"writer", "planner", "audit"}:
            parts.append("主辅比例：7:3。首个选定题材为主题材，占七成；其余辅题材合计三成。"
                         "主线、节奏、禁忌和世界观遵循主题材；辅题材只提供钩子、规则和爽点，"
                         "辅题材不得覆盖主题材硬约束，不改主题材主线。")
        for s in (_resources.get() or {}).get("selections", []):
            body = s["body"]
            # Non-creative roles accept only rules explicitly scoped to their role.
            if role not in {"writer", "planner", "audit"} and s["kind"] in {"genre", "style", "reference", "genre_rule"}:
                continue
            if s["kind"] == "genre":
                label = "主题材" if s is genres[0] else "辅题材"
                parts.append(label + "：" + s["name"] + "\n" + json.dumps(body.get("fields", {}), ensure_ascii=False))
            elif s["kind"] == "style":
                from myink.workflow.prompts import _style_section
                parts.append(_style_section(body.get("profile", {}), None))
            elif s["kind"] == "reference":
                parts.append("可读参考资料：" + "、".join(f["path"] for f in body.get("files", [])))
            else:
                if s["kind"] == "genre_rule" and body.get("genre_ids"):
                    genre_ids = {g["body"].get("catalog_id") for g in selected("genre")}
                    if not genre_ids.intersection(body["genre_ids"]):
                        continue
                text = body.get("roles", {}).get(role, "")
                if text:
                    if s["kind"] == "genre_rule" and body.get("genre_ids"):
                        if primary_id in body["genre_ids"]:
                            text = ("主题材精调（七成）：" if len(genres) > 1 else "主题材精调：") + text
                        else:
                            text = "辅题材精调（合计三成，服从主题材）：" + text
                    parts.append(text)
        addition = [{"role": "system", "content": "【作品选定写作资源】\n作品私有文风档案、作者样本和人物口吻优先于以下通用建议。\n" + "\n".join(parts)}] if parts else []
        from myink.context_budget import fit_prompt
        from myink.workflow.prompts import _tool_prompt_budget
        if "context" in bound.arguments:
            def render(context):
                bound.arguments["context"] = context
                output = apply_role_prompts(builder(*bound.args, **bound.kwargs), role, current_resources())
                for message in output:
                    if message.get("role") != "system":
                        continue
                    for fragment in optional_fragments():
                        message["content"] = message.get("content", "").replace(fragment, "")
                return with_reference_library(output + addition, role)
            return fit_prompt(bound.arguments["context"] or {}, render, _tool_prompt_budget())
        return fit_prompt({}, lambda _: with_reference_library(messages + addition, role), _tool_prompt_budget())
    return wrapped


def project_resources(function):
    """Synchronous planning reads once at call admission, then stays frozen."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        import inspect
        params = inspect.signature(function).bind(*args, **kwargs).arguments
        project_id, db = params.get("project_id"), params.get("db")
        if current_resources() is not None or (not project_id and db is None and not params.get("user_id")):
            return function(*args, **kwargs)
        from myink.writing_resources import capture_task_resources
        if db is not None:
            snapshot = capture_task_resources(db, project_id)
        else:
            from myink.db import tenant_session
            from myink.db import new_session
            with (tenant_session(str(project_id)) if project_id else new_session()) as session:
                snapshot = capture_task_resources(session, project_id)
        with bind_resources(snapshot):
            return function(*args, **kwargs)
    return wrapped
