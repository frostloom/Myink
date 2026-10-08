"""Run direct/full/no_hybrid on synthetic fixtures in an approved isolated database."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import secrets
import time
import uuid
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import delete, select

from myink.config import settings
from myink.db import new_session, tenant_session
from myink.evaluation.cases import json_text
from myink.evaluation.comparison import BudgetedProvider, ComparisonCase, blind_bundle, direct_context, pending_slots
from myink.evaluation.isolation import require_isolated_database
from myink.evaluation.runner import Budget, provenance, save_manifest
from myink.memory import recall
from myink.models import AgentRun, Alias, Chapter, Character, Event, Fact, Project, ProjectSettings, User
from myink.providers.base import FallbackChain
from myink.providers.prices import lookup_prices
from myink.validation import ledger_l2
from myink.workflow import nodes, prompts
from myink.workflow.chapter_graph import build_chapter_graph


def normalized(value): return json.loads(json.dumps(value,ensure_ascii=False,default=str))


def run(directory, cases, *, live, max_calls, max_cost, selected_slots=None, supplement_source=None):
    if not live: raise ValueError('explicit --live required')
    if settings.embed_enabled: raise ValueError('comparison requires EMBED_ENABLED=0')
    cases = [ComparisonCase.model_validate(c).model_dump() for c in cases]
    identity = require_isolated_database()
    if len({c['id'] for c in cases}) != len(cases): raise ValueError('duplicate comparison case')
    directory.mkdir(parents=True,exist_ok=False)
    config={'model':'deepseek-v4-flash','temperature':.1,
            'prices':{k:v*2 for k,v in lookup_prices('deepseek-v4-flash').items()},
            'max_calls':max_calls,'max_cost_yuan':max_cost,'deadline_seconds':1800}
    budget=Budget(max_calls=max_calls,max_cost_yuan=max_cost,deadline_seconds=1800)
    provider=BudgetedProvider(directory,budget,config)
    source=provenance(Path.cwd())
    source['source_hashes'][Path(__file__).relative_to(Path.cwd()).as_posix()]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for base in ('src/myink/workflow','src/myink/memory','src/myink/providers','src/myink/validation'):
        source['source_hashes'].update({p.as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(base).rglob('*.py')})
    run_info={'started_at':datetime.now(timezone.utc).isoformat(),'identity':identity,'config':config,
              'embedding_enabled':False,'sdk_retries':0,'cases':cases,
              'supplement_source':supplement_source,**source}
    (directory/'run.json').write_text(json_text(run_info),encoding='utf-8')
    with new_session() as db: owner=db.execute(select(User.id).limit(1)).scalar_one()
    outputs=[];cleaned=[]
    # Interleave variants for each task/repetition; never select only successful outputs.
    for repetition in (1,2):
        for case in cases:
            for variant in ('direct','full','no_hybrid'):
                if selected_slots is not None and (case['id'],variant,repetition) not in selected_slots:
                    continue
                provider.active={'case_id':case['id'],'variant':variant,'repetition':repetition}
                label=f'{case["id"]}/{repetition}/{variant}'
                artifact=directory/'outputs'/case['id']/str(repetition)/variant
                artifact.mkdir(parents=True,exist_ok=False)
                started=time.monotonic();before=len(provider.records);pid=None
                row={**provider.active,'execution':'not_run','draft':'','outcome':'unknown'}
                try:
                    if variant=='direct':
                        context=direct_context(case)
                        messages=prompts.write_messages(context,{'goals':[case['instruction']],'characters':case['characters'],
                            'scenes':[],'hard_constraints':case['constraints']},target_words=case['target_words'])
                        response=provider.generate(messages,model_id=config['model'],max_tokens=int(case['target_words']*nodes._WRITE_TOKENS_PER_CHAR*1.25),json_mode=False)
                        row.update(draft=response.content,error=response.error,execution='provider_error' if response.error else 'completed',
                                   outcome='generated' if not response.error else 'failed',finish_reason=response.finish_reason)
                    else:
                        pid=uuid.uuid4()
                        with new_session() as db:
                            db.add(Project(id=pid,user_id=owner,title='P1 compare '+label,genre='现实',target_words=case['target_words'],current_chapter=20));db.commit()
                        with tenant_session(pid) as db:
                            db.add(ProjectSettings(project_id=pid,hard_constraints=case['constraints'],world_rules={},style_profile={}))
                            for name in case['characters']:
                                char=Character(project_id=pid,name=name,realm_cap='普通人',personality='谨慎负责')
                                db.add(char);db.flush()
                                for alias in case.get('aliases',{}).get(name,[]):db.add(Alias(project_id=pid,alias=alias,entity_id=char.id))
                            for text in case['constraints']:db.add(Fact(project_id=pid,content=text,is_hard=True,source_chapter=1,confirm_status='confirmed'))
                            for event in case['history']:db.add(Event(project_id=pid,summary=event['summary'],source_chapter=event['chapter'],participants=[]))
                            db.add(Chapter(project_id=pid,chapter_seq=20,status='confirmed',content=case['previous_tail'],summary=case['previous_tail']))
                        chain=lambda *args,**kwargs:FallbackChain(provider,[config['model']],thinking_enabled=False,prices=config['prices'])
                        states=[]
                        with ExitStack() as stack:
                            stack.enter_context(patch.object(nodes,'make_chain',chain))
                            stack.enter_context(patch.object(ledger_l2,'make_chain',chain))
                            if variant=='no_hybrid':
                                stack.enter_context(patch.object(recall,'_hybrid_recall',lambda *args,**kwargs:{'hybrid_status':'disabled_by_evaluation'}))
                            graph=build_chapter_graph(checkpointer=InMemorySaver())
                            for state in graph.stream({'project_id':str(pid),'chapter_seq':21,'task_id':str(uuid.uuid4()),
                                'user_instruction':case['instruction']},config={'configurable':{'thread_id':label},'recursion_limit':64},stream_mode='values'):
                                states.append(normalized(state))
                                (artifact/'states.json').write_text(json_text(states),encoding='utf-8')
                        final=states[-1]
                        with tenant_session(pid) as db:
                            chapter=db.execute(select(Chapter).where(Chapter.project_id==pid,Chapter.chapter_seq==21)).scalar_one_or_none()
                            database={'content':chapter.content if chapter else None,'status':chapter.status if chapter else None}
                        row.update(draft=final.get('draft') or '',error=final.get('error'),execution='workflow_error' if final.get('error') else 'completed',
                            outcome='awaiting_review' if final.get('needs_review') else 'persisted' if final.get('persisted') else 'incomplete',
                            database=database,database_matches_draft=bool(database['content']) and database['content']==final.get('draft'),
                            system_audit=final.get('audit_verdict'),tool_trace=final.get('tool_trace',[]))
                except Exception as exc:
                    from myink.admin_observability import scrub_text
                    row.update(execution='environment_error',error=scrub_text(str(exc)))
                finally:
                    if pid:
                        with tenant_session(pid) as db:
                            db.execute(delete(AgentRun).where(AgentRun.project_id==pid))
                            db.execute(delete(Project).where(Project.id==pid))
                        cleaned.append(str(pid))
                row.update(wall_ms=round((time.monotonic()-started)*1000),requests=len(provider.records)-before,
                    estimated_cost_yuan=sum(r.get('cost_est',0) for r in provider.records[before:]),quality_status='pending_independent_review')
                if row.get('error') and 'budget' in row['error']:row['execution']='budget_stopped'
                (artifact/'result.json').write_text(json_text(row),encoding='utf-8')
                outputs.append(row);(directory/'results.json').write_text(json_text(outputs),encoding='utf-8')
                print(label+': '+row['execution']+' / '+row['outcome'],flush=True)
    blind,key=blind_bundle(outputs,seed=secrets.randbits(32))
    (directory/'blind-review.json').write_text(json_text(blind),encoding='utf-8')
    (directory/'blind-key.json').write_text(json_text(key),encoding='utf-8')
    summary={'planned_outputs':len(selected_slots) if selected_slots is not None else len(cases)*6,'actual_requests':budget.calls,'cost_reserved_or_estimated_yuan':budget.spent,
             'completed_outputs':sum(r['execution']=='completed' for r in outputs),'quality_status':'pending_independent_review',
             'variants':{v:[{'case_id':r['case_id'],'repetition':r['repetition'],'execution':r['execution'],'outcome':r['outcome'],
                         'requests':r['requests'],'cost':r['estimated_cost_yuan'],'chars':len(r['draft'])} for r in outputs if r['variant']==v] for v in ('direct','full','no_hybrid')}}
    (directory/'summary.json').write_text(json_text(summary),encoding='utf-8')
    parts=['<!doctype html><meta charset="utf-8"><title>P1 生成对照</title><style>body{max-width:1100px;margin:32px auto;padding:0 20px;font:16px/1.7 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}</style><h1>P1 生成对照：原始结果</h1><p>两任务 × 两次 × direct/full/no_hybrid。质量待独立复核；系统自己的 audit pass 不算效果优胜。向量关闭，no_hybrid 仅关闭关键词/向量补充腿；不是删除全部记忆。</p>']
    parts.append('<pre>'+html.escape(json_text(summary))+'</pre>')
    for r in outputs:
        parts.append('<article><h2>'+html.escape(f'{r["case_id"]} · {r["variant"]} · 第{r["repetition"]}次')+'</h2><p>'+html.escape(r['execution']+' / '+r['outcome'])+'</p><details><summary>完整正文</summary><pre>'+html.escape(r['draft'])+'</pre></details></article>')
    (directory/'report.html').write_text('\n'.join(parts),encoding='utf-8')
    save_manifest(directory,{**run_info,'status':'finished','finished_at':datetime.now(timezone.utc).isoformat(),
        'actual_requests':budget.calls,'cost_reserved_or_estimated_yuan':budget.spent,'cleaned_project_ids':cleaned,
        'limitations':['2 synthetic tasks, 2 repetitions; not an external benchmark','direct receives same raw history and constraints, full retrieves production context','nonstreaming evaluation transport, no TTFT conclusion','single chapter: Reflexion is not exercised; vector embeddings disabled','quality remains pending; review blinded bundle before opening key']})
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['plan','run'])
    p.add_argument('--cases',type=Path,default=Path('evals/cases/comparison.json'))
    p.add_argument('--output',type=Path);p.add_argument('--live',action='store_true')
    p.add_argument('--max-calls',type=int,default=60);p.add_argument('--max-cost-yuan',type=float,default=5)
    p.add_argument('--supplement-source',type=Path)
    a=p.parse_args();cases=json.loads(a.cases.read_text(encoding='utf-8'))['cases']
    slots=None; supplement=None
    if a.supplement_source:
        manifest=json.loads((a.supplement_source/'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('status')!='finished':p.error('supplement source must be finished')
        snapshot=a.supplement_source/'run.json';results=a.supplement_source/'results.json'
        cases=json.loads(snapshot.read_text(encoding='utf-8'))['cases']
        slots=pending_slots(json.loads(results.read_text(encoding='utf-8')),cases)
        if not slots:p.error('no budget-stopped slots to supplement')
        supplement={'directory':str(a.supplement_source.resolve()),
                    'run_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                    'results_sha256':hashlib.sha256(results.read_bytes()).hexdigest(),
                    'selected_slots':sorted(slots)}
    if a.command=='plan':print(json_text({'tasks':[c['id'] for c in cases],'variants':['direct','full','no_hybrid'],'repetitions':2,'planned_outputs':len(slots) if slots is not None else len(cases)*6,'supplement_source':supplement,'max_calls':a.max_calls,'max_cost_yuan':a.max_cost_yuan,'requires':'approved isolated PostgreSQL identity; no business data'}))
    else:
        if not a.output:p.error('--output required')
        print(json_text(run(a.output,cases,live=a.live,max_calls=a.max_calls,max_cost=a.max_cost_yuan,selected_slots=slots,supplement_source=supplement)))
