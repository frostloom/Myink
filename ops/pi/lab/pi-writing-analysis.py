"""One useful frozen writing-data analysis; containment/gateway are host-owned."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from ops.pi.engine import AdministratorContext, EngineSession
from ops.pi.pi_config import make_pi_config
from ops.pi.pi_rpc import PiAdapter
from ops.pi.policy import load_policy
from ops.pi.writing_analysis import (PRIVATE_ROOT, SYSTEM_PROMPT, _safe_path,
    analysis_receipt, build_writing_prompt, load_analysis_inputs, preflight_request,
    require_private_root)


def serialize_receipt(output):
    """Escape untrusted evidence, including lone surrogates, without losing it."""
    return (json.dumps(output, ensure_ascii=True, indent=2) + '\n').encode('utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser()
    for name in ('root', 'input', 'report', 'policy', 'scope-token-file'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--input-sha256', required=True)
    parser.add_argument('--report-sha256', required=True)
    parser.add_argument('--gateway-port', required=True, type=int)
    parser.add_argument('--target-domain', required=True)
    args = parser.parse_args(argv)
    require_private_root(args.root)
    root = _safe_path(args.root, PRIVATE_ROOT)
    if not root.is_dir() or not 1 <= args.gateway_port <= 65535:
        raise ValueError('private run directory and loopback port required')
    receipt_path = root / 'writing-analysis-receipt.json'
    if receipt_path.exists():
        raise ValueError('fresh private receipt required')
    loaded = load_analysis_inputs(args.input, args.input_sha256, args.report, args.report_sha256)
    prompt = build_writing_prompt(loaded['view'], loaded['report'], target_domain=args.target_domain)
    policy = load_policy(_safe_path(args.policy, PRIVATE_ROOT))
    if (policy.max_attempts != 100 or policy.budget_microyuan != 10000000
            or policy.max_body_bytes != 65536 or policy.max_tokens != 2048
            or policy.input_token_bound != 1000000 or policy.server_daily_enabled):
        raise ValueError('reviewed finite writing-analysis policy required')
    cwd = _safe_path(root / 'candidate', PRIVATE_ROOT, existing=False)
    sizes = preflight_request(prompt, model=policy.model, cwd=cwd)
    token_path = _safe_path(args.scope_token_file, PRIVATE_ROOT)
    if not token_path.is_file() or token_path.stat().st_size > 4096:
        raise ValueError('bounded regular scoped-token file required')
    token = token_path.read_text(encoding='utf-8').strip()
    config = make_pi_config(root, {'base_url': f'http://127.0.0.1:{args.gateway_port}',
                                 'scope_token': token}, policy)
    config['args'] += ['--system-prompt', SYSTEM_PROMPT]
    for name, value in config['env'].items():
        if name not in ('PI_TELEMETRY', 'PI_OFFLINE', 'SCOPED_GATEWAY_TOKEN'):
            _safe_path(Path(value), PRIVATE_ROOT, existing=False).mkdir(parents=True, exist_ok=True)
    agent = Path(config['env']['PI_CODING_AGENT_DIR'])
    for name, value in [('settings.json', config['settings']), ('models.json', config['models'])]:
        _safe_path(agent / name, PRIVATE_ROOT, existing=False).write_text(json.dumps(value), encoding='utf-8')
    cwd.mkdir(exist_ok=False)
    node = Path('/Users/a1/项目/Myink/myink-pi/runtime/node/node-v24.22.0-darwin-arm64/bin/node')
    cli = Path('/Users/a1/项目/Myink/myink-pi/runtime/pi-project/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js')
    guard = Path(__file__).parent / 'pi-wire-guard.mjs'
    config_hash = hashlib.sha256(json.dumps({k: v for k, v in config.items() if k != 'env'},
        sort_keys=True).encode() + guard.read_bytes()).hexdigest()
    command = [str(node), str(cli), *config['args'], '-e', str(guard)]
    env = {**config['env'], 'PATH': str(node.parent) + ':/usr/bin:/bin', 'LANG': 'C.UTF-8'}
    context = AdministratorContext('local-trial-1', 'c15b-writing-data-analysis', 'local-trial-1',
                                   json.dumps(loaded['identity'], sort_keys=True))
    session = EngineSession('pi', config_hash, 'analysis', root / 'sessions' / 'analysis.jsonl')
    _safe_path(session.session_path, PRIVATE_ROOT, existing=False)
    adapter = PiAdapter(command, cwd=cwd, env=env, config_hash=config_hash)
    receipt = adapter.run_phase(phase='analysis', prompt=prompt, context=context, session=session,
        deadline=datetime.now(timezone.utc) + timedelta(seconds=min(policy.timeout_seconds, 90)), tools=[])
    output = analysis_receipt(receipt, loaded['view'], loaded['identity'])
    output['request_bytes'] = sizes
    output['prompt_sha256'] = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    raw = serialize_receipt(output)
    with receipt_path.open('xb') as target:
        target.write(raw)
    analysis = output['analysis']
    print(json.dumps(dict(status=output['status'], receipt_sha256=hashlib.sha256(raw).hexdigest(),
        view_sha256=args.input_sha256, report_sha256=args.report_sha256,
        session_sha256=receipt.evidence.get('session_sha256'),
        domains=len(analysis['domains']) if analysis else 0, request_bytes=sizes)))
    return 0 if output['status'] == 'done' else 1


if __name__ == '__main__':
    raise SystemExit(main())
