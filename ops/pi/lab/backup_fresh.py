"""One finite isolated fresh-source trial; original source and services are immutable."""
import hashlib,json,os,shutil,subprocess,sys,time
from datetime import datetime,timezone,timedelta
from pathlib import Path
from ops.pi.lab import backup_lab as lab
from ops.pi.lab.verify import _docker,_configuration,verify_runtime
from ops.pi.backup import digest,durable_file,encoded,private_path,release_allowed,mark_released,record_recovery_references
from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger


def directory(operation):return lab.BASE/('b11-fresh-'+operation)


def fixed_paths(operation):
    root=directory(operation)
    return {'context':str(root/'context.json'),'source':str(root/'source.json'),'materials':str(root/'materials'),
        'ledger':str(lab.PRIVATE/'state'/('b11-fresh-'+operation+'.sqlite')),
        'collections':str(lab.PRIVATE/'backups'/('fresh-'+operation)/'collections')}


def context(operation):
    path=private_path(lab.BASE,'b11-fresh-'+operation+'/context.json')
    if path.stat().st_uid!=0 or path.stat().st_mode&0o077:raise ValueError('untrusted fresh context')
    value=json.loads(path.read_text())
    if value['operation_id']!=operation or value['paths']!=fixed_paths(operation):raise ValueError('foreign fresh context')
    ledger=Ledger(Path(value['paths']['ledger']))
    with ledger.transaction() as db:
        events=[json.loads(v[0]) for v in db.execute("SELECT payload FROM events WHERE kind='fresh_context_created'")]
    if len(events)!=1 or events[0]['sha256']!=digest(path):raise ValueError('fresh context creation authority missing')
    return value


def source_runtime(runtime):
    if not os.environ.get('B11_FRESH_CONTEXT'):return runtime
    value=context(lab.current_operation())
    return {**runtime,'source_pg':value['services']['pg']['name'],
        'test_containers':[value['services']['pg']['name'],value['services']['redis']['name'],runtime['project']+'-rabbit']}


def verify_context(runtime,original,operation):
    value=context(operation)
    if os.environ['B11_FRESH_CONTEXT']!=value['paths']['context'] or value['lab_uuid']!=runtime['lab_uuid']:raise ValueError('fresh context transport drift')
    hashes={name:digest(lab.BASE/'trusted-source'/name) for name in value['source_hashes']}
    if hashes!=value['source_hashes']:raise ValueError('fresh context tested source drift')
    network=_docker('network','inspect',runtime['project']+'-fixtures')[0]
    if network['Id']!=value['network_id'] or network['Labels']!={'myink.pi.lab':runtime['lab_uuid']}:raise ValueError('fresh network ownership drift')
    for role,service in value['services'].items():
        info=_docker('inspect',service['id'])[0];volume=_docker('volume','inspect',service['volume']['Name'])[0]
        if _configuration(info)!=service['configuration'] or volume!=service['volume'] or not info['State']['Running']:raise ValueError('fresh service identity/config/volume drift')
        if info['Config']['Labels']!=value['labels'] or info['HostConfig']['CgroupParent']!='myinkpi-heavy.slice':raise ValueError('fresh service owner drift')
        expected_memory={'pg':256,'redis':96}[role]*1024**2
        if info['HostConfig']['Memory']!=expected_memory or info['HostConfig']['MemorySwap']!=expected_memory or info['HostConfig']['NanoCpus']!={'pg':500000000,'redis':250000000}[role]:raise ValueError('fresh service limits drift')
        if '/myinkpi.slice/myinkpi-heavy.slice/' not in Path('/proc/'+str(info['State']['Pid'])+'/cgroup').read_text():raise ValueError('fresh fixture outside heavy')
        if set(info['NetworkSettings']['Networks'])!={runtime['project']+'-fixtures'} or info['NetworkSettings']['Networks'][runtime['project']+'-fixtures']['NetworkID']!=value['network_id']:raise ValueError('fresh service network drift')
        if len(info['Mounts'])!=1 or info['Mounts'][0]['Name']!=volume['Name'] or volume['Labels']!=value['labels']:raise ValueError('fresh mount ownership drift')
        port=info['NetworkSettings']['Ports'][{'pg':'5432/tcp','redis':'6379/tcp'}[role]]
        if port!=[{'HostIp':'127.0.0.1','HostPort':str(service['port'])}]:raise ValueError('fresh endpoint drift')
    import psycopg
    with psycopg.connect(value['admin_dsn']) as db:
        if db.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]!=value['system_identifier']:raise ValueError('fresh PG system drift')
    return {**original,'DATABASE_URL':value['admin_dsn'].replace('postgresql:','postgresql+psycopg:'),
        'ADMIN_DATABASE_URL':value['admin_dsn'].replace('postgresql:','postgresql+psycopg:'),'REDIS_URL':value['redis_url']}


