"""Root metadata handoff after a human main release; never a publisher or manager."""
from hashlib import sha256
from pathlib import Path
from datetime import timedelta
import fcntl,os,stat
from .audit import AuditStore,_path,_plain,digest,hash_value,require,strict_json,utc
from .development_inputs import file_hash,ledger_snapshot
from .nightly_gate import BASE,ApprovalGate
from .nightly_driver import _load
from .product_commands import _write,DockerCommands

PROOF_FIELDS=set('identity package_sha256 source_sha256 profile_sha256 cohort_sha256 audit_path export_root observer deployed_at metrics_source_sha256'.split())


def _controller_pin(pin):
    # The launcher has verified this process against its environment pin before
    # importing any Pi module. An independently valid older release is not enough.
    require(hash_value(pin) and os.environ.get('PI_OBSERVER_RUNTIME_SHA256')==pin,'installed nightly controller differs from executing verified runtime')


def _metrics_source(observer,commands,maintenance,now):
    from .nightly_deployment import _run,PRODUCTION
    from .psql_metrics import PsqlMetricsReader
    from .metrics import _PROJECTIONS
    source=observer['source']
    rows=strict_json(_run(commands,['container','inspect',maintenance.container]))
    require(isinstance(rows,list) and len(rows)==1 and rows[0]['Id']==maintenance.container and rows[0]['State']['Running'] is True,'current production PG required')
    expected=dict(docker='/usr/bin/docker',endpoint='unix:///var/run/docker.sock',daemon_id=PRODUCTION,container_id=maintenance.container,image_id=rows[0]['Image'],database='myink',database_user='myink')
    require(all(source.get(k)==v for k,v in expected.items()),'observer source is not the actual production PG')
    reader=PsqlMetricsReader(source)
    cohort='SELECT COALESCE(batch_task_id, id) FROM tasks WHERE created_at >= :start AND created_at < :end'
    for table,predicate in [('tasks',f'id IN ({cohort}) OR batch_task_id IN ({cohort})'),('agent_runs','FALSE')]:
        # Access qualification only: two one-row read-only view queries, never a
        # quality assessment or an extra eligible business sample.
        reader(dict(source=table,sql=f'SELECT {_PROJECTIONS[table]} FROM {table} WHERE {predicate} ORDER BY created_at, id LIMIT :limit OFFSET :offset',params=dict(start=now-timedelta(microseconds=1),end=now,limit=1,offset=0),read_only=True,timeout_ms=3000))
    return digest(source)


