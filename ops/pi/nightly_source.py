"""Fresh finite research input after a human-deployed comparison, never renewal.

The standing root template omits source, observer and issuance dates. Those are
derived anew from a completed approved version and a fresh read-only window.
The original manager, closed model policy, ledger and unknown holds remain fixed.
"""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import os,stat
from hashlib import sha256
from .audit import _path,_plain,require,strict_json,digest,utc
from .development_inputs import file_hash,tree_hash,ledger_snapshot
from .nightly_gate import BASE
from .nightly_binding import context,_read,_ordinary
from .product_commands import _write,DockerCommands
from .nightly_deployment import _run,_cohort,PRODUCTION


OMITTED={'source','observer','checker_image_id','issued_at','expires_at'}


def _folder(path,mode,*,shared=False):
    if not path.exists():
        path.mkdir(mode=0o750 if shared else 0o700)
        if mode=='ACTUAL' and shared:
            import pwd
            os.chown(path,0,pwd.getpwnam('ubuntu').pw_gid);os.chmod(path,0o750)
        else:_ordinary(path,mode)
    _path(path);require(path.is_dir() and stat.S_IMODE(path.stat().st_mode)==(0o750 if shared and mode=='ACTUAL' else 0o700),'private fixed source directory required')


def _inspect(packet,root):
    root.mkdir(mode=0o700);commands=DockerCommands(Path('/usr/bin/docker'),'unix:///var/run/docker.sock',root)
    require(_run(commands,['info','--format','{{.ID}}']).decode().strip()==PRODUCTION,'original source metrics daemon changed')
    rows,reason=_cohort(commands,packet['manifest']['image_id'],packet['image']['package_sha256'],datetime.now(timezone.utc))
    require(rows is not None,'confirmed product cohort no longer running');return rows


