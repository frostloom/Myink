"""Shared request budget and blinded outputs for production-workflow comparisons."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import random
import time
from pydantic import BaseModel, ConfigDict, Field

from myink.admin_observability import scrub_text
from myink.evaluation.cases import json_text
from myink.evaluation.runner import Budget, deepseek_call, digest, save_manifest
from myink.providers.base import ModelProvider, ModelResponse


class ComparisonHistory(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary: str = Field(min_length=1)
    chapter: int = Field(ge=1, le=20)


class ComparisonCase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$')
    group_id: str = ''
    split: str = 'dev'
    label: str = 'proposed'
    characters: list[str] = Field(min_length=1)
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    history: list[ComparisonHistory] = Field(default_factory=list)
    previous_tail: str
    constraints: list[str]
    instruction: str = Field(min_length=1)
    target_words: int = Field(ge=80, le=5000)
    expected: list[str] = Field(default_factory=list)


def pending_slots(rows: list[dict], cases: list[dict]) -> set[tuple[str, str, int]]:
    """Only budget-stopped slots are eligible; successful attempts stay immutable."""
    ids = {case['id'] for case in cases}
    seen = set()
    pending = set()
    for row in rows:
        slot = (row['case_id'], row['variant'], row['repetition'])
        if slot[0] not in ids or slot[1] not in ('direct', 'full', 'no_hybrid') or slot[2] not in (1, 2):
            raise ValueError('invalid comparison slot')
        if slot in seen:
            raise ValueError('duplicate comparison slot')
        seen.add(slot)
        if row['execution'] == 'budget_stopped':
            pending.add(slot)
    return pending


def direct_context(case: dict) -> dict:
    """Direct generation gets all authored material, including the previous tail."""
    return {
        'long_term_facts': [{'content':s,'is_hard':True} for s in case['constraints']],
        'mid_term_events': case['history'],
        'short_context': [
            {'kind':'user_instruction','text':case['instruction']},
            {'kind':'prev_chapter_tail','chapter':20,'tail':case['previous_tail']},
            {'kind':'alias_mapping','text':json_text(case.get('aliases',{}))},
        ],
        'entity_snapshots': [{'name':name,'realm_cap':'普通人','personality':'谨慎负责','state':{}}
                             for name in case['characters']],
    }


def combine_outputs(primary: list[dict], supplement: list[dict]):
    """Select the new attempt only for budget stops; retain every original attempt."""
    def slot(row):return (row['case_id'],row['variant'],row['repetition'])
    selected = {slot(row):row for row in primary}
    if len(selected)!=len(primary):raise ValueError('duplicate primary slot')
    seen=set()
    for row in supplement:
        key=slot(row)
        if key in seen or key not in selected or selected[key]['execution']!='budget_stopped':
            raise ValueError('supplement may only replace a unique budget-stopped slot')
        seen.add(key);selected[key]=row
    return list(selected.values()), [*primary,*supplement]


class BudgetedProvider(ModelProvider):
    """One SDK call per admitted request, including tools and graph correction calls."""
    def __init__(self, directory: Path, budget: Budget, config: dict, *, call=deepseek_call):
        self.directory = directory
        self.budget = budget
        self.config = config
        self.call = call
        self.active = {}
        self.records = []

    def name(self): return 'evaluation-budgeted-deepseek'

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None,
                 json_mode=False, tools=None, disable_thinking=False):
        cap = min(max_tokens or 2000, 6000)
        config = {**self.config, 'max_tokens':cap, 'json_mode':json_mode, 'tools':tools,
                  'temperature':self.config['temperature']}
        try:
            self.budget.reserve(len(json_text(messages).encode())*2+1024,cap,config['prices'])
        except RuntimeError as exc:
            return ModelResponse(content='',model_id=self.config['model'],error=str(exc))
        index = self.budget.calls
        path = self.directory/'requests'/f'{index:04d}';path.mkdir(parents=True,exist_ok=False)
        row = {'request_index':index,**self.active,'prompt_sha256':digest(messages),
               'request_config':{k:v for k,v in config.items() if k!='tools'},
               'started_at':datetime.now(timezone.utc).isoformat(),'execution':'inflight_unknown'}
        (path/'messages.json').write_text(json_text(messages),encoding='utf-8')
        save_manifest(path,row)
        save_manifest(self.directory,{'mode':'generation_compare','status':'running','inflight':row,
            'actual_requests':self.budget.calls,'cost_reserved_or_estimated_yuan':self.budget.spent})
        start = time.monotonic()
        config['timeout_seconds'] = max(.01,min(90.,self.budget.deadline-time.monotonic()))
        try:
            output = self.call(messages,config)
            row.update(output,execution='completed')
            self.budget.settle(output.get('cost_est') if output.get('cost_status')=='estimated' else None)
            response = ModelResponse(content=output['raw_output'],model_id=output['model_id'],
                input_tokens=output.get('input_tokens',0),output_tokens=output.get('output_tokens',0),
                prices=config['prices'],tool_calls=output.get('tool_calls'),finish_reason=output.get('finish_reason'))
        except Exception as exc:
            row.update(execution='timeout' if isinstance(exc,TimeoutError) else 'provider_error',error=scrub_text(str(exc)))
            self.budget.settle(None)
            response = ModelResponse(content='',model_id=self.config['model'],error=row['error'])
        response.duration_ms=round((time.monotonic()-start)*1000)
        row['wall_ms']=response.duration_ms
        (path/'result.json').write_text(json_text(row),encoding='utf-8')
        self.records.append(row)
        save_manifest(self.directory,{'mode':'generation_compare','status':'running','inflight':None,
            'actual_requests':self.budget.calls,'cost_reserved_or_estimated_yuan':self.budget.spent})
        return response


def blind_bundle(outputs:list[dict], *, seed:int):
    order = list(outputs);random.Random(seed).shuffle(order)
    blind=[];key=[]
    for n,row in enumerate(order,1):
        label=f'B{n:03d}'
        blind.append({'blind_id':label,'case_id':row['case_id'],'execution':row['execution'],
                      'draft':row.get('draft',''),'review_status':'pending','reviewer':None,
                      'constraint_violations':None,'goal_completion':None,'readability':None})
        key.append({'blind_id':label,'case_id':row['case_id'],'variant':row['variant'],'repetition':row['repetition']})
    return blind,key
