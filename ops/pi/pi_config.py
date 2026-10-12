"""Fixed private Pi configuration; the controller supplies a scoped gateway token."""
from pathlib import Path
import hashlib
from urllib.parse import urlsplit
from .contracts import Record
from .policy import Policy


def make_pi_config(root: Path, gateway: Record, policy: Policy, *, controlled_tools=None) -> Record:
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
    if controlled_tools is not None:
        from .tools import PHASE_TOOLS
        expected = {'phase','extension_sha256','schema_sha256','guard_sha256','broker_url','scope_token'}
        if (not isinstance(controlled_tools, dict) or set(controlled_tools) != expected
                or controlled_tools['phase'] not in PHASE_TOOLS
                or controlled_tools['broker_url'].rstrip('/') != gateway['base_url'].rstrip('/')):
            raise ValueError('fixed controller tool profile required')
        tool_token = controlled_tools['scope_token']
        if not isinstance(tool_token, str) or not tool_token or len(tool_token) > 4096 or any(not 33 <= ord(c) <= 126 for c in tool_token):
            raise ValueError('scoped broker token required')
        extension = Path(__file__).parent / 'extensions/controlled-tools.ts'
        for path, key in ((extension,'extension_sha256'), (extension.with_name('tool-schemas.json'),'schema_sha256'),
                          (Path(__file__).parent/'lab/pi-wire-guard.mjs','guard_sha256')):
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != controlled_tools[key]:
                raise ValueError('pinned owned tool closure hash mismatch')
        env.update(PI_TOOL_PHASE=controlled_tools['phase'],PI_TOOL_BROKER_URL=controlled_tools['broker_url'],
                   PI_TOOL_SCOPE_TOKEN=tool_token)
        models['providers']['myink-budget']['models'][0]['compat'] = {'supportsEagerToolInputStreaming': False}
        # Suppress pinned SDK automatic beta features before strict wire validation.
        models['providers']['myink-budget']['models'][0]['headers'] = {'anthropic-beta': ''}
        args.remove('--no-tools')
        args += ['-e',str(extension)]
    return {'env': env, 'settings': settings, 'models': models, 'args': args}
