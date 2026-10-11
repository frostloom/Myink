from pathlib import Path
from types import SimpleNamespace
import pytest
from ops.pi.pi_config import make_pi_config


def test_private_config_drops_ambient_credentials_and_discovery(tmp_path):
    config = make_pi_config(tmp_path, {'base_url': 'http://127.0.0.1:8088', 'scope_token': 'mock-only', 'mock': True}, SimpleNamespace(model='mock-model', max_tokens=64))
    assert config['env']['PI_TELEMETRY'] == '0'
    assert config['env']['SCOPED_GATEWAY_TOKEN'] == 'mock-only'
    assert 'ANTHROPIC_API_KEY' not in config['env']
    assert all(Path(config['env'][name]).is_relative_to(tmp_path) for name in ('HOME', 'TMPDIR', 'PI_CODING_AGENT_DIR', 'NODE_COMPILE_CACHE'))
    assert config['settings']['cacheWarming'] == 'off'
    assert config['settings']['retry']['enabled'] is False
    assert config['settings']['compaction']['enabled'] is False
    assert config['settings']['enableInstallTelemetry'] is False
    assert config['models']['providers']['myink-budget']['apiKey'] == '$SCOPED_GATEWAY_TOKEN'
    assert '--no-builtin-tools' in config['args'] and '--no-context-files' in config['args']


@pytest.mark.parametrize('url', ['https://third-party.example', 'http://localhost:8088', 'http://127.0.0.1:8088/?x=1'])
def test_config_rejects_untrusted_gateway_url(tmp_path, url):
    with pytest.raises(ValueError):
        make_pi_config(tmp_path, {'base_url': url, 'scope_token': 'mock', 'mock': True}, SimpleNamespace(model='mock-model', max_tokens=64))
