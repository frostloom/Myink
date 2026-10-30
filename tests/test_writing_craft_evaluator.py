"""Live evaluator must not judge conditions it forgot to send to the writer."""
import base64
import json
import logging
from pathlib import Path
import runpy
from types import SimpleNamespace
import sys


def test_all_required_terminal_facts_reach_actual_writer_messages(monkeypatch):
    from myink.providers.base import ModelResponse
    import myink.platform_configuration as configuration
    from myink.writing_resource_seed import builtin_resources
    from myink.chapter_craft import CHAPTER_CONTINUITY_RULES, CRAFT_LESSON
    from myink.seed import STYLE_PRESETS

    monkeypatch.setattr(configuration, 'load_configuration', lambda: {})
    entries = [dict(r, current_version=1) for r in builtin_resources()]
    monkeypatch.setattr('myink.writing_resources.catalog', lambda *a, **kw: entries)
    monkeypatch.setattr('myink.writing_resources.capture_role_prompts', lambda *a: {})
    class ReadSession:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr('myink.db.new_session', ReadSession)
    monkeypatch.setattr(configuration, 'resolve_connection', lambda *a, **kw: {'model': 'synthetic-test'})
    seen = []
    class Provider:
        _client = SimpleNamespace(event_hooks={'request': []})
        def generate(self, messages, **kwargs):
            for hook in self._client.event_hooks['request']:
                hook(None)
            text = '\n'.join(m['content'] for m in messages)
            if '"drafts"' in text:
                content = json.dumps({'ranking': ['X', 'Y', 'Z'], 'reasons': {}, 'hard_violations': {}})
            else:
                assert 'ALL_REQUIRED_TERMINAL_FACTS' in text
                assert 'ATOMIC_EVENT' in text and 'GIVEN_FACT' in text and 'PREVIOUS_TAIL' in text
                seen.append(text)
                content = '=== CONTENT ===\n合成文本。'
            return ModelResponse(content=content, model_id='synthetic-test', finish_reason='stop')
    monkeypatch.setattr('myink.providers._chain_from_override', lambda *a: SimpleNamespace(providers=[Provider()]))
    monkeypatch.setattr('myink.providers.connections.price_table', lambda *a: None)
    monkeypatch.setattr('myink.providers.prices.lookup_prices', lambda *a: None)
    case = dict(id='test', genre='现实题材', style='character-narration', previous_tail='PREVIOUS_TAIL',
                facts=['GIVEN_FACT'], goal='GOAL', expected_events=['ATOMIC_EVENT'], must_end='ALL_REQUIRED_TERMINAL_FACTS')
    payload = dict(app_source='test', continuity=CHAPTER_CONTINUITY_RULES, lesson=CRAFT_LESSON,
                   profiles={p["id"]: p["style_profile"] for p in STYLE_PRESETS}, cases=[case])
    monkeypatch.setenv('CRAFT_EVAL_PAYLOAD', base64.b64encode(json.dumps(payload).encode()).decode())
    monkeypatch.setattr(sys, 'argv', ['evaluate-writing-craft.py', '--allow-live', '--max-requests', '15'])
    disabled = logging.root.manager.disable
    try:
        runpy.run_path(str(Path(__file__).parents[1] / 'scripts/evaluate-writing-craft.py'), run_name='__main__')
    finally:
        logging.disable(disabled)
    assert len(seen) >= 3
