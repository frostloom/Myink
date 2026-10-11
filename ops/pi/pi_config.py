"""Fixed private Pi configuration; the controller supplies a scoped gateway token."""
from pathlib import Path
from urllib.parse import urlsplit
from .contracts import Record
from .policy import Policy


def make_pi_config(root: Path, gateway: Record, policy: Policy) -> Record:
    root = Path(root)
    if not root.is_absolute() or '..' in root.parts or root.is_symlink():
        raise ValueError('private absolute root required')
    url = urlsplit(gateway.get('base_url', ''))
    if (url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port
            or url.username or url.password or url.query or url.fragment or url.path not in ('', '/')):
        raise ValueError('trusted loopback gateway required')
    token = gateway.get('scope_token')
    if not isinstance(token, str) or not token or len(token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError('scoped token required')
    env = {name: str(root / suffix) for name, suffix in {
        'HOME': 'home', 'XDG_CONFIG_HOME': 'config', 'XDG_CACHE_HOME': 'cache',
        'XDG_DATA_HOME': 'data', 'TMPDIR': 'tmp', 'TMP': 'tmp', 'TEMP': 'tmp',
        'PI_CODING_AGENT_DIR': 'agent', 'NODE_COMPILE_CACHE': 'compile-cache',
        'npm_config_cache': 'npm-cache'}.items()}
    env.update(PI_TELEMETRY='0', PI_OFFLINE='1', SCOPED_GATEWAY_TOKEN=token)
    settings = {'defaultProvider': 'myink-budget', 'defaultModel': policy.model,
        'defaultThinkingLevel': 'off', 'enabledModels': ['myink-budget/' + policy.model],
        'cacheWarming': 'off', 'transport': 'sse', 'compaction': {'enabled': False},
        'retry': {'enabled': False, 'provider': {'maxRetries': 0}},
        'enableInstallTelemetry': False, 'enableAnalytics': False,
        'packages': [], 'extensions': [], 'skills': [], 'promptTemplates': [], 'themes': []}
    models = {'providers': {'myink-budget': {'baseUrl': gateway['base_url'],
        'api': 'anthropic-messages', 'apiKey': '$SCOPED_GATEWAY_TOKEN',
        'headers': {'X-Pi-Scope': 'local-trial-1'},
        'models': [{'id': policy.model, 'name': policy.model, 'reasoning': False,
                    'input': ['text'], 'contextWindow': 1000000, 'maxTokens': policy.max_tokens}]}}}
    args = ['--mode', 'rpc', '--offline', '--provider', 'myink-budget', '--model', policy.model,
        '--models', 'myink-budget/' + policy.model, '--thinking', 'off', '--no-tools',
        '--no-builtin-tools', '--no-mcp', '--no-extensions', '--no-skills',
        '--no-prompt-templates', '--no-themes', '--no-context-files', '--no-approve']
    return {'env': env, 'settings': settings, 'models': models, 'args': args}
