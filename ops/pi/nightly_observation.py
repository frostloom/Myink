"""Deployment-anchored next-day assessment; no model or business release action."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import os,stat
from .audit import _path,_plain,require,strict_json,digest,utc,SHANGHAI,validate_record,AuditStore
from .development_inputs import file_hash
from .nightly_bundle import verify
from .nightly_gate import BASE
from .product_commands import _write,DockerCommands
from .nightly_deployment import _run,_cohort,PRODUCTION


def _json(path):
    _plain(path);require(path.stat().st_size<=4194304,'bounded assessment receipt required');return strict_json(path.read_bytes())


def _audit(gate,cycle,slot,packet,config,assessment,tested,metrics=None):
    task=gate.status()['task_id'] or cycle;identity=config['identity'];version=dict(candidate_sha256=packet['manifest']['source_sha256'],deployment_id=identity['deployment_id'],source_commit=identity.get('commit_sha'),generation=identity.get('generation'),owner=identity.get('owner'),image_ids=dict(python=packet['manifest']['image_id']))
    domain='offline' if gate.mode=='ACTUAL' else 'synthetic';proof=[dict(kind='frozen_regression_result',sha256=digest(tested),verified=True,evidence_domain=domain)];records=[]
    def event(key,kind,status,summary,details,evidence_domain=domain):
        value=dict(kind=kind,status=status,run_id=task,occurred_at=utc(gate.clock()).isoformat(),summary=summary,details=dict(model_requests=0,known_cost_microyuan=0,operation_id=cycle,**details),version=version,changes=packet['changes'] if kind=='version' else [],evidence=proof,followups=[],mode=gate.mode,evidence_domain=evidence_domain)
        validate_record(value);records.append(dict(record_key=task+':nightly:'+cycle+':'+slot.name+':'+key,event=value))
    failed=assessment['status']=='blocked'
    event('test','test','failed' if failed else 'passed','Next-day frozen regression and cleanup result.',dict(reference='nightly.nextday.regression.v1',test_id='nightly-regression-'+cycle,test_total=tested.get('tests',0),test_failures=tested.get('failures',0),test_errors=tested.get('errors',0),test_skipped=tested.get('skipped',0),next_action='manual_rollback_review' if failed else 'version_bound_metrics'))
    if metrics is not None:
        metric_domain='online_business' if gate.mode=='ACTUAL' else 'synthetic';proof=proof+[dict(kind='version_bound_metrics_result',sha256=digest(metrics),verified=True,evidence_domain=metric_domain)]
        event('metrics','observation','passed' if assessment['status']=='completed' else 'insufficient_evidence','Observed the confirmed version; online improvement remains unproven.',dict(reference='nightly.nextday.metrics.v1',observed_samples=assessment['observed_samples'],minimum_samples=assessment['minimum_samples'],decision=assessment['status'],next_action='next_nightly_round' if assessment['status']=='completed' else 'wait_for_evidence'),metric_domain)
        event('metrics-test','test','passed' if assessment['status']=='completed' else 'insufficient_evidence','Next-day version-bound metrics result; insufficient evidence does not close the comparison.',dict(reference='nightly.nextday.metrics.test.v1',test_id='nightly-metrics-'+cycle,observed_samples=assessment['observed_samples'],minimum_samples=assessment['minimum_samples'],decision=assessment['status']),metric_domain)
    if failed:
        proof=proof+[dict(kind='manual_return_image',sha256=packet['image']['base_image_id'][7:],verified=True,evidence_domain=domain)]
        event('rollback','rollback','blocked','Manual rollback review reserved; no rollback was executed.',dict(reference='nightly.manual_return.v1',decision='advice_only',next_action='manual_rollback_review'))
    event('version','version','no_change','Recorded the confirmed image and change scope; no new release.',dict(reference='nightly.confirmed_version.v1',decision='no_new_release',next_action='manual_rollback_review' if failed else 'none'))
    _write(slot/'audit.json',dict(schema='pi-nightly-nextday-audit-v1',cycle_id=cycle,records=records))
    publish_audit(gate,cycle,slot,config)


def publish_audit(gate,cycle,slot,config):
    """Audit-only idempotent publication; never acknowledges an assessment."""
    slot=_path(slot);audit=_path(config['audit_path']);export=_path(config.get('export_root',audit.parent/'export'))
    if gate.mode=='ACTUAL':require(os.geteuid()==0 and slot.parent==BASE/'nightly'/cycle/'observation' and slot.name.startswith('assessment-') and audit.parent==BASE/'audit/state' and export==BASE/'audit/export','fixed actual next-day audit outputs required')
    else:require(not any(p.is_relative_to(BASE) for p in (slot,audit,export)),'isolated audit outputs required')
    packet=_json(slot/'audit.json');require(packet['schema']=='pi-nightly-nextday-audit-v1' and packet['cycle_id']==cycle and isinstance(packet['records'],list) and 1<=len(packet['records'])<=8,'bounded same-cycle audit packet required')
    for item in packet['records']:
        require(set(item)=={'record_key','event'} and item['event']['mode']==gate.mode and item['event']['details']['operation_id']==cycle,'same-mode audit record required');validate_record(item['event'])
    store=AuditStore(audit)
    for item in packet['records']:store.append(item['record_key'],item['event'])
    manifest=store.export(export)
    if gate.mode=='ACTUAL':
        from .nightly_binding import _audit_outputs,_ordinary
        for path in _audit_outputs(config):_ordinary(path,gate.mode)
    return dict(records=len(packet['records']),snapshot_sha256=manifest['snapshot_sha256'])


def assess(gate,cycle,bundle,observer_config,config_pin,*,clock=None,observe=None,check=None):
    gate.require_action(cycle,'observe_metrics')
    require(gate.mode!='ACTUAL' or os.geteuid()==0 and clock is None and observe is None and check is None,'ACTUAL assessment forbids injected clock/metrics/checker')
    if gate.mode=='SIMULATED':require(callable(observe) and callable(check),'explicit isolated assessment callbacks required')
    with gate._connection() as c:deployment=strict_json(gate._row(c,cycle)['deployment'])['packet']
    now=utc((clock or gate.clock)());deployed=utc(deployment['deployed_at']);due=(deployed.astimezone(SHANGHAI)+timedelta(days=1)).replace(hour=3,minute=0,second=0,microsecond=0)
    if now<due:return dict(status='waiting_due',scheduled_for=due.isoformat(),model_requests=0)
    bundle=_path(bundle);packet=verify(gate,bundle);path=_path(observer_config);_plain(path);require(path.stat().st_size<=65536 and file_hash(path)==config_pin and stat.S_IMODE(path.stat().st_mode)==0o600,'pinned private next-day observer required');config=_json(path)
    require(config['schema']=='pi-live-observer-v1' and config['mode']==gate.mode and config['lookback_hours']==1 and config['minimum_samples']>=20,'bounded postdeployment observer policy required')
    require(config['identity']['deployment_id']==deployment['deployment_id'] and config['identity']['image_ids'].get('python')==packet['manifest']['image_id'],'observer identity does not match verified deployment')
    if gate.mode=='ACTUAL':require(bundle==BASE/'nightly'/cycle/'bundle' and path in (BASE/'config/observer/nightly-observer.json',BASE/'config/nightly-observers'/cycle/'observer.json'),'fixed ACTUAL observation inputs required')
    root=bundle.parent/'observation'
    if not root.exists():root.mkdir(mode=0o700)
    require(all((prior/'receipt.json').exists() for prior in root.glob('assessment-*')),'unfinished observation claim requires inspection; no later-slot replay')
    slot=root/('assessment-'+datetime.fromtimestamp(int(now.timestamp())//900*900,tz=timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    if slot.exists():
        require((slot/'receipt.json').exists(),'unfinished observation claim requires inspection; no same-slot replay');publish_audit(gate,cycle,slot,config);return _json(slot/'receipt.json')
    slot.mkdir(mode=0o700);_write(slot/'intent.json',dict(cycle_id=cycle,comparison_sha256=packet['manifest']['comparison_sha256'],observer_config_sha256=config_pin,model_requests=0))
    commands=None;context=None
    if gate.mode=='ACTUAL':
        logs=slot/'commands';logs.mkdir(mode=0o700);commands=DockerCommands(Path('/usr/bin/docker'),'unix:///var/run/docker.sock',logs)
        require(_run(commands,['info','--format','{{.ID}}']).decode().strip()==PRODUCTION,'original observer daemon drift')
        context,reason=_cohort(commands,packet['manifest']['image_id'],packet['image']['package_sha256'],now)
        require(context is not None,'confirmed deployment is no longer the healthy running cohort')
        require(context[0]['identity']==config['identity'] and context[0]['identity']['deployment_id']==deployment['deployment_id'],'deployed runtime/config identity changed')
    regression=root/'regression'
    if regression.exists():require((regression/'result.json').exists(),'unfinished fixed checker claim must not repeat');tested=_json(regression/'result.json')
    else:
        regression.mkdir(mode=0o700);e=dict(candidate_path=str(bundle/'candidate'),test_path=str(bundle/'regression.py'),test_sha256=packet['comparison']['test_sha256'],test_cases=packet['comparison']['test_cases'],checker=dict(docker='/usr/bin/docker',endpoint='unix:///var/run/docker.sock',daemon_id=PRODUCTION,checker_image_id=packet['image']['image_id']))
        _write(regression/'intent.json',dict(image_id=packet['image']['image_id'],test_sha256=e['test_sha256']))
        def write(name,value):_write(regression/name,value)
        if check is None:
            from .followup import _isolated_check
            check=_isolated_check
        tested=check(e,regression,write);_write(regression/'result.json',tested)
    if tested.get('passed') is not True or tested.get('failures') or tested.get('errors') or tested.get('skipped') or not tested.get('cleanup') or not all(r.get('removed') is True for r in tested['cleanup']):
        rollback=dict(status='blocked',next_action='manual_rollback_review',base_image_id=packet['image']['base_image_id'],candidate_image_id=packet['image']['image_id'],deployed=False,model_requests=0)
        _audit(gate,cycle,slot,packet,config,rollback,tested)
        _write(slot/'receipt.json',rollback);gate.block(cycle,'postdeployment_regression_or_cleanup_failed');return rollback
    require(tested['tests']==len(packet['comparison']['test_cases']),'complete frozen regression inventory required')
    if observe is None:
        from .nightly_binding import collect
        observe=lambda p,pin:collect(p,pin,mode=gate.mode)
    result=observe(path,config_pin);_write(slot/'metrics-result.json',result)
    require(result['schema']=='pi-live-observer-result-v1' and result['mode']==gate.mode and result['config_sha256']==digest(config),'postdeployment metrics receipt identity drift')
    start,end=utc(result['window']['start']),utc(result['window']['end']);require(deployed<=start<end<=now,'metrics window crosses unconfirmed/old deployment')
    if commands is not None:
        after,reason=_cohort(commands,packet['manifest']['image_id'],packet['image']['package_sha256'],utc(gate.clock()));require(after==context,'runtime changed during collection');require(start>=max(utc(r['started_at']) for r in context),'metric window includes a different process cohort')
    enough=result['status']=='passed' and not result['confounders'] and type(result['observed_samples']) is int and result['observed_samples']>=config['minimum_samples']
    assessment=dict(schema='pi-nightly-nextday-assessment-v1',cycle_id=cycle,status='completed' if enough else 'insufficient_evidence',metrics_receipt_sha256=digest(result),regression_sha256=digest(tested),source_sha256=packet['manifest']['source_sha256'],image_id=packet['manifest']['image_id'],observed_samples=result['observed_samples'],minimum_samples=config['minimum_samples'],online_improvement_proven=False,comparison_scope='frozen_regression_and_version_bound_metrics',model_requests=0)
    _audit(gate,cycle,slot,packet,config,assessment,tested,result)
    _write(slot/'receipt.json',assessment)
    if enough:gate.complete(cycle,digest(assessment))
    return assessment
