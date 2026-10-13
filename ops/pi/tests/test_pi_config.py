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


def test_default_no_tools_loads_only_fixed_pure_text_guard(tmp_path):
    import ops.pi.pi_config as module
    config = make_pi_config(tmp_path, {'base_url': 'http://127.0.0.1:8088', 'scope_token': 'mock'}, SimpleNamespace(model='mock', max_tokens=64))
    guard = Path(module.__file__).parent / 'lab/pi-wire-guard.mjs'
    assert config['args'][-2:] == ['-e', str(guard)]
    assert config['args'].count('-e') == 1
    assert all(flag in config['args'] for flag in ('--no-tools', '--no-builtin-tools', '--no-extensions', '--no-mcp', '--no-skills', '--no-context-files', '--no-approve'))
    assert not any(key.startswith('PI_TOOL_') for key in config['env'])


def test_default_guard_tampering_is_rejected_in_fixed_install_path(tmp_path, monkeypatch):
    import ops.pi.pi_config as module
    original = Path(module.__file__).parent / 'lab/pi-wire-guard.mjs'
    install = tmp_path / 'install'
    guard = install / 'lab/pi-wire-guard.mjs'
    guard.parent.mkdir(parents=True)
    guard.write_bytes(original.read_bytes())
    monkeypatch.setattr(module, '__file__', str(install / 'pi_config.py'))
    gateway = {'base_url': 'http://127.0.0.1:8088', 'scope_token': 'mock'}
    policy = SimpleNamespace(model='mock', max_tokens=64)
    assert make_pi_config(tmp_path, gateway, policy)['args'][-1] == str(guard)
    guard.write_bytes(guard.read_bytes() + b'// tampered')
    with pytest.raises(ValueError, match='pinned pure text'):
        make_pi_config(tmp_path, gateway, policy)


def test_default_guard_requires_absolute_owned_install_and_private_root(tmp_path, monkeypatch):
    import ops.pi.pi_config as module
    gateway = {'base_url': 'http://127.0.0.1:8088', 'scope_token': 'mock'}
    policy = SimpleNamespace(model='mock', max_tokens=64)
    with pytest.raises(ValueError, match='private absolute root'):
        make_pi_config(Path('relative'), gateway, policy)
    monkeypatch.setattr(module, '__file__', 'relative/pi_config.py')
    with pytest.raises(ValueError, match='pinned pure text'):
        make_pi_config(tmp_path, gateway, policy)