def _native(gate,permission,driver,root):
    from .autonomy_profile import load
    from .live_observer import _load as observer_load
    from .nightly_deployment import _cohort,_run,PROBE,PRODUCTION
    from .admin_maintenance import Maintenance
    profile,_,_=load(driver['autonomy_profile']['path'],permission['profile_sha256'])
    from .nightly_source import OMITTED
    template_path=_path(driver['source_template']['path']);_plain(template_path)
    require(file_hash(template_path)==driver['source_template']['sha256'] and template_path==BASE/'config/nightly-source-template.json' and template_path.stat().st_uid==0 and stat.S_IMODE(template_path.stat().st_mode)==0o640,'root fresh source template required')
    template=strict_json(template_path.read_bytes());require(isinstance(template,dict) and set(template)=={'schema','mode','profile','source_scope','validity_seconds'} and template['schema']=='pi-nightly-source-template-v1' and template['mode']==gate.mode and type(template['validity_seconds']) is int and 1<=template['validity_seconds']<=86400 and set(template['source_scope'])=={'files','behavior'} and template['source_scope']['behavior']==profile['source']['behavior'],'bounded standing source template required')
    require(template['profile']=={k:v for k,v in profile.items() if k not in OMITTED} and template['source_scope']['files']==profile['source']['files'],'new profile and standing source template differ')
    identity=permission['new_identity'];image=identity['image_ids']['python']
    require(profile['mode']==gate.mode and _path(profile['manager_state'])==gate.state and _path(profile['host']['ledger_path'])==gate.billing,'original profile accounting required')
    require(profile['source']['reference_commit']==identity['commit_sha'] and profile['checker_image_id']==image,'new source/checker version required')
    _,observer,observer_pin,*_=observer_load(profile['observer']['observer_config_path'])
    require(observer_pin==profile['observer']['observer_config_sha256'] and observer['identity']==identity and observer['minimum_samples']>=20 and observer['lookback_hours']==1,'new observer identity required')
    env_path=BASE/'config/nightly.env';_plain(env_path);require(env_path.stat().st_uid==0 and stat.S_IMODE(env_path.stat().st_mode)==0o640 and env_path.stat().st_size<=65536,'root nightly environment required')
    env={}
    for line in env_path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        key,sep,value=line.partition('=');require(sep and key not in env,'unique nightly environment required');env[key]=value
    require(set(env)=={'PI_NIGHTLY_ENTRYPOINT','PI_NIGHTLY_CONFIG_SHA256','PI_OBSERVER_RUNTIME_SHA256'} and env['PI_NIGHTLY_ENTRYPOINT']==profile['worker_entry_path'] and env['PI_NIGHTLY_CONFIG_SHA256']==permission['driver_sha256'] and env['PI_OBSERVER_RUNTIME_SHA256']==profile['controller_sha256'],'installed nightly runtime/config drift')
    from .deploy.observer_entry import verify_release
    _controller_pin(env['PI_OBSERVER_RUNTIME_SHA256'])
    verify_release(Path(env['PI_NIGHTLY_ENTRYPOINT']).parent,env['PI_OBSERVER_RUNTIME_SHA256'])
    commands=DockerCommands(Path('/usr/bin/docker'),'unix:///var/run/docker.sock',root/'commands')
    require(_run(commands,['info','--format','{{.ID}}']).decode().strip()==PRODUCTION,'original product daemon required')
    rows,reason=_cohort(commands,image,permission['new_package_sha256'],utc(gate.clock()))
    require(rows is not None and all(r['identity']==identity for r in rows),'new healthy physical cohort required')
    image_row=strict_json(_run(commands,['image','inspect',image]))
    require(len(image_row)==1 and image_row[0]['Config']['Labels'].get('org.opencontainers.image.revision')==identity['commit_sha'],'new physical image source label required')
    maintenance=Maintenance(commands);before=maintenance.opened(identity)
    metrics_pin=_metrics_source(observer,commands,maintenance,utc(gate.clock()))
    api=next(r['container_id'] for r in rows if r['role']=='myink-api')
    package=strict_json(_run(commands,['exec','--user','10001:10001',api,'python','-I','-S','-B','-c',PROBE]))
    require(set(package)=={'package','files'} and digest(package['files'])==permission['new_package_sha256'],'physical source package drift')
    source=_path(profile['source']['source_path']);files=profile['source']['files']
    require({p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}==set(files),'bounded selected source snapshot required')
    selected={f:sha256((source/f).read_bytes()).hexdigest() for f in files}
    require(all(package['files'].get(f)==v for f,v in selected.items()) and digest(selected)==profile['source']['source_sha256'],'profile source differs from installed main')
    after,_=_cohort(commands,image,permission['new_package_sha256'],utc(gate.clock()))
    require(after==rows and maintenance.opened(identity)==before and file_hash(driver['autonomy_profile']['path'])==permission['profile_sha256'],'new cohort/profile/maintenance changed during verification')
    require(_path(profile['audit_path'])==BASE/'audit/state/events.sqlite' and _path(profile['export_root'])==BASE/'audit/export','original audit outputs required')
    return dict(identity=identity,package_sha256=permission['new_package_sha256'],source_sha256=digest(selected),profile_sha256=permission['profile_sha256'],cohort_sha256=digest(rows),audit_path=profile['audit_path'],export_root=profile['export_root'],observer=dict(path=profile['observer']['observer_config_path'],sha256=observer_pin),deployed_at=max(r['started_at'] for r in rows),metrics_source_sha256=metrics_pin)


