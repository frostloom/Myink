"""Trusted host provider configuration. Never expose this module as a model tool."""
import json
from pathlib import Path
import re
import sqlite3


DEFAULT_MODEL = 'deepseek-flash'
ANALYSIS_MODELS = (DEFAULT_MODEL, 'deepseek-v4.1-flash')
DEEPSEEK_BASE_URL = 'https://api.deepseek.com/anthropic'
_FIELDS = {'PLATFORM_MODEL_API_KEY', 'PLATFORM_MODEL_BASE_URL',
           'PLATFORM_MODEL_NAME', 'PLATFORM_MODEL_PROTOCOL'}
_ERROR = 'trusted provider configuration invalid'


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(_ERROR)
        result[key] = value
    return result


def _key(value):
    # Literal HTTP token only: no env references, shell commands or header injection.
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9._~+/=-]{1,4096}', value) is not None


def cc_switch_deepseek_credentials(database):
    """Read the unique Pi/DeepSeek entry; map its official key to Anthropic API.

    CC-Switch's active provider and database are never changed. Models and all
    provider endpoints are host-selected; supplied config commands are inert.
    """
    db = None
    try:
        path = Path(database).resolve(strict=True)
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, isolation_level=None, timeout=5)
        db.execute('PRAGMA query_only=ON')
        rows = db.execute("SELECT settings_config FROM providers WHERE app_type='pi' AND lower(name)='deepseek'").fetchall()
        if len(rows) != 1:
            raise ValueError(_ERROR)
        cfg = json.loads(rows[0][0], object_pairs_hook=_pairs)
        if (not isinstance(cfg, dict) or cfg.get('baseUrl') not in (
                'https://api.deepseek.com', 'https://api.deepseek.com/v1', DEEPSEEK_BASE_URL)
                or (cfg.get('api'), cfg.get('baseUrl')) not in (
                    ('openai-completions', 'https://api.deepseek.com'),
                    ('openai-completions', 'https://api.deepseek.com/v1'),
                    ('anthropic-messages', DEEPSEEK_BASE_URL))
                or not _key(cfg.get('apiKey')) or not isinstance(cfg.get('models'), list)
                or not any(isinstance(model, dict) and model.get('id') == DEFAULT_MODEL
                           for model in cfg['models'])):
            raise ValueError(_ERROR)
        return dict(PLATFORM_MODEL_API_KEY=cfg['apiKey'], PLATFORM_MODEL_BASE_URL=DEEPSEEK_BASE_URL,
                    PLATFORM_MODEL_NAME=DEFAULT_MODEL, PLATFORM_MODEL_PROTOCOL='anthropic')
    except (OSError, sqlite3.DatabaseError, ValueError, TypeError, KeyError, RuntimeError):
        raise ValueError(_ERROR) from None
    finally:
        if db is not None:
            db.close()


def load_credentials(path, policy):
    """Load one private snapshot; validate identity before constructing HTTP headers."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_pairs)
        if (not isinstance(data, dict) or set(data) != _FIELDS
                or not all(isinstance(value, str) and value.strip() for value in data.values())
                or not _key(data['PLATFORM_MODEL_API_KEY'])
                or data['PLATFORM_MODEL_BASE_URL'].rstrip('/') != policy.base_url.rstrip('/')
                or data['PLATFORM_MODEL_NAME'] != policy.model
                or data['PLATFORM_MODEL_PROTOCOL'] != policy.protocol):
            raise ValueError(_ERROR)
        return data
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        raise ValueError(_ERROR) from None
