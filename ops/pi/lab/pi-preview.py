"""One read-only administrator analysis through an already authorized scoped gateway.
The trusted host owns gateway authorization, source preparation and OS containment.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from ops.pi.engine import AdministratorContext, EngineSession
from ops.pi.pi_config import make_pi_config
from ops.pi.pi_rpc import PiAdapter
from ops.pi.policy import load_policy


def build_analysis_prompt(snapshot):
    if (not isinstance(snapshot, dict) or snapshot.get('kind')!='readonly_source_preview'
            or snapshot.get('evidence_domain')!='source_only'
            or snapshot.get('new_features_require_owner') is not True):
        raise ValueError('trusted source-only preview required')
    return ('你是 Myink 集成管理员，角色为 myink-administrator。仅分析以下固定提交的源码摘录。'
        '提出恰好一个针对既有行为的小优化假设，范围限稳定性、成本、速度、写作质量或使用体验。'
        '新功能方向由 owner 决定，本次不调用工具、不修改文件。源码分析不能证明运行效果，baseline is not measured。'
        '只输出一个小 JSON 对象，不要 Markdown。必须恰好包含七个字段：hypothesis（中文非空字符串），'
        'source_evidence（数组，每项恰好为 {"path":"摘录文件路径","quote":"摘录中逐字连续片段"}），'
        'baseline（恰好为 {"availability":"unknown","reason":"中文原因"}），'
        'candidate_metrics、tests、risks（各为非空中文字符串数组），'
        'owner_decision（恰好为 {"new_features_require_owner":true}）。'
        '至少一条 source_evidence 必须逐字匹配给出的真实文件摘录。描述为待验证假设，不声称改进已发生。\n'
        + json.dumps(snapshot,ensure_ascii=False,sort_keys=True))


def validate_analysis_plan(plan, snapshot):
    required={'hypothesis','source_evidence','baseline','candidate_metrics','tests','risks','owner_decision'}
    if not isinstance(plan,dict) or set(plan)!=required or len(json.dumps(plan,ensure_ascii=False).encode())>32768:
        raise ValueError('finite seven-field source plan required')
    if not isinstance(plan['hypothesis'],str) or not plan['hypothesis'].strip():
        raise ValueError('hypothesis required')
    baseline=plan['baseline']
    if (not isinstance(baseline,dict) or set(baseline)!={'availability','reason'}
            or baseline['availability']!='unknown' or not isinstance(baseline['reason'],str) or not baseline['reason'].strip()):
        raise ValueError('source baseline must remain unknown')
    owner=plan['owner_decision']
    if not isinstance(owner,dict) or set(owner)!={'new_features_require_owner'} or owner['new_features_require_owner'] is not True:
        raise ValueError('owner feature authority required')
    for name in ('candidate_metrics','tests','risks'):
        if not isinstance(plan[name],list) or not plan[name] or not all(isinstance(v,str) and v.strip() for v in plan[name]):
            raise ValueError('finite proposal list required')
    excerpts={item['path']:item['excerpt'] for item in snapshot['files']}
    evidence=plan['source_evidence']
    if not isinstance(evidence,list) or not evidence or len(evidence)>3:
        raise ValueError('quoted source evidence required')
    for item in evidence:
        if (not isinstance(item,dict) or set(item)!={'path','quote'} or not isinstance(item['path'],str)
                or not isinstance(item['quote'],str) or not item['quote'].strip() or len(item['quote'])>512
                or item['path'] not in excerpts or item['quote'] not in excerpts[item['path']]):
            raise ValueError('quote must match trusted source excerpt')
    return plan


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--input-sha256',required=True)
    parser.add_argument('--policy',required=True,type=Path)
    parser.add_argument('--gateway-port',required=True,type=int)
    parser.add_argument('--scope-token-file',required=True,type=Path)
    args=parser.parse_args(argv)
    root=args.root
    from ops.pi.writing_analysis import require_private_root
    require_private_root(root)
    raw=args.input.read_bytes()
    if len(raw)>65536 or not re.fullmatch('[a-f0-9]{64}',args.input_sha256) or hashlib.sha256(raw).hexdigest()!=args.input_sha256:
        raise ValueError('trusted snapshot hash/size mismatch')
    snapshot=json.loads(raw)
    prompt=build_analysis_prompt(snapshot)
    policy=load_policy(args.policy)
    if (policy.max_attempts!=100 or policy.budget_microyuan!=10000000 or policy.max_body_bytes>65536
            or policy.max_tokens>2048 or policy.input_token_bound!=1000000 or policy.server_daily_enabled):
        raise ValueError('reviewed finite preview policy required')
    token=args.scope_token_file.read_text().strip()
    config=make_pi_config(root,{'base_url':f'http://127.0.0.1:{args.gateway_port}','scope_token':token},policy)
    for name,value in config['env'].items():
        if name not in ('PI_TELEMETRY','PI_OFFLINE','SCOPED_GATEWAY_TOKEN'): Path(value).mkdir(parents=True,exist_ok=True)
    agent=Path(config['env']['PI_CODING_AGENT_DIR'])
    (agent/'settings.json').write_text(json.dumps(config['settings']))
    (agent/'models.json').write_text(json.dumps(config['models']))
    cwd=root/'candidate'; cwd.mkdir(exist_ok=False)
    node=Path('/Users/a1/项目/Myink/myink-pi/runtime/node/node-v24.22.0-darwin-arm64/bin/node')
    cli=Path('/Users/a1/项目/Myink/myink-pi/runtime/pi-project/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js')
    guard=Path(__file__).parent/'pi-wire-guard.mjs'
    config_hash=hashlib.sha256(json.dumps({k:v for k,v in config.items() if k!='env'},sort_keys=True).encode()+guard.read_bytes()).hexdigest()
    command=[str(node),str(cli),*config['args'],'-e',str(guard)]
    env={**config['env'],'PATH':str(node.parent)+':/usr/bin:/bin','LANG':'C.UTF-8'}
    context=AdministratorContext('local-trial-1','c14-readonly-source-analysis','local-trial-1',json.dumps({'source_commit':snapshot.get('commit_sha'),'input_sha256':args.input_sha256,'evidence_domain':'source_only'}))
    session=EngineSession('pi',config_hash,'analysis',root/'sessions'/'analysis.jsonl')
    adapter=PiAdapter(command,cwd=cwd,env=env,config_hash=config_hash)
    receipt=adapter.run_phase(phase='analysis',prompt=prompt,context=context,session=session,
        deadline=datetime.now(timezone.utc)+timedelta(seconds=min(policy.timeout_seconds,90)),tools=[])
    plan=None
    if receipt.status=='done':
        try:
            plan=validate_analysis_plan(json.loads(receipt.evidence['text']),snapshot)
        except ValueError: pass
    output={'status':'done' if receipt.status=='done' and plan is not None else 'pending',
        'evidence':receipt.evidence,'input_sha256':args.input_sha256,'source_commit':snapshot.get('commit_sha'),
        'evidence_domain':'source_only','new_features_require_owner':True,'plan':plan,
        'billing_evidence':'canonical gateway ledger required; Pi usage is not authoritative'}
    (root/'preview-receipt.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':output['status'],'receipt_path':str(root/'preview-receipt.json'),'source_commit':snapshot.get('commit_sha')}))
    return 0 if output['status']=='done' else 1

if __name__=='__main__': raise SystemExit(main())
