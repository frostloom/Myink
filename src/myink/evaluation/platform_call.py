"""One explicit Anthropic attempt through the canonical Pi loopback gateway.

The gateway alone accounts generation/judgment/retries. No website allowance or
legacy DeepSeek client is consulted. Raw usage is retained; an independently
reconciled canonical receipt is required before any estimated cost is accepted.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',', ':'),
        ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def public_config(config):
    return {k:v for k,v in config.items() if not k.startswith('_')}


def platform_config(config,*,environ=None):
    env=os.environ if environ is None else environ
    selected={key:env.get('PLATFORM_MODEL_'+name,'').strip() for key,name in
        (('_api_key','API_KEY'),('base_url','BASE_URL'),('model','NAME'),('protocol','PROTOCOL'))}
    if any(not v for v in selected.values()):raise ValueError('four PLATFORM_MODEL_* fields required')
    if any(key in config and config[key]!=selected[key] for key in ('model','protocol','base_url')):
        raise ValueError('selected platform configuration mismatch')
    result={**config,**selected,'transport':'platform','budget_scope_id':'local-trial-1'}
    _validate(result)
    return result


def _validate(config):
    parsed=urlsplit(config.get('base_url',''))
    if (parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port
            or parsed.path not in ('','/') or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('trusted fixed loopback gateway required')
    if config.get('protocol')!='anthropic' or config.get('budget_scope_id')!='local-trial-1':
        raise ValueError('explicit Anthropic canonical gateway scope required')
    key=config.get('_api_key')
    if not isinstance(key,str) or not key or len(key)>4096 or any(not 33<=ord(c)<=126 for c in key):
        raise ValueError('scoped gateway token required')
    if not isinstance(config.get('model'),str) or not config['model'].strip():raise ValueError('model required')
    pricing=config.get('pricing_id')
    if not isinstance(pricing,str) or len(pricing)!=64 or any(c not in '0123456789abcdef' for c in pricing):
        raise ValueError('trusted pricing_id required')
    prices=config.get('prices')
    if not isinstance(prices,dict) or set(prices)!= {'input','output','cache_read','cache_write'}:
        raise ValueError('explicit trusted four-dimensional prices required')
    for name,value in prices.items():
        if value is None and name in ('cache_read','cache_write'):continue
        try:
            rate=Decimal(value) if isinstance(value,str) else Decimal('NaN')
            if not rate.is_finite() or rate<0:raise ValueError('invalid price')
        except (ValueError,ArithmeticError):raise ValueError('trusted Decimal-string prices required') from None
    if type(config.get('max_tokens')) is not int or not 0<config['max_tokens']<=8192:
        raise ValueError('bounded max_tokens required')
    if (type(config.get('temperature')) not in (int,float) or not 0<=config['temperature']<=1
            or type(config.get('timeout_seconds')) not in (int,float) or not 0<config['timeout_seconds']<=120):
        raise ValueError('bounded temperature/timeout required')


def _payload(messages,config):
    # Reuse production converters only on shapes they preserve exactly.
    from myink.providers.anthropic import _convert_messages, _convert_tools
    if not isinstance(messages,list) or not messages:raise ValueError('messages required')
    if any(not isinstance(m,dict) or m.get('role') not in ('system','user','assistant','tool')
           or not isinstance(m.get('content',''),str) for m in messages):
        raise ValueError('supported text message shape required; no lossy block conversion')
    system,converted=_convert_messages(messages,config.get('json_mode',False))
    for original,item in zip([m for m in messages if m['role']!='system'],converted):
        if original['role']=='tool':item['content'][0]['is_error']=original.get('is_error',False)
    payload={'model':config['model'],'max_tokens':config['max_tokens'],'temperature':config['temperature'],
             'messages':converted,'stream':False,'thinking':{'type':'disabled'}}
    if system:payload['system']=system
    tools=config.get('tools')
    if tools:
        # Native Anthropic declarations already use input_schema; do not discard it.
        payload['tools']=deepcopy(tools) if all('input_schema' in t for t in tools) else _convert_tools(tools)
    return payload


def _scrub(value,key):
    from myink.admin_observability import scrub_text
    if isinstance(value,str):return scrub_text(value).replace(key,'[REDACTED]')
    if isinstance(value,list):return [_scrub(v,key) for v in value]
    if isinstance(value,dict):return {_scrub(k,key):_scrub(v,key) for k,v in value.items()}
    return value


def platform_call(messages,config):
    _validate(config);payload=_payload(messages,config);key=config['_api_key']
    row={'protocol':'anthropic','requested_model':config['model'],'model_id':None,
         'raw_output':'','raw_response':None,'raw_response_content':'','tool_calls':None,
         'thinking_blocks':[],'finish_reason':None,'usage':None,'input_tokens':None,'output_tokens':None,
         'cost_est':None,'cost_status':'unknown','accounting_status':'unreconciled',
         'pricing_id':config['pricing_id'],'budget_scope_id':'local-trial-1','gateway_http_attempts':1,'actual_http_attempts':None,
         'request_sha256':digest(payload),'executed_messages_sha256':digest(messages),
         'executed_config_sha256':digest(public_config(config)),'execution':'provider_error'}
    try:
        with httpx.Client(transport=httpx.HTTPTransport(retries=0),trust_env=False,follow_redirects=False,
                          timeout=config['timeout_seconds']) as client:
            response=client.post(config['base_url'].rstrip('/')+'/v1/messages',json=payload,
                headers={'x-api-key':key,'X-Pi-Scope':'local-trial-1','anthropic-version':'2023-06-01','content-type':'application/json'})
        row['http_status']=response.status_code
        try:data=response.json()
        except ValueError:data={'unparsed_body':response.text}
        row['raw_response']=_scrub(data,key)
        if not isinstance(data,dict):return row
        row['provider_request_id']=data.get('id') or response.headers.get('request-id') or response.headers.get('x-request-id')
        row['usage']=_scrub(data.get('usage'),key)
        if isinstance(data.get('model'),str) and data['model']:row['model_id']=data['model']
        blocks=data.get('content') if isinstance(data.get('content'),list) else []
        raw=''.join(b.get('text','') for b in blocks if isinstance(b,dict) and b.get('type')=='text' and isinstance(b.get('text'),str))
        from myink.providers.think_tag_stripper import isolate_response_body
        projected=isolate_response_body(raw,json_mode=config.get('json_mode',False))
        row.update(raw_output=_scrub(projected,key),raw_response_content=_scrub(raw,key),
          response_projection={'source':'content.text','normalized':projected!=raw,'scrubbed':_scrub(raw,key)!=raw},
          thinking_blocks=_scrub([b for b in blocks if isinstance(b,dict) and b.get('type') in ('thinking','redacted_thinking')],key),
          tool_calls=_scrub([{'id':b.get('id'),'name':b.get('name'),'arguments':b.get('input')} for b in blocks
                            if isinstance(b,dict) and b.get('type')=='tool_use'],key) or None,
          finish_reason=data.get('stop_reason'))
        usage=row['usage'];known=False
        if isinstance(usage,dict):
            for name in ('input_tokens','output_tokens'):
                if type(usage.get(name)) is int and usage[name]>=0:row[name]=usage[name]
            from ops.pi.model_gateway import _usage_updates
            try:
                counters=_usage_updates(usage,{},('input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens'))
                known=all(type(counters.get(k)) is int for k in ('input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens'))
                known=known and not (counters['cache_read_input_tokens'] and config['prices']['cache_read'] is None)
                known=known and not (counters['cache_creation_input_tokens'] and config['prices']['cache_write'] is None)
            except ValueError:pass
        if response.status_code==429:row['execution']='budget_stopped'
        elif response.status_code==200 and row['model_id'] and (row['raw_output'] or row['tool_calls']):row['execution']='completed'
        resolver=config.get('_accounting_resolver')
        if known and row['execution']=='completed' and callable(resolver):
            identity={'scope_id':'local-trial-1','request_sha256':row['request_sha256'],
                      'provider_request_id':row['provider_request_id'],'model_id':row['model_id'],
                      'pricing_id':row['pricing_id'],'usage_sha256':digest(usage)}
            receipt=resolver(deepcopy(identity))
            if (isinstance(receipt,dict) and all(receipt.get(k)==v for k,v in identity.items())
                    and receipt.get('ledger_event_verified') is True and receipt.get('status')=='done'
                    and receipt.get('usage_known') is True and isinstance(receipt.get('attempt_id'),str)
                    and bool(receipt['attempt_id']) and type(receipt.get('charged_microyuan')) is int
                    and receipt['charged_microyuan']>=0):
                row.update(cost_est=receipt['charged_microyuan']/1_000_000,cost_status='estimated',
                           accounting_status='reconciled',actual_http_attempts=1,canonical_receipt=deepcopy(receipt))
    except Exception as exc:
        row['execution']='timeout' if isinstance(exc,(TimeoutError,httpx.TimeoutException)) else 'provider_error'
        row['error_kind']=type(exc).__name__
    return row


def run_platform_cases(cases,directory,config,*,live,call=platform_call,repo_root=None):
    """Legacy audit artifacts, but NO independent Budget on the platform route."""
    if not live:raise ValueError('explicit --live required')
    _validate(config)
    from myink.evaluation.cases import json_text
    from myink.evaluation.runner import save_manifest,provenance,digest as artifact_digest
    from myink.workflow.prompts import audit_messages
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    snapshot=[c.model_dump() for c in cases];rows=[]
    manifest={'schema_version':1,'status':'running','config':public_config(config),'mode':'audit',
              'accounting_source':'canonical local-trial-1 gateway only','cases_sha256':artifact_digest(snapshot),
              'results_sha256':artifact_digest([]),**(provenance(repo_root) if repo_root else {})}
    save_manifest(directory,manifest);(directory/'cases.json').write_text(json_text(snapshot),encoding='utf-8')
    (directory/'results.jsonl').touch(exist_ok=False)
    for case in cases:
        messages=audit_messages(case.input.draft,case.input.plan,case.input.context,case.input.chapter_seq)
        artifact=directory/'artifacts'/case.id;artifact.mkdir(parents=True)
        (artifact/'messages.json').write_text(json_text(messages),encoding='utf-8')
        row={'case_id':case.id,'case_sha256':artifact_digest(case.model_dump()),'attempted':True,
             'coverage':'implemented','prompt_sha256':digest(messages),'execution':'inflight_unknown',
             'cost_est':None,'cost_status':'unknown','actual_http_attempts':None}
        save_manifest(artifact,row)
        manifest['inflight']={'case_id':case.id,'messages_sha256':digest(messages)};save_manifest(directory,manifest)
        try:row.update(call(messages,config))
        except Exception as exc:
            row.update(execution='timeout' if isinstance(exc,TimeoutError) else 'provider_error',error_kind=type(exc).__name__)
        (artifact/'result.json').write_text(json_text(row),encoding='utf-8')
        with (directory/'results.jsonl').open('a',encoding='utf-8') as handle:handle.write(json.dumps(row,ensure_ascii=False)+'\n')
        rows.append(row);manifest.update(results_sha256=artifact_digest(rows),inflight=None);save_manifest(directory,manifest)
    attempts=[r.get('actual_http_attempts') for r in rows]
    manifest.update(status='finished',actual_requests=sum(attempts) if all(type(n) is int for n in attempts) else None,
                    cost_reserved_or_estimated_yuan=None)
    save_manifest(directory,manifest)
    return rows
