"""Host rules turn observations into candidates; only fresh checker failures qualify."""
import argparse
import json
import math
from pathlib import Path
import stat
from threading import Event,Timer
import time

from .container_probe import ProbeHost
from .development_inputs import digest,file_hash,path,read_json,tree_hash
from .development_launcher import atomic_write,require
from .local_cycle import _disjoint,_host_roles
from .observations import _read,_name,_sha,collect,MAX_BYTES,_baseline
from .package_baseline import execute as run_baseline
from .task_package import check as check_package,freeze as freeze_package,_stable
from .tool_proof import strict_json

FIELDS={'schema','batch_id','observation_path','observation_sha256','rules','root',
        'baseline_environment','max_baselines','deadline_seconds'}
RULE={'rule_id','source_id','observation_id','package_request_path','package_request_sha256','priority','trigger'}
REQUIRES=['fresh_run_identity','independent_reviews','current_runtime','current_billing_checkpoint']


def load_observations(p,sha):
    p=path(p,private=True);r=strict_json(_read(p,sha).decode('utf-8'))
    require(isinstance(r,dict) and r.get('schema')=='pi-observation-report-v1','observation report required')
    original=path(r['request_path'],private=True);_read(original,r['request_sha256'])
    c,expected=collect(original,existing=True)
    require(p==Path(c['root'])/'observations.json' and digest(r)==digest(expected),'normalized observation binding drift')
    return r


def _trigger(trigger,observation):
    require(isinstance(trigger,dict),'host trigger required')
    if trigger.get('kind')=='failure':
        require(set(trigger)=={'kind'},'strict failure trigger required')
        return observation['state'] in ('failed','error','reproduced_failure'),None
    require(set(trigger)=={'kind','operator','threshold','minimum_samples'} and trigger['kind']=='metric_threshold'
        and trigger['operator'] in ('gt','lt') and type(trigger['threshold']) in (int,float)
        and math.isfinite(trigger['threshold']) and trigger['threshold']>=0
        and type(trigger['minimum_samples']) is int and trigger['minimum_samples']>=5,'bounded metric trigger required')
    if observation['state']!='measured':return False,'metric_not_measured'
    if observation['samples']<trigger['minimum_samples']:return False,'insufficient_samples'
    value=observation['value'];return (value>trigger['threshold'] if trigger['operator']=='gt' else value<trigger['threshold']),None


def _metrics(observed,assessments,candidates):
    mapped={(a['source_id'],a['observation_id']) for a in assessments}
    signals=[x for x in observed['observations'] if x['state'] in ('failed','error','collection_error','reproduced_failure')]
    return dict(observations_total=len(observed['observations']),signals_total=len(signals),
        signals_unmapped=sum((o['source_id'],o['observation_id']) not in mapped for o in signals),
        unknown_observations=sum(x['state'] in ('unknown','confounded','execution_unknown') for x in observed['observations']),
        rules_total=len(assessments),triggered_rules=sum(a['triggered'] for a in assessments),
        rules_rejected=sum(a['decision']=='rejected' for a in assessments),
        rules_not_triggered=sum(a['decision']=='not_triggered' for a in assessments),
        duplicate_rules=sum(a['decision']=='duplicate' for a in assessments),candidate_count=len(candidates),
        baseline_executor_invocations=0,eligible_proposals=0)


