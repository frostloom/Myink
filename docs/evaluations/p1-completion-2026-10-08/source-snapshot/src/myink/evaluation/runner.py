"""Serial fixed-text evaluation; every actual API request is budgeted once."""
from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone

from myink.admin_observability import scrub_text
from myink.evaluation.cases import Case, json_text
from myink.workflow.prompts import audit_messages


def digest(value) -> str:
    return hashlib.sha256(json_text(value).encode()).hexdigest()


def save_manifest(directory:Path,manifest:dict):
    temporary=directory/'manifest.tmp'
    with temporary.open('w',encoding='utf-8') as file:
        file.write(json_text(manifest));file.flush();os.fsync(file.fileno())
    temporary.replace(directory/'manifest.json')


class Budget:
    def __init__(self, *, max_calls:int, max_cost_yuan:float, deadline_seconds:float):
        if type(max_calls) is not int or max_calls<1 or not all(math.isfinite(x) and x>0 for x in (max_cost_yuan,deadline_seconds)):
            raise ValueError('positive finite budgets required')
        self.max_calls=max_calls;self.max_cost=max_cost_yuan
        self.deadline=time.monotonic()+deadline_seconds
        self.calls=0;self.spent=0.;self.reserved=0.

    def reserve(self,input_tokens:int,output_tokens:int,prices:dict|None):
        if prices is None or not all(k in prices and math.isfinite(prices[k]) and prices[k]>0 for k in ('input','output')):
            raise ValueError('known positive input/output prices required')
        cost=(input_tokens*prices['input']+output_tokens*prices['output'])/1_000_000
        if time.monotonic()>=self.deadline:raise RuntimeError('deadline exhausted')
        if self.calls>=self.max_calls:raise RuntimeError('call budget exhausted')
        if self.spent+cost>self.max_cost:raise RuntimeError('cost reservation exceeds budget')
        self.calls+=1;self.reserved=cost;self.spent+=cost

    def settle(self,cost:float|None):
        # Unknown usage keeps the entire reservation; no retry or optimistic refund.
        if cost is not None:
            if not math.isfinite(cost) or cost<0:raise ValueError('invalid cost')
            self.spent+=cost-self.reserved
        self.reserved=0.


def provenance(root:Path):
    def git(*args):
        p=subprocess.run(['git',*args],cwd=root,capture_output=True,check=False)
        return p.stdout if p.returncode==0 else b'unknown'
    paths=['src/myink/workflow/prompts.py','src/myink/schemas/contract.py','src/myink/evaluation']
    return {'commit':git('rev-parse','HEAD').decode().strip(),
            'dirty':bool(git('status','--porcelain').strip()),
            'tracked_diff_sha256':hashlib.sha256(git('diff','HEAD','--',*paths)).hexdigest(),
            'source_hashes':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                             for item in paths for p in ((root/item).rglob('*.py') if (root/item).is_dir() else [root/item])},
            'dependencies':{name:version(name) for name in ('pydantic','openai')}}


def run_cases(cases:list[Case],directory:Path,config:dict,*,live:bool,call,repo_root:Path|None=None):
    if not live:raise ValueError('explicit --live required')
    budget=Budget(max_calls=config['max_calls'],max_cost_yuan=config['max_cost_yuan'],
                  deadline_seconds=config['deadline_seconds'])
    prices=config['prices']
    if prices is None:raise ValueError('prices unknown')
    directory.mkdir(parents=True,exist_ok=False)
    started=datetime.now(timezone.utc).isoformat()
    manifest={'schema_version':1,'started_at':started,'config':config,'mode':'audit','status':'running',
              'cases_sha256':digest([c.model_dump() for c in cases]),'case_ids':[c.id for c in cases],
              'limits_note':'no SDK retries; input reservation uses conservative UTF-8 byte estimate; cost is local estimate, not invoice',
              'results_sha256':digest([]),**(provenance(repo_root) if repo_root else {})}
    save_manifest(directory,manifest)
    (directory/'cases.json').write_text(json_text([c.model_dump() for c in cases]),encoding='utf-8')
    (directory/'results.jsonl').touch(exist_ok=False)
    rows=[]
    for case in cases:
        messages=audit_messages(case.input.draft,case.input.plan,case.input.context,case.input.chapter_seq)
        row={'case_id':case.id,'case_sha256':digest(case.model_dump()),'execution':'not_run',
             'coverage':'implemented','attempted':False,'prompt_sha256':digest(messages),
             'input_tokens':0,'output_tokens':0,'cost_est':0,'cost_status':'unknown'}
        start=time.monotonic()
        try:
            # Byte-based upper estimate with margin, not a claim of exact tokenization.
            token_reserve=len(json_text(messages).encode('utf-8'))*2+1024
            budget.reserve(token_reserve,config['max_tokens'],prices)
        except RuntimeError as exc:
            row.update(execution='budget_stopped',error=str(exc))
        else:
            row['attempted']=True
            artifact=directory/'artifacts'/case.id;artifact.mkdir(parents=True)
            (artifact/'messages.json').write_text(json_text(messages),encoding='utf-8')
            manifest.update(inflight={'case_id':case.id,'request_intent_at':datetime.now(timezone.utc).isoformat()},
                            actual_requests=budget.calls,cost_reserved_or_estimated_yuan=budget.spent)
            save_manifest(directory,manifest)
            request_config={**config,'timeout_seconds':max(.01,min(60.,budget.deadline-time.monotonic()))}
            try:
                output=call(messages,request_config)
                row.update(output,execution='completed')
                budget.settle(row.get('cost_est') if row.get('cost_status')=='estimated' else None)
            except Exception as exc:
                timeout=isinstance(exc,TimeoutError) or 'timeout' in type(exc).__name__.lower()
                row.update(execution='timeout' if timeout else 'provider_error',error=scrub_text(str(exc)))
                budget.settle(None)
        row['wall_ms']=round((time.monotonic()-start)*1000)
        artifact=directory/'artifacts'/case.id;artifact.mkdir(parents=True,exist_ok=True)
        (artifact/'messages.json').write_text(json_text(messages),encoding='utf-8')
        (artifact/'result.json').write_text(json_text(row),encoding='utf-8')
        with (directory/'results.jsonl').open('a',encoding='utf-8') as file:
            file.write(json.dumps(row,ensure_ascii=False)+'\n');file.flush();os.fsync(file.fileno())
        rows.append(row)
        manifest.update(inflight=None,actual_requests=budget.calls,cost_reserved_or_estimated_yuan=budget.spent,
                        results_sha256=digest(rows))
        save_manifest(directory,manifest)
        print(f'{case.id}: {row["execution"]}',flush=True)
    manifest.update(status='finished',finished_at=datetime.now(timezone.utc).isoformat(),actual_requests=budget.calls,
                    cost_reserved_or_estimated_yuan=budget.spent,results_sha256=digest(rows))
    save_manifest(directory,manifest)
    return rows