def _result(receipt):
    return dict(status='handed_off',cycle_id=receipt['cycle_id'],operation_id=receipt['operation_id'],comparison_status='interrupted',online_improvement_proven=False,result_sha256=digest(receipt),model_requests=0,known_cost_microyuan=0)


def handoff(gate,permission_path,permission_pin,driver_path,driver_pin,root,*,verify=None):
    require((gate.mode=='ACTUAL' and os.geteuid()==0 and verify is None) or (gate.mode=='SIMULATED' and callable(verify)),'explicit isolated verifier or root native handoff required')
    permission_path=_path(permission_path);raw=gate._trusted(permission_path,permission_pin,'handoff');cycle=raw['cycle_id']
    permission=gate.handoff_permission(cycle,permission_path,permission_pin,current=False)
    driver_path=_path(driver_path);driver=_load(driver_path,driver_pin,(),None if gate.mode=='ACTUAL' else gate.clock)
    require(driver['mode']==gate.mode and all(_path(driver[k])==v for k,v in [('state_path',gate.state),('billing_path',gate.billing),('gate_path',gate.path)]),'original nightly stores required')
    require(driver_pin==permission['driver_sha256'] and driver['inherit_task_id'] is None and isinstance(driver.get('source_template'),dict) and set(driver['source_template'])=={'path','sha256'} and driver['autonomy_profile'] is not None and driver['autonomy_profile']['sha256']==permission['profile_sha256'] and driver['base_image_id']==permission['new_identity']['image_ids']['python'],'explicit new main source profile required')
    template_path=_path(driver['source_template']['path']);require(file_hash(template_path)==driver['source_template']['sha256'],'standing source template drift')
    profile_path=_path(driver['autonomy_profile']['path']);require(file_hash(profile_path)==permission['profile_sha256'],'new profile file drift')
    root=_path(root);require(root==_path(driver['root'])/cycle/('manual-handoff-'+permission['operation_id']) and root.parent.is_dir(),'fixed old-cycle handoff output required')
    if gate.mode=='ACTUAL':require(permission_path.name==permission['operation_id']+'.json' and root.is_relative_to(BASE/'nightly'),'fixed root handoff permission/output required')
    maintenance_path=BASE/'control/maintenance.lock' if gate.mode=='ACTUAL' else _path(driver['lock_path']).with_name('maintenance.lock')
    _plain(maintenance_path)
    with _path(driver['lock_path']).open('rb') as lock,maintenance_path.open('rb') as maintenance:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(maintenance,fcntl.LOCK_EX|fcntl.LOCK_NB)
        require(not any(p!=root for p in root.parent.glob('manual-handoff-*')),'unfinished sibling manual handoff retained; reconcile the original operation')
        if root.exists():
            require((root/'verified.json').exists(),'unfinished manual handoff retained; reconcile')
            _plain(root/'verified.json');receipt=strict_json((root/'verified.json').read_bytes())
            with gate._connection() as db:row=gate._row(db,cycle);require(row['phase']=='completed' and row['result_sha256']==digest(receipt),'unfinished manual handoff retained; reconcile')
            require(receipt['permission_sha256']==permission_pin and receipt['driver_sha256']==driver_pin,'manual handoff receipt drift')
            gate.interrupt_observation(cycle,permission_path,permission_pin,digest(receipt));return _result(receipt)
        gate.handoff_permission(cycle,permission_path,permission_pin)
        require(gate.status()['cycle_id']==cycle and gate.status()['phase'] in ('observing','blocked'),'one current deployed observation required')
        root.mkdir(mode=0o700);(root/'commands').mkdir(mode=0o700)
        accounting=ledger_snapshot(gate.state),ledger_snapshot(gate.billing)
        _write(root/'intent.json',dict(cycle_id=cycle,permission_sha256=permission_pin,driver_sha256=driver_pin,accounting_sha256=digest(accounting)))
        proof=(verify or _native)(gate,permission,driver,root)
        require(isinstance(proof,dict) and set(proof)==PROOF_FIELDS and proof['identity']==permission['new_identity'] and proof['package_sha256']==permission['new_package_sha256'] and proof['profile_sha256']==permission['profile_sha256'] and all(hash_value(proof[k]) for k in ('source_sha256','cohort_sha256','metrics_source_sha256')),'new deployed source proof invalid')
        require((ledger_snapshot(gate.state),ledger_snapshot(gate.billing))==accounting,'original accounting changed during handoff')
        audit,export=_path(proof['audit_path']),_path(proof['export_root'])
        from .local_cycle import _disjoint
        for output in (audit,export):
            for protected in (gate.path,gate.state,gate.billing,permission_path,driver_path,profile_path,root):_disjoint(output,protected)
        _disjoint(audit,export)
        if gate.mode=='ACTUAL':require(audit==BASE/'audit/state/events.sqlite' and audit.is_file() and export==BASE/'audit/export','original actual audit required')
        receipt=dict(schema='pi-nightly-manual-handoff-result-v1',mode=gate.mode,cycle_id=cycle,operation_id=permission['operation_id'],permission_sha256=permission_pin,driver_sha256=driver_pin,source_template_sha256=driver['source_template']['sha256'],comparison_status='interrupted',online_improvement_proven=False,proof=proof,accounting_sha256=digest(accounting),model_requests=0,known_cost_microyuan=0)
        identity=permission['new_identity'];domain='online_business' if gate.mode=='ACTUAL' else 'synthetic'
        event=dict(kind='version',status='insufficient_evidence',run_id=cycle,occurred_at=utc(gate.clock()).isoformat(),summary='Human main release verified; request to end the old observation without a completed comparison. No online improvement is established.',details=dict(reference='nightly.manual_handoff.v1',operation_id=permission['operation_id'],decision='interrupted',reason='manual_main_release',next_action='new_version_bound_source_profile',model_requests=0,known_cost_microyuan=0),version=dict(source_commit=identity['commit_sha'],deployment_id=identity['deployment_id'],generation=identity['generation'],owner=identity['owner'],image_ids=identity['image_ids']),changes=[],evidence=[dict(kind='human_manual_handoff_permission',sha256=permission_pin,verified=True,evidence_domain='offline' if gate.mode=='ACTUAL' else 'synthetic'),dict(kind='new_deployed_source',sha256=digest(proof),verified=True,evidence_domain=domain)],followups=[],mode=gate.mode,evidence_domain=domain)
        store=AuditStore(audit);store.append('manual-handoff:'+permission['operation_id'],event);store.export(export)
        if gate.mode=='ACTUAL':
            from .nightly_binding import _audit_outputs,_ordinary
            for path in _audit_outputs(proof):_ordinary(path,gate.mode)
        require(file_hash(driver_path)==driver_pin and file_hash(profile_path)==permission['profile_sha256'] and (ledger_snapshot(gate.state),ledger_snapshot(gate.billing))==accounting,'handoff inputs/accounting changed before final Gate transaction')
        require((verify or _native)(gate,permission,driver,root)==proof,'new deployed proof changed during audit export')
        require(file_hash(template_path)==driver['source_template']['sha256'],'standing source template changed during handoff')
        _write(root/'verified.json',receipt)
        gate.interrupt_observation(cycle,permission_path,permission_pin,digest(receipt))
        return _result(receipt)


def run(config_path,pin):
    gate=ApprovalGate(BASE/'state/nightly-approval.sqlite',BASE/'state/actual-manager.sqlite',BASE/'state/ledger.sqlite',mode='ACTUAL')
    permission=gate._trusted(config_path,pin,'handoff')
    return handoff(gate,config_path,pin,BASE/'config/nightly-driver.json',permission['driver_sha256'],BASE/'nightly'/permission['cycle_id']/('manual-handoff-'+permission['operation_id']))