def prepare(request_path):
    request=path(request_path,private=True);sha=file_hash(request);_read(request,sha);c=read_json(request)
    require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-proposal-batch-v1'
        and _name(c['batch_id']) and isinstance(c['rules'],list) and 0<len(c['rules'])<=20
        and type(c['max_baselines']) is int and 0<c['max_baselines']<=20
        and type(c['deadline_seconds']) is int and 0<c['deadline_seconds']<=1800,'strict finite proposal batch required')
    root=path(c['root']);require(not root.exists() and root.parent.is_dir()
        and stat.S_IMODE(root.parent.stat().st_mode)==0o700,'new private proposal root required')
    env=c['baseline_environment']
    require(isinstance(env,dict) and set(env)=={'docker','endpoint','daemon_id','checker_image_id','deadline_seconds'}
        and type(env['deadline_seconds']) is int and 0<env['deadline_seconds']<=300,'strict bounded checker environment required')
    host=_host_roles(env);ProbeHost(docker=path(env['docker']),endpoint=env['endpoint'],daemon_id=env['daemon_id'],
        image_id=env['checker_image_id'],operation_id='00000000-0000-4000-8000-000000000001')
    observed=load_observations(c['observation_path'],c['observation_sha256'])
    inputs=[request,path(c['observation_path']),path(observed['request_path']),*host]
    inputs.extend(path(x['path']) for x in observed['sources'])
    for item in observed['sources']:
        if item['kind']=='baseline':
            _,protected=_baseline(item,_read(item['path'],item['sha256']));inputs.extend(protected)
    assessments=[];candidates=[];dedup={};ids=set();outputs=[root]
    for rule in c['rules']:
        require(isinstance(rule,dict) and set(rule)==RULE and _name(rule['rule_id']) and rule['rule_id'] not in ids
            and _name(rule['source_id']) and isinstance(rule['observation_id'],str) and 0<len(rule['observation_id'])<=1100
            and _sha(rule['package_request_sha256']) and type(rule['priority']) is int and 0<=rule['priority']<=9,'strict unique host rule required')
        ids.add(rule['rule_id']);a=dict(rule_id=rule['rule_id'],source_id=rule['source_id'],observation_id=rule['observation_id'],
            triggered=False,decision='rejected',reason='missing_observation');assessments.append(a)
        matches=[x for x in observed['observations'] if x['source_id']==rule['source_id'] and x['observation_id']==rule['observation_id']]
        if not matches:continue
        if len(matches)!=1:a['reason']='ambiguous_observation';continue
        o=matches[0];triggered,reason=_trigger(rule['trigger'],o)
        if not triggered:
            a.update(decision='rejected' if reason else 'not_triggered',reason=reason or 'trigger_not_met');continue
        a['triggered']=True
        try:
            recipe_path=path(rule['package_request_path'],private=True);_read(recipe_path,rule['package_request_sha256']);recipe=read_json(recipe_path)
            inputs.append(recipe_path)
            if isinstance(recipe,dict):
                for key in ('source_path','test_path'):
                    if isinstance(recipe.get(key),str):inputs.append(path(recipe[key]))
                if isinstance(recipe.get('root'),str):
                    outputs.extend([path(recipe['root']),path(recipe['root']).with_name(path(recipe['root']).name+'-baseline')])
            check_package(recipe_path)
            require(recipe['source_sha256']==o['source_sha256'],'observation source identity mismatch')
        except (ValueError,OSError,KeyError,TypeError):
            a['reason']='package_or_source_rejected';continue
        key=digest(dict(source=recipe['source_sha256'],test=recipe['test_sha256'],files=sorted(recipe['files'])))
        if key in dedup:
            candidate=dedup[key];candidate['priority']=max(candidate['priority'],rule['priority'])
            a.update(decision='duplicate',reason='same_frozen_task',proposal_id=candidate['proposal_id']);continue
        candidate=dict(proposal_id='proposal-'+key[:24],task_id=recipe['task_id'],priority=rule['priority'],
            source_sha256=recipe['source_sha256'],test_sha256=recipe['test_sha256'],files=recipe['files'],
            package_request_path=str(recipe_path),package_request_sha256=rule['package_request_sha256'],
            package_root=recipe['root'],baseline_root=str(Path(recipe['root']).with_name(Path(recipe['root']).name+'-baseline')),
            state='requires_baseline',catalog=[],requires=list(REQUIRES))
        candidates.append(candidate);dedup[key]=candidate;a.update(decision='candidate',reason='host_rule_triggered',proposal_id=candidate['proposal_id'])
    unique=list(dict.fromkeys(outputs))
    for i,output in enumerate(unique):
        for value in inputs+unique[:i]:_disjoint(output,value)
    require(file_hash(request)==sha,'proposal request drift')
    result=dict(schema='pi-proposal-report-v1',batch_id=c['batch_id'],request_path=str(request),request_sha256=sha,
        observation_path=c['observation_path'],observation_sha256=c['observation_sha256'],requires_reconciliation=observed['requires_reconciliation'],
        assessments=assessments,proposals=candidates,metrics=_metrics(observed,assessments,candidates),inputs_current=True,automatic_execution=False)
    return c,result


def check(request_path):
    _,r=prepare(request_path)
    return dict(ready=True,mode='read-only',metrics=r['metrics'],requires_reconciliation=r['requires_reconciliation'])


def verify_proposal(proposal):
    recipe=read_json(proposal['package_request_path'])
    _read(proposal['package_request_path'],proposal['package_request_sha256'])
    _stable(proposal['package_request_path'],proposal['package_request_sha256'],recipe)
    p=path(proposal['baseline_request_path'],private=True);_read(p,proposal['baseline_request_sha256'])
    raw=_read(proposal['baseline_outcome_path'],proposal['baseline_outcome_sha256'])
    rows,_=_baseline(dict(request_path=str(p),request_sha256=proposal['baseline_request_sha256'],
        path=proposal['baseline_outcome_path'],source_sha256=proposal['source_sha256']),raw)
    require(rows[0]['state']=='reproduced_failure' and strict_json(raw.decode('utf-8'))['catalog']==proposal['catalog'],
        'completed proposal baseline drift')