def deepseek_call(messages:list[dict],config:dict) -> dict:
    """Use production request shape without its hidden automatic retry loops."""
    import os
    from openai import OpenAI
    from myink.providers.deepseek import DeepSeekProvider, extract_openai_text_part, isolate_response_body, _message_reasoning
    key=os.getenv('DEEPSEEK_API_KEY','').strip()
    if not key:raise ValueError('DEEPSEEK_API_KEY is not configured')
    kwargs=DeepSeekProvider._request_kwargs(messages,model_id=config['model'],max_tokens=config['max_tokens'],
        temperature=config['temperature'],json_mode=config.get('json_mode',True),tools=config.get('tools'),disable_thinking=True)
    try:
        with OpenAI(api_key=key,base_url='https://api.deepseek.com',max_retries=0,timeout=config['timeout_seconds']) as client:
            response=client.chat.completions.create(**kwargs)
        choice=response.choices[0];usage=response.usage
        content=extract_openai_text_part(choice.message.content)
        raw=isolate_response_body(content,
                                  reasoning=_message_reasoning(choice.message),json_mode=config.get('json_mode',True))
        input_tokens=usage.prompt_tokens if usage else 0;output_tokens=usage.completion_tokens if usage else 0
        prices=config['prices']
        cost=(input_tokens*prices['input']+output_tokens*prices['output'])/1_000_000
        tool_calls=[]
        def safe_argument(value):
            if isinstance(value,str):return scrub_text(value).replace(key,'[REDACTED]')
            if isinstance(value,list):return [safe_argument(v) for v in value]
            if isinstance(value,dict):return {safe_argument(k):safe_argument(v) for k,v in value.items()}
            return value
        for tc in getattr(choice.message,'tool_calls',None) or []:
            try:arguments=json.loads(tc.function.arguments)
            except (ValueError,TypeError):arguments={'_invalid_arguments':scrub_text(str(tc.function.arguments)).replace(key,'[REDACTED]')}
            tool_calls.append({'id':safe_argument(tc.id),'name':safe_argument(tc.function.name),'arguments':safe_argument(arguments)})
        return {'raw_output':scrub_text(raw).replace(key,'[REDACTED]'),'model_id':response.model,
                'tool_calls':tool_calls or None,
                'raw_response_content':scrub_text(content).replace(key,'[REDACTED]'),
                'response_projection':{'source':'message.content' if content.strip() else 'reasoning_fallback',
                    'scrubbed':scrub_text(content).replace(key,'[REDACTED]')!=content,'normalized':raw!=content},
                'finish_reason':choice.finish_reason,'input_tokens':input_tokens,'output_tokens':output_tokens,
                'cost_est':cost,'cost_status':'estimated' if usage else 'unknown'}
    except Exception as exc:
        # SDK exceptions can echo request headers. Only expose scrubbed text.
        safe=scrub_text(str(exc)).replace(key,'[REDACTED]')
        if 'timeout' in type(exc).__name__.lower():raise TimeoutError(safe) from None
        raise RuntimeError(safe) from None
