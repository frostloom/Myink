"""Pure stopped-run evidence projection; never grants, executes or reconciles."""
import json


def _object(value):
    if isinstance(value,dict):return value
    try:result=json.loads(value)
    except (ValueError,TypeError):return {}
    return result if isinstance(result,dict) else {}


def _known(row):
    e=_object(row.get('evidence'))
    return (row.get('status')=='done' and e.get('usage_known') is True
        and type(e.get('charged_microyuan')) is int and e['charged_microyuan']>=0)


def stopped_summary(task_order,run,artifacts,before,after):
    rows=[];cleanup=[];missing=[]
    for name in task_order:
        a=artifacts.get(name,{})
        s=a.get('selection');d=a.get('development')
        if d is not None:state='reported_verified_development' if d.get('verified') is True else 'development_failed_or_unknown'
        elif s is not None:
            if s.get('verified') is not True:state='selection_failed_or_unknown'
            elif isinstance(s.get('proposal'),dict) and s['proposal'].get('task_id') is None:state='not_selected'
            else:state='development_incomplete'
        else:state='incomplete' if a.get('started') else 'unstarted'
        rows.append(dict(task=name,state=state))
        entries=a.get('cleanup',[]);cleanup.extend(entries)
        if a.get('started') and not entries:missing.append(name)
    available=isinstance(before,dict) and isinstance(after,dict)
    result=dict(schema='pi-diverse-stopped-evidence-v1',status='stopped',reason=run.get('reason','audit_failed'),
        scheduled_tasks=len(task_order),tasks=rows,billing_available=available,
        known_cost_microyuan=None,new_model_attempts=None,new_unknown=None,
        new_unresolved_reserved_microyuan=None,historical_unknown=None,
        original_billing_prefix_unchanged=None,cleanup_records=len(cleanup),
        cleanup_removed_records=sum(x.get('removed') is True for x in cleanup),
        started_tasks_without_cleanup_records=missing,current_resource_absence_verified=False,
        cold_recovery_attempted=run.get('cold_recovery_attempted') is True,candidate_adopted=False)
    if isinstance(before,dict):
        result['historical_unknown']=sum(not _known(x) for x in before['operations'] if x['kind']=='model-attempt')
    if available:
        old={x['operation_id']:x for x in before['operations']};current={x['operation_id']:x for x in after['operations']}
        new=[x for k,x in current.items() if k not in old and x['kind']=='model-attempt'];unknown=[x for x in new if not _known(x)]
        reservations=[_object(x.get('payload')).get('reserved_microyuan') for x in unknown]
        result.update(new_model_attempts=len(new),new_unknown=len(unknown),
            known_cost_microyuan=sum(_object(x['evidence'])['charged_microyuan'] for x in new if _known(x)),
            new_unresolved_reserved_microyuan=sum(reservations) if all(type(v) is int and v>=0 for v in reservations) else None,
            original_billing_prefix_unchanged=all(current.get(k)==v for k,v in old.items())
                and after['events'][:len(before['events'])]==before['events'])
    return result