def execute(request_path,*,cancel=None):
    cancel=cancel if cancel is not None else Event();require(not cancel.is_set(),'proposal batch cancelled')
    c,r=prepare(request_path);require(not cancel.is_set(),'proposal batch cancelled')
    root=Path(c['root']);root.mkdir(mode=0o700);requests=root/'requests';requests.mkdir(mode=0o700)
    until=time.monotonic()+c['deadline_seconds'];timer=Timer(c['deadline_seconds'],cancel.set);timer.daemon=True;timer.start()
    try:
        for proposal in r['proposals']:
            if r['requires_reconciliation']:proposal['state']='reconciliation_required';continue
            if cancel.is_set() or time.monotonic()>=until:proposal['state']='cancelled';continue
            if r['metrics']['baseline_executor_invocations']>=c['max_baselines']:proposal['state']='deferred';continue
            try:
                require(file_hash(request_path)==r['request_sha256'],'proposal request drift')
                load_observations(c['observation_path'],c['observation_sha256'])
                staged=freeze_package(proposal['package_request_path']);require(not staged['staging_retained'],'package publication incomplete')
                require(not cancel.is_set() and time.monotonic()<until,'batch expired after staging')
                draft=Path(proposal['package_root'])/'task-draft.json';env=dict(c['baseline_environment'])
                env['deadline_seconds']=min(env['deadline_seconds'],max(1,int(until-time.monotonic())))
                request=dict(env,schema='pi-package-baseline-request-v1',baseline_id=proposal['proposal_id'],draft_path=str(draft),
                    draft_sha256=file_hash(draft),root=proposal['baseline_root'])
                p=requests/(proposal['proposal_id']+'.json');atomic_write(p,json.dumps(request,indent=2).encode()+b'\n')
                proposal.update(baseline_request_path=str(p),baseline_request_sha256=file_hash(p))
                r['metrics']['baseline_executor_invocations']+=1
                result=run_baseline(p,cancel=cancel);out=Path(proposal['baseline_root'])/'outcome.json'
                require(path(result['result_path'])==out,'baseline output path drift')
                raw=_read(out,file_hash(out));o=strict_json(raw.decode('utf-8'))
                probe=dict(source_id='proposal',kind='baseline',path=str(out),sha256=file_hash(out),source_sha256=proposal['source_sha256'],
                    request_path=str(p),request_sha256=file_hash(p))
                rows,_=_baseline(probe,raw)
                recipe=read_json(proposal['package_request_path']);_stable(proposal['package_request_path'],proposal['package_request_sha256'],recipe)
                proposal.update(baseline_outcome_path=str(out),baseline_outcome_sha256=file_hash(out),staged_source_path=str(draft.parent/'source'),
                    staged_test_path=str(draft.parent/'test.py'),catalog=o['catalog'] if rows[0]['state']=='reproduced_failure' else [],
                    state='eligible' if rows[0]['state']=='reproduced_failure' else 'baseline_rejected')
            except (ValueError,OSError,KeyError,TypeError) as error:
                proposal.update(state='baseline_rejected',error_class=type(error).__name__,catalog=[])
        try:
            require(file_hash(request_path)==r['request_sha256'],'proposal request drift')
            load_observations(c['observation_path'],c['observation_sha256'])
        except (ValueError,OSError,KeyError,TypeError):
            r['inputs_current']=False
            for p in r['proposals']:
                if p['state']=='eligible':p.update(state='input_changed',catalog=[])
        for proposal in r['proposals']:
            if proposal['state']=='eligible':
                try:verify_proposal(proposal)
                except (ValueError,OSError,KeyError,TypeError):
                    r['inputs_current']=False;proposal.update(state='input_changed',catalog=[])
    finally:timer.cancel()
    r['metrics']['eligible_proposals']=sum(x['state']=='eligible' for x in r['proposals'])
    target=root/'proposals.json';atomic_write(target,json.dumps(r,ensure_ascii=True,indent=2).encode()+b'\n')
    return dict(report_path=str(target),report_sha256=file_hash(target),metrics=r['metrics'],automatic_execution=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True);p.add_argument('--execute',action='store_true');a=p.parse_args()
    try:r=execute(a.request) if a.execute else check(a.request)
    except (ValueError,OSError,KeyError,TypeError) as e:
        print(json.dumps(dict(ready=False,error_class=type(e).__name__)));return 1
    print(json.dumps(r,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
