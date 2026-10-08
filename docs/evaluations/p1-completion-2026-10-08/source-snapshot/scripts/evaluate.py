"""Unified synthetic audit evaluation; paid calls require explicit --live."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import uuid

from myink.evaluation.cases import Case, EvaluationConfig, json_text, load_cases, validate_catalog
from myink.evaluation.runner import deepseek_call, digest, run_cases
from myink.evaluation.scoring import score_case
from myink.evaluation.reporting import write_report

ROOT=Path(__file__).resolve().parents[1]


def quality_exit(summary:dict,*,reviewed:bool=False) -> int:
    if summary['completed']!=summary['planned']:return 1
    if reviewed:
        return 0 if (summary['confirmed']['cases']==summary['planned'] and
                     summary['confirmed']['overall_success']==1) else 1
    return 0 if summary['provisional_automatic']['passed']==summary['completed'] else 1


def load_run(path):
    cases=[Case.model_validate(c) for c in json.loads((path/'cases.json').read_text(encoding='utf-8'))]
    manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    rows=[]
    encoded=(path/'results.jsonl').read_bytes()
    lines=encoded.decode('utf-8',errors='replace' if manifest.get('status')=='running' else 'strict').splitlines()
    for index,line in enumerate(lines):
        if not line:continue
        try:rows.append(json.loads(line))
        except json.JSONDecodeError:
            if (index!=len(lines)-1 or manifest.get('status')!='running' or
                    digest(rows)!=manifest['results_sha256'] or len(rows)>=len(cases)):
                raise ValueError('corrupt result log') from None
            artifact=path/'artifacts'/cases[len(rows)].id/'result.json'
            if artifact.is_file():
                recovered=json.loads(artifact.read_text(encoding='utf-8'))
                if json.dumps(recovered,ensure_ascii=False).startswith(line):rows.append(recovered)
            print('Partial JSONL tail detected; preserved source unchanged, recovered durable artifact if consistent.')
    if digest([c.model_dump() for c in cases])!=manifest['cases_sha256']:
        raise ValueError('run case source hash mismatch')
    if digest(rows)!=manifest['results_sha256']:
        last=path/'artifacts'/cases[len(rows)-1].id/'result.json' if rows and len(rows)<=len(cases) else None
        append_interrupted=(manifest.get('status')=='running' and rows and
            digest(rows[:-1])==manifest['results_sha256'] and last is not None and last.is_file() and
            json.loads(last.read_text(encoding='utf-8'))==rows[-1])
        if not append_interrupted:raise ValueError('run result source hash mismatch')
    if len(rows)>len(cases) or [r['case_id'] for r in rows]!=[c.id for c in cases[:len(rows)]]:
        raise ValueError('run cases/order mismatch')
    if len(rows)<len(cases) and manifest.get('status')!='running':
        raise ValueError('finished run is missing results')
    if any(r.get('case_sha256')!=digest(c.model_dump()) for c,r in zip(cases,rows)):
        raise ValueError('result case hash mismatch')
    return cases,rows


def score_run(path:Path,review_path:Path|None=None):
    cases,rows=load_run(path);reviews={}
    case_hash=digest([c.model_dump() for c in cases])
    manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    if review_path:
        review=json.loads(review_path.read_text(encoding='utf-8'))
        if review.get('results_sha256')!=digest(rows):raise ValueError('review source hash mismatch')
        if review.get('cases_sha256')!=case_hash:raise ValueError('review case source hash mismatch')
        if review.get('actor_kind')!='human':raise ValueError('formal review requires human actor_kind')
        reviews=review.get('cases',{})
        if set(reviews)-{c.id for c in cases}:raise ValueError('review unknown case')
    inflight=manifest.get('inflight') or {}
    scoring_rows=rows+[{'case_id':c.id,'execution':'interrupted_unknown' if c.id==inflight.get('case_id') else 'not_run',
                       'coverage':'implemented','attempted':c.id==inflight.get('case_id'),
                       'note':'Missing result; an inflight request may have incurred usage. No output or success inferred.'}
                      for c in cases[len(rows):]]
    scores=[score_case(c,r,reviews.get(c.id)) for c,r in zip(cases,scoring_rows)]
    scoring_id=datetime.now().astimezone().strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6]
    target=path/'scores'/scoring_id;target.mkdir(parents=True,exist_ok=False)
    (target/'scored.json').write_text(json_text(scores),encoding='utf-8')
    if review_path:(target/'review.json').write_bytes(review_path.read_bytes())
    from myink.evaluation.runner import provenance
    metadata={'results_sha256':digest(rows),'cases_sha256':case_hash,
              'raw_log_sha256':hashlib.sha256((path/'results.jsonl').read_bytes()).hexdigest(),
              'review_sha256':hashlib.sha256(review_path.read_bytes()).hexdigest() if review_path else None,
              'scorer_provenance':provenance(ROOT)}
    (target/'scoring-manifest.json').write_text(json_text(metadata),encoding='utf-8')
    summary=write_report(target,scores)
    template={'results_sha256':digest(rows),'cases_sha256':case_hash,'actor_kind':'human','cases':{
        c.id:{'reviewer':'','label_confirmed':False,'decisions':{fid:{'kind':'disputed'} for fid in s['candidates']}}
        for c,s in zip(cases,scores)}}
    (target/'review-template.json').write_text(json_text(template),encoding='utf-8')
    print(json_text({'report':str(target/'report.html'),'summary':summary}))
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['validate','plan','run','score','report','check-recovery'])
    parser.add_argument('--cases',type=Path,default=ROOT/'evals/cases/audit')
    parser.add_argument('--config',type=Path,default=ROOT/'evals/configs/audit.json')
    parser.add_argument('--split',choices=['all','development','holdout'],default='all')
    parser.add_argument('--suite',choices=['audit'],default='audit')
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--review',type=Path)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--max-calls',type=int)
    parser.add_argument('--max-cost-yuan',type=float)
    parser.add_argument('--deadline-seconds',type=float)
    args=parser.parse_args()
    try:
        if args.command=='check-recovery':
            if not args.source:raise ValueError('--source required')
            from myink.evaluation.recovery import check_recovery
            receipt=check_recovery(args.source);print(json_text(receipt))
            return 0 if receipt['deterministic_pass'] else 1
        if args.command in ('score','report'):
            if not args.run_dir:raise ValueError('--run-dir required')
            summary=score_run(args.run_dir,args.review)
            return 0 if args.command=='report' else quality_exit(summary,reviewed=bool(args.review))
        cases=load_cases(args.cases,ROOT)
        cases=[c for c in cases if args.split=='all' or c.split==args.split]
        if not cases:raise ValueError('empty selected split')
        if args.command=='validate':
            count=validate_catalog(ROOT)
            from myink.evaluation.comparison import ComparisonCase
            from myink.evaluation.retrieval import RetrievalCase
            auxiliary={}
            for name,model in (('retrieval',RetrievalCase),('comparison',ComparisonCase)):
                data=json.loads((ROOT/f'evals/cases/{name}.json').read_text(encoding='utf-8'))
                if data['schema_version']!=1:raise ValueError('unknown auxiliary schema version')
                values=[model.model_validate(c) for c in data['cases']]
                if len({c.id for c in values})!=len(values):raise ValueError('duplicate auxiliary case id')
                groups={}
                for c in values:
                    if c.group_id in groups and groups[c.group_id]!=c.split:raise ValueError('group crosses split')
                    groups[c.group_id]=c.split
                auxiliary[name]=len(values)
            print(f'{len(cases)} audit cases and {count} catalog entries valid; auxiliary: {auxiliary}');return 0
        config=json.loads(args.config.read_text(encoding='utf-8'))
        expected={'model','temperature','max_tokens','max_calls','max_cost_yuan','deadline_seconds'}
        if set(config)!=expected:raise ValueError('unknown/missing config fields')
        for key in ('max_calls','max_cost_yuan','deadline_seconds'):
            value=getattr(args,key)
            if value is not None:config[key]=value
        config=EvaluationConfig.model_validate(config).model_dump()
        from myink.providers.prices import lookup_prices
        prices=lookup_prices(config['model'])
        if prices is None or config['model'] not in ('deepseek-v4-flash','deepseek-v4-pro'):
            raise ValueError('unknown price table or unsupported DeepSeek model')
        config['prices']={k:v*2 for k,v in prices.items()}
        config['price_source']='repository DeepSeek idle table x2 conservative reservation; not supplier invoice'
        from myink.evaluation.runner import Budget
        Budget(max_calls=config['max_calls'],max_cost_yuan=config['max_cost_yuan'],deadline_seconds=config['deadline_seconds'])
        if config['max_tokens']<1 or not 0<=config['temperature']<=2:raise ValueError('invalid model parameters')
        if args.command=='plan':
            print(json_text({'case_ids':[c.id for c in cases],'config':config,'requests':len(cases),
                             'network_calls':0,'database_required':False}));return 0
        target=args.run_dir or ROOT/'.local/evaluation-runs'/(
            datetime.now().astimezone().strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6])
        run_cases(cases,target,config,live=args.live,call=deepseek_call,repo_root=ROOT)
        summary=score_run(target)
        print('Run directory:',target)
        return quality_exit(summary)
    except (ValueError,FileExistsError,KeyError,json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__=='__main__':raise SystemExit(main())