def prepare(gate,cycle,root,template_path,template_pin,*,collect=None,inspect_cohort=None,read_source=None):
    state=gate.status();require(state['phase']=='preparing' and state['cycle_id']==cycle and state['task_id'] is None,'one new unadmitted round required')
    root=_path(root);require(root.is_dir() and stat.S_IMODE(root.stat().st_mode)==0o700,'existing private new round required')
    template_path=_path(template_path);_plain(template_path)
    if gate.mode=='ACTUAL':require(os.geteuid()==0 and collect is None and inspect_cohort is None and read_source is None and root==BASE/'nightly'/cycle and template_path==BASE/'config/nightly-source-template.json' and template_path.stat().st_uid==0 and stat.S_IMODE(template_path.stat().st_mode)==0o640 and template_path.parent.stat().st_uid==0 and stat.S_IMODE(template_path.parent.stat().st_mode)==0o750,'root fixed fresh source issuer required')
    else:require(callable(collect) and callable(inspect_cohort) and callable(read_source) and stat.S_IMODE(template_path.stat().st_mode)==0o600,'explicit isolated source evidence required')
    require(template_path.stat().st_size<=65536 and file_hash(template_path)==template_pin,'source template drift');template=strict_json(template_path.read_bytes())
    from . import autonomy_profile
    require(set(template)=={'schema','mode','profile','source_scope','validity_seconds'} and template['schema']=='pi-nightly-source-template-v1' and template['mode']==gate.mode and isinstance(template['profile'],dict) and set(template['profile'])==autonomy_profile.FIELDS-OMITTED,'source-free standing template required')
    require(type(template['validity_seconds']) is int and 1<=template['validity_seconds']<=86400 and set(template['source_scope'])=={'files','behavior'},'bounded new source lease required')
    from .nightly_source_read import scope,read as read_installed
    files=scope(template['source_scope']['files'],gate.mode)
    with gate._connection() as c:
        row=c.execute("SELECT cycle_id,result_sha256 FROM approval_cycles WHERE phase='completed' AND package IS NOT NULL AND deployment IS NOT NULL ORDER BY rowid DESC LIMIT 1").fetchone()
        require(row is not None,'completed human-deployed predecessor required');previous=row['cycle_id'];result_pin=row['result_sha256']
    bundle=root.parent/previous/'bundle';packet,deployment,cohort,cp=context(gate,previous,bundle,historical=True)
    completed=[]
    assessments=list((bundle.parent/'observation').glob('assessment-*/receipt.json'));require(len(assessments)<=4096,'bounded comparison history required')
    for path in assessments:
        value=_read(path)
        if digest(value)==result_pin and value.get('schema')=='pi-nightly-nextday-assessment-v1' and value.get('cycle_id')==previous and value.get('status')=='completed':completed.append(path)
    require(len(completed)==1,'original completed next-day comparison required')
    binding=_read(bundle.parent/'observer-binding.json');observer=Path(binding['path']);oc=_read(observer)
    require(file_hash(observer)==binding['sha256'] and binding['deployment_receipt_sha256']==deployment['sha256'] and binding['context_sha256']==file_hash(cp) and oc['identity']==cohort['containers'][0]['identity'],'confirmed observer binding drift')
    receipt=root/'source-stage.json';intent=root/'source-intent.json'
    before=ledger_snapshot(gate.billing);profile=dict(template['profile'])
    require(profile['mode']==gate.mode and _path(profile['manager_state'])==gate.state and _path(profile['host']['ledger_path'])==gate.billing and profile['budget_microyuan']==before['limits']['budget_microyuan'],'original finite financial scope required')
    from .diagnosis_launcher import _unknown
    require(set(profile['legacy_unknown_ids'])==_unknown(before),'original unknown fee holds changed')
    if receipt.exists():
        result=_read(receipt);require(result['cycle_id']==cycle and result['previous_cycle_id']==previous and result['template_sha256']==template_pin and result['comparison_sha256']==result_pin and result['context_sha256']==file_hash(cp),'fresh source receipt drift')
        autonomy_profile.load(result['profile']['path'],result['profile']['sha256'],clock=gate.clock if gate.mode=='SIMULATED' else None);return result
    require(not intent.exists(),'unfinished source preparation retained; no replay');_write(intent,dict(cycle_id=cycle,previous_cycle_id=previous,template_sha256=template_pin,comparison_sha256=result_pin))
    inspect_cohort=inspect_cohort or _inspect
    actual=inspect_cohort(packet,root/'source-cohort-before')
    require(isinstance(actual,list) and len(actual)==3 and all(r['identity']==oc['identity'] and r['image_id']==packet['manifest']['image_id'] for r in actual),'confirmed live source identity changed')
    if collect is None:
        from .nightly_binding import collect as observe
        collect=lambda p,pin:observe(p,pin,mode=gate.mode)
    metrics=collect(observer,binding['sha256']);_write(root/'source-metrics.json',metrics)
    require(metrics['schema']=='pi-live-observer-result-v1' and metrics['mode']==gate.mode and metrics['config_sha256']==digest(oc) and metrics['status'] in ('passed','insufficient_evidence'),'completed fresh observation required')
    start,end=utc(metrics['window']['start']),utc(metrics['window']['end']);now=utc(gate.clock())
    require(max(utc(r['started_at']) for r in actual)<=start<end<=now and now-end<=timedelta(minutes=45) and utc(deployment['packet']['deployed_at'])<=start,'fresh deployed source observation required')
    values=read_source(packet,actual,files,root/'source-read') if read_source is not None else read_installed(gate.mode,packet,actual,files,root/'source-read')
    require(isinstance(values,dict) and set(values)==set(files) and all(isinstance(v,str) and len(v.encode())<=24000 for v in values.values()),'bounded selected source text required')
    source_pin=digest({name:sha256(text.encode()).hexdigest() for name,text in values.items()})
    require(inspect_cohort(packet,root/'source-cohort-after')==actual,'source runtime changed during collection')
    parent=BASE/'nightly-source-inputs' if gate.mode=='ACTUAL' else root/'source-inputs';_folder(parent,gate.mode,shared=gate.mode=='ACTUAL')
    inputs=parent/cycle;require(not inputs.exists(),'existing source snapshot retained');_folder(inputs,gate.mode)
    copied=inputs/'source';copied.mkdir(mode=0o700)
    for name,text in values.items():
        path=copied/name;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.write_bytes(text.encode());path.chmod(0o600)
    for path in [copied,*copied.rglob('*')]:path.chmod(0o700 if path.is_dir() else 0o600);_ordinary(path,gate.mode)
    require(tree_hash(copied)==source_pin,'selected deployed source changed during copy')
    pending=inputs/'pending.json';_write(pending,[]);_ordinary(pending,gate.mode)
    from .live_observer import _controller
    profile.update(source=dict(source_path=str(copied),source_sha256=source_pin,files=files,reference_commit=oc['identity']['commit_sha'],pending_path=str(pending),pending_sha256=file_hash(pending),behavior=template['source_scope']['behavior']),observer=dict(observer_config_path=str(observer),observer_config_sha256=binding['sha256'],observer_controller_sha256=_controller()),checker_image_id=packet['manifest']['image_id'],issued_at=now.isoformat(),expires_at=(now+timedelta(seconds=template['validity_seconds'])).isoformat())
    folder=BASE/'config/nightly-source-profiles' if gate.mode=='ACTUAL' else root;_folder(folder,gate.mode,shared=gate.mode=='ACTUAL')
    path=folder/(cycle+'.json');_write(path,profile)
    if gate.mode=='ACTUAL':
        import pwd
        os.chown(path,0,pwd.getpwnam('ubuntu').pw_gid);os.chmod(path,0o640)
    pin=file_hash(path);autonomy_profile.load(path,pin,clock=gate.clock if gate.mode=='SIMULATED' else None)
    require(file_hash(template_path)==template_pin and ledger_snapshot(gate.billing)==before,'source template or original fee ledger changed')
    result=dict(schema='pi-nightly-source-stage-v1',cycle_id=cycle,previous_cycle_id=previous,template_sha256=template_pin,comparison_sha256=result_pin,context_sha256=file_hash(cp),metrics_sha256=digest(metrics),profile=dict(path=str(path),sha256=pin),base_image_id=packet['manifest']['image_id'],known_model_requests=0,fee_sha256=before['sha256'])
    _write(receipt,result);return result