def command(root,*arguments,input=None):
    folder=root/'commands';folder.mkdir(exist_ok=True,mode=0o700)
    token=str(len(list(folder.glob('*.intent.json'))))
    durable_file(folder/(token+'.intent.json'),encoded({'operation_id':lab.current_operation(),'arguments':arguments}))
    result=subprocess.run(arguments,input=input,capture_output=True,timeout=30)
    for stream in ('stdout','stderr'):durable_file(folder/(token+'.'+stream),getattr(result,stream))
    durable_file(folder/(token+'.receipt.json'),encoded({'returncode':result.returncode,'stdout_sha256':digest(folder/(token+'.stdout')),'stderr_sha256':digest(folder/(token+'.stderr'))}))
    result.check_returncode();return result


def provision():
    runtime,original=lab.verify_test_environment();operation=lab.current_operation();root=directory(operation)
    if root.exists() or 'myink.config' in sys.modules:raise ValueError('fresh context exists or business imported')
    peak=1024**3;reserve=5*1024**3
    capacity={'planned_peak_bytes':peak,'reserve_bytes':reserve,'e_free_bytes':shutil.disk_usage('/mnt/e').free,'guest_free_bytes':shutil.disk_usage('/').free}
    if min(capacity['e_free_bytes'],capacity['guest_free_bytes'])<peak+reserve:raise ValueError('fresh context disk gate')
    root.mkdir(mode=0o700);paths=fixed_paths(operation)
    lab.SOURCE=Path(paths['source']);lab.MATERIALS=Path(paths['materials']);lab.LEDGER_PATH=Path(paths['ledger']);lab.COLLECTIONS=Path(paths['collections'])
    lab.MATERIALS.mkdir(mode=0o700);private_path(lab.PRIVATE/'state',lab.LEDGER_PATH.name)
    durable_file(root/'claim.json',encoded({'operation_id':operation,'lab_uuid':runtime['lab_uuid'],'paths':paths,'source_hashes':{name:digest(lab.BASE/'trusted-source'/name) for name in ('ops/pi/backup.py','ops/pi/lab/backup_lab.py','ops/pi/lab/backup_fresh.py','ops/pi/lab/verify.py')}}))
    ledger=Ledger(lab.LEDGER_PATH);labels={'myink.pi.lab':runtime['lab_uuid'],'myink.pi.owner':'b11-fresh','myink.pi.operation':operation}
    names={role:runtime['project']+'-b11-fresh-'+operation.replace('-','')[:16]+'-'+role for role in ('pg','redis')}
    images={role:_docker('inspect',runtime['project']+'-'+role)[0]['Image'] for role in names}
    network=_docker('network','inspect',runtime['project']+'-fixtures')[0]
    namespace='-pi-'+runtime['lab_uuid']+'-b11-'+operation+'-'
    queues=json.loads(command(root,'/usr/bin/docker','--host','unix:///var/run/docker.sock','exec',runtime['project']+'-rabbit','rabbitmqctl','list_queues','name','messages','consumers','--formatter','json','--quiet').stdout)
    if any(v['name'].startswith(namespace) for v in queues):raise ValueError('fresh broker namespace exists')
    specification={'operation_id':operation,'lab_uuid':runtime['lab_uuid'],'labels':labels,'names':names,'images':images,'network_id':network['Id'],'namespace':namespace,'capacity':capacity,'paths':paths}
    ledger.intent('fresh-trial:'+operation,'fresh_trial',specification)
    durable_file(root/'specification.json',encoded(specification));services={}
    for role,name in names.items():
        volume=name+'-data';memory={'pg':256,'redis':96}[role];cpus={'pg':'.5','redis':'.25'}[role];port={'pg':'5432','redis':'6379'}[role]
        for kind,obj in [('container',name),('volume',volume)]:
            check=subprocess.run(['/usr/bin/docker','--host','unix:///var/run/docker.sock',kind,'inspect',obj],capture_output=True,timeout=10)
            if check.returncode==0:raise ValueError('fresh resource preexists')
        intent={'name':name,'volume':volume,'image':images[role],'operation_id':operation,'labels':labels,'memory_mib':memory,'cpus':cpus,'network_id':network['Id']}
        ledger.intent('fresh-fixture:'+operation+':'+role,'fresh_fixture',intent)
        flags=[part for key,value in labels.items() for part in ('--label',key+'='+value)]
        command(root,'/usr/bin/docker','--host','unix:///var/run/docker.sock','volume','create',*flags,volume)
        args=['/usr/bin/docker','--host','unix:///var/run/docker.sock','run','-d','--name',name,*flags,'--cgroup-parent','myinkpi-heavy.slice','--memory',str(memory)+'m','--memory-swap',str(memory)+'m','--cpus',cpus,'--mount','type=volume,source='+volume+',target='+('/var/lib/postgresql/data' if role=='pg' else '/data'),'--network',runtime['project']+'-fixtures','-p','127.0.0.1::'+port]
        if role=='pg':args+=['-e','POSTGRES_PASSWORD=synthetic-b11-fresh-only','-e','POSTGRES_DB=myink',images[role]]
        else:args += [images[role],'redis-server','--appendonly','yes']
        creation=command(root,*args);created=creation.stdout.decode().strip();info=_docker('inspect',created)[0]
        command_token=str(len(list((root/'commands').glob('*.intent.json')))-1)
        if info['Id']!=created or info['Name']!='/'+name or info['Image']!=images[role]:raise ValueError('fresh actual creation ID mismatch')
        if info['Config']['Labels']!=labels or info['HostConfig']['CgroupParent']!='myinkpi-heavy.slice' or info['HostConfig']['Memory']!=memory*1024**2 or info['HostConfig']['MemorySwap']!=memory*1024**2 or info['HostConfig']['NanoCpus']!=int(float(cpus)*10**9):raise ValueError('fresh actual limits/owner mismatch')
        if set(info['NetworkSettings']['Networks'])!={runtime['project']+'-fixtures'} or info['NetworkSettings']['Networks'][runtime['project']+'-fixtures']['NetworkID']!=network['Id']:raise ValueError('fresh actual network mismatch')
        if len(info['Mounts'])!=1 or info['Mounts'][0]['Name']!=volume or info['Mounts'][0]['Destination']!=('/var/lib/postgresql/data' if role=='pg' else '/data'):raise ValueError('fresh actual mount mismatch')
        if '/myinkpi.slice/myinkpi-heavy.slice/' not in Path('/proc/'+str(info['State']['Pid'])+'/cgroup').read_text():raise ValueError('fresh actual cgroup mismatch')
        endpoint=info['NetworkSettings']['Ports'][port+'/tcp']
        if len(endpoint)!=1 or endpoint[0]['HostIp']!='127.0.0.1':raise ValueError('fresh endpoint not loopback')
        service={'name':name,'id':created,'creation_command':command_token,'creation_intent_sha256':digest(root/'commands'/(command_token+'.intent.json')),'creation_receipt_sha256':digest(root/'commands'/(command_token+'.receipt.json')),'configuration':_configuration(info),'volume':_docker('volume','inspect',volume)[0],'port':int(info['NetworkSettings']['Ports'][port+'/tcp'][0]['HostPort'])}
        durable_file(root/('created-'+role+'.json'),encoded(service));ledger.append_event('fresh_fixture_created',{'role':role,'registry_sha256':digest(root/('created-'+role+'.json')),'container_id':created})
        services[role]=service
    pg=services['pg'];redis=services['redis'];dsn='postgresql://postgres:synthetic-b11-fresh-only@127.0.0.1:'+str(pg['port'])+'/myink'
    for _ in range(60):
        check=subprocess.run(['/usr/bin/docker','--host','unix:///var/run/docker.sock','exec',pg['id'],'pg_isready','-h','127.0.0.1','-U','postgres'],capture_output=True,timeout=5)
        if not check.returncode:break
        time.sleep(.2)
    import psycopg,redis as redis_module
    with psycopg.connect(dsn,autocommit=True) as db:
        system=db.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
        tables=db.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0];version=db.execute('SHOW server_version_num').fetchone()[0]
        if tables!=0 or version[:2]!='16':raise ValueError('fresh PG not empty16')
        source=json.loads((lab.BASE/'b11-source.json').read_text())
        if system==source['system_identifier']:raise ValueError('fresh fixture equals original source')
        ledger.intent('fresh-role-bootstrap:'+operation,'fresh_role_bootstrap',{'container_id':pg['id'],'system_identifier':system,'role':'myink','superuser':False,'bypassrls':False})
        db.execute("CREATE ROLE myink LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD 'synthetic-b11-fresh-only'")
        role_attributes=list(db.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='myink'").fetchone())
        if role_attributes!=[False,False]:raise ValueError('fresh source role unsafe')
        ledger.finish(Receipt('fresh-role-bootstrap:'+operation,'done',{'system_identifier':system,'role_attributes':role_attributes,'initial_public_tables':tables,'server_version_num':version}))
    client=redis_module.Redis(host='127.0.0.1',port=redis['port'],db=15)
    if not client.ping() or client.dbsize()!=0:raise ValueError('fresh Redis15 not entirely empty')
    value={'operation_id':operation,'lab_uuid':runtime['lab_uuid'],'paths':paths,'labels':labels,'services':services,'network_id':network['Id'],'system_identifier':system,'admin_dsn':dsn,
        'initial_public_tables':tables,'server_version_num':version,'myink_role_attributes':role_attributes,'redis_initial_dbsize':client.dbsize(),
        'redis_url':'redis://127.0.0.1:'+str(redis['port'])+'/0','broker_namespace_initial_empty':namespace,'capacity':capacity,'source_hashes':json.loads((root/'claim.json').read_text())['source_hashes']}
    durable_file(Path(paths['context']),encoded(value));ledger.append_event('fresh_context_created',{'sha256':digest(Path(paths['context']))})
    os.environ['B11_FRESH_CONTEXT']=paths['context'];os.environ.update(verify_context(runtime,original,operation))
    return value


def claim_labels(value,specification):
    if specification['operation_id']!=value['operation_id'] or specification['paths']!=value['paths']:raise ValueError('fresh specification drift')
    return specification['labels']


def stop_fixtures(value,status):
    root=directory(value['operation_id']);ledger=Ledger(Path(value['paths']['ledger']))
    claim=json.loads((root/'claim.json').read_text());specification=json.loads((root/'specification.json').read_text())
    if claim['operation_id']!=lab.current_operation() or claim['paths']!=value['paths'] or ledger.get('fresh-trial:'+value['operation_id'])['status'] not in ('done','failed'):raise ValueError('fresh stop lacks terminal exclusive owner')
    if (root/'claim.json').stat().st_uid!=0 or (root/'claim.json').stat().st_mode&0o077:raise ValueError('fresh stop untrusted claim')
    for role,service in reversed(list(value['services'].items())):
        info=_docker('inspect',service['id'])[0]
        registry=root/('created-'+role+'.json')
        with ledger.transaction() as db:events=[json.loads(row[0]) for row in db.execute("SELECT payload FROM events WHERE kind='fresh_fixture_created'")]
        bound=[e for e in events if e['role']==role]
        token=service['creation_command'];folder=root/'commands'
        intent=json.loads((folder/(token+'.intent.json')).read_text());receipt=json.loads((folder/(token+'.receipt.json')).read_text())
        if digest(folder/(token+'.intent.json'))!=service['creation_intent_sha256'] or digest(folder/(token+'.receipt.json'))!=service['creation_receipt_sha256'] or receipt['returncode']!=0 or receipt['stdout_sha256']!=digest(folder/(token+'.stdout')) or (folder/(token+'.stdout')).read_text().strip()!=service['id']:raise ValueError('fresh stop actual creation command proof missing')
        args=intent['arguments']
        if intent['operation_id']!=value['operation_id'] or args[:5]!=['/usr/bin/docker','--host','unix:///var/run/docker.sock','run','-d'] or args[args.index('--name')+1]!=service['name'] or specification['images'][role] not in args or service['volume']['Labels']!=claim_labels(value,specification):raise ValueError('fresh stop command ownership mismatch')
        if info['State']['Running'] and '/myinkpi.slice/myinkpi-heavy.slice/' not in Path('/proc/'+str(info['State']['Pid'])+'/cgroup').read_text():raise ValueError('fresh stop current cgroup drift')
        if len(bound)!=1 or bound[0]['registry_sha256']!=digest(registry) or _configuration(info)!=service['configuration'] or _docker('volume','inspect',service['volume']['Name'])[0]!=service['volume']:raise ValueError('fresh stop ownership drift')
        operation='fresh-fixture:'+value['operation_id']+':'+role
        ledger.finish(Receipt(operation,status,{'container_id':service['id'],'volume_retained':service['volume']['Name'],'effect_state':'initialized_source_trial_complete' if status=='done' else 'trial_failed_preserved'}))
        durable_file(root/('pre-stop-'+role+'.json'),encoded({'configuration':_configuration(info),'state':info['State'],'registry_sha256':digest(registry)}))
        command(root,'/usr/bin/docker','--host','unix:///var/run/docker.sock','logs',service['id'])
        command(root,'/usr/bin/docker','--host','unix:///var/run/docker.sock','stop','--time','10',service['id'])
        stopped=_docker('inspect',service['id'])[0]
        if stopped['State']['Running'] or stopped['State']['Pid']!=0:raise ValueError('fresh fixture PID exit unconfirmed')
        verify_runtime();ledger.append_event('fresh_fixture_stopped',{'role':role,'container_id':service['id'],'pid_exited':True,'original_runtime_verified':True})


def assert_corrupt_pre_refuses_release(ledger,pair_id,context_value,clock):
    candidate=ledger.get('release-pair:'+pair_id)['payload']['post_identity']
    try:mark_released(ledger,pair_id,candidate,context=context_value,now=clock)
    except ValueError:return True
    raise AssertionError('corrupt PRE authorized mark_released')


def run_fresh_trial():
    value=None;operation_id=lab.current_operation();operation='fresh-trial:'+operation_id;status='failed'
    try:
        value=provision();ledger=Ledger(Path(value['paths']['ledger']))
        observation=lab.initialize_and_pre()
        initial=ledger.get('source-initialization:'+value['operation_id'])
        if initial['status']!='done' or observation['evidence']['verification_kind']!='initial_current_creator':raise ValueError('fresh initialization authority absent')
        # Only this newly verified isolated synthetic context has known complete-empty references.
        record_recovery_references(ledger,'fresh-recovery-references:'+operation_id,version=1,context=lab.rehearsal_context(),complete=True,stable_ids=[],referenced_ids=[])
        result=lab.run_actual_pair();context_value=result['rehearsal_context'];clock=datetime.now(timezone.utc)
        assert release_allowed(ledger,'next-release',context=context_value,now=clock)
        assert not release_allowed(ledger,'next-release',context={**context_value,'tool_context':'changed'},now=clock)
        assert not release_allowed(ledger,'next-release',context={**context_value,'schema_context':'changed'},now=clock)
        assert not release_allowed(ledger,result['pre_receipt']['evidence']['release_pair_id'],context=context_value,now=clock+timedelta(days=7))
        assert release_allowed(ledger,'next-release',recovery=True)
        faults=[]
        for phase,pair_receipt in [('PRE',result['pre_receipt']),('POST',result['post_receipt'])]:
            path=Path(pair_receipt['evidence']['manifest_path']);manifest=json.loads(path.read_text());artifact=private_path(path.parent,manifest['artifacts']['attachments']['path'])
            before=digest(artifact);artifact.write_bytes(b'fixed synthetic corruption retained')
            assert not release_allowed(ledger,result['pre_receipt']['evidence']['release_pair_id'] if phase=='PRE' else 'next-release',context=context_value,now=clock)
            assert release_allowed(ledger,'next-release',recovery=True)
            if phase=='PRE':
                assert_corrupt_pre_refuses_release(ledger,result['pre_receipt']['evidence']['release_pair_id'],context_value,clock)
            faults.append({'phase':phase,'original_sha256':before,'corrupt_sha256':digest(artifact),'eligibility_blocked':True,'original_receipt_preserved':ledger.get(pair_receipt['operation_id'])['status']=='done'})
        status='done';evidence={'observation':observation,'pair':result,'corruption_guards':faults,'first_use_schema_tool_weekly_policy':True,'context_sha256':digest(Path(value['paths']['context']))}
        ledger.finish(Receipt(operation,status,evidence));durable_file(lab.PRIVATE/'evidence'/('b11-fresh-trial-'+value['operation_id']+'.json'),encoded(evidence));return evidence
    finally:
        if value is None:
            root=directory(operation_id);paths=fixed_paths(operation_id)
            if (root/'specification.json').exists():
                ledger=Ledger(Path(paths['ledger']));value={'operation_id':operation_id,'paths':paths,'services':{role:json.loads((root/('created-'+role+'.json')).read_text()) for role in ('pg','redis') if (root/('created-'+role+'.json')).exists()}}
        if value is not None:
            if status!='done':ledger.finish(Receipt(operation,'failed',{'reason':'fresh_trial_unconfirmed','partial_creation_preserved':True}))
            stop_fixtures(value,status)


def observe_retained_corruption():
    """One fixed negative gate observation; no fixture initialization or data import."""
    from ops.pi.backup import revalidate_collection
    lab.verify_test_environment()
    ancestor='e791db84-67aa-4bec-887f-51a55707ecad';root=directory(ancestor)
    proof_path=lab.PRIVATE/'evidence/b11-fix1-canonical-proof.json'
    if digest(proof_path)!='0776e7abc8d98f1ce5a458f226baf59f8930907cffce14241e1eca23ec25177c':raise ValueError('retained canonical proof drift')
    proof=json.loads(proof_path.read_text());value=context(ancestor)
    if digest(root/'context.json')!=proof['fresh_context_sha256'] or digest(root/'claim.json')!=proof['fresh_claim_sha256'] or digest(root/'source.json')!=proof['fresh_source_sha256']:raise ValueError('retained creator/context drift')
    ledger=Ledger(Path(value['paths']['ledger']))
    if digest(ledger.path)!=proof['ledger']['native']['sha256']:raise ValueError('retained canonical ledger drift')
    host=Ledger(lab.PRIVATE/'state/b11-executor-ledger.sqlite')
    with host.transaction() as db:receipts=[json.loads(row[0]) for row in db.execute("SELECT payload FROM events WHERE kind='tool_receipt'")]
    if [v for v in receipts if v['operation_id']==ancestor]!=[proof['controller_receipt']]:raise ValueError('original canonical DONE missing')
    if ledger.get('fresh-trial:'+ancestor)['status']!='done' or ledger.get('source-initialization:'+ancestor)['status']!='done':raise ValueError('first source lifecycle missing')
    with ledger.transaction() as db:
        checks=[Ledger._record(row) for row in db.execute("SELECT * FROM operations WHERE kind='restore_check' ORDER BY rowid")]
        before=[dict(row) for row in db.execute("SELECT * FROM operations WHERE kind='release' ORDER BY rowid")]
    clock=datetime.now(timezone.utc)
    if len(checks)!=2 or any(v['status']!='done' or v['evidence'].get('verified') is not True or len(v['evidence']['assertions'])!=12 or not timedelta(0)<=clock-datetime.fromisoformat(v['evidence']['rehearsal_completed_at'])<timedelta(days=7) for v in checks):raise ValueError('original actual rehearsal or fresh clock invalid')
    context_value=checks[0]['payload']['rehearsal_context']
    if checks[1]['payload']['rehearsal_context']!=context_value:raise ValueError('original rehearsal context mismatch')
    pair_id='b11-'+ancestor;pair=ledger.get('release-pair:'+pair_id)['payload'];candidate=pair['post_identity']
    if candidate['deployment_id']!='b11-post' or candidate['generation']!=2:raise ValueError('original matching candidate drift')
    operation='corruption-gate-observation:'+lab.current_operation()
    ledger.intent(operation,'corruption_gate_observation',{'ancestor_operation':ancestor,'proof_sha256':digest(proof_path),'context_sha256':digest(root/'context.json'),'pair_id':pair_id,'candidate':candidate,'rehearsal_context':context_value,'current_source_hashes':{n:digest(lab.BASE/'trusted-source'/n) for n in ('ops/pi/backup.py','ops/pi/lab/backup_lab.py','ops/pi/lab/backup_fresh.py','ops/pi/lab/verify.py')}})
    try:
        refusals={phase:revalidate_collection(ledger,ledger.get('backup:'+pair_id+':'+phase),Path(value['paths']['collections'])).status for phase in ('PRE','POST')}
        if refusals!={'PRE':'blocked','POST':'blocked'}:raise ValueError('expected retained corrupt collections absent')
        assert assert_corrupt_pre_refuses_release(ledger,pair_id,context_value,clock)
        assert not release_allowed(ledger,pair_id,context=context_value,now=clock)
        assert not release_allowed(ledger,'next-release',context=context_value,now=clock)
        assert release_allowed(ledger,pair_id,recovery=True)
        with ledger.transaction() as db:after=[dict(row) for row in db.execute("SELECT * FROM operations WHERE kind='release' ORDER BY rowid")]
        if before!=after:raise ValueError('negative observation changed release history')
        evidence={'ancestor_operation':ancestor,'candidate_matches_immutable_pair':True,'original_rehearsal_context_matches':True,'clock_within_seven_days':True,'observed_at':clock.isoformat(),'restores_verified':2,'collection_refusals':refusals,'mark_released_refused':True,'denial_scope':'known_corruption_POST_debt_and_PRE_not_PRE_only','release_rows_unchanged_sha256':hashlib.sha256(encoded(before)).hexdigest(),'recovery_allowed':True,'original_trial_identity_argument_limitation_preserved':True}
        lab.verify_test_environment();receipt=Receipt(operation,'done',evidence)
    except Exception as exc:
        ledger.finish(Receipt(operation,'failed',{'reason':'corruption_gate_observation_failed','error_class':type(exc).__name__}));raise
    ledger.finish(receipt);durable_file(lab.PRIVATE/'evidence'/('b11-corruption-gate-'+lab.current_operation()+'.json'),encoded({'operation_id':operation,'status':'done','evidence':evidence}));return evidence
