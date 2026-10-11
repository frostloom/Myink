"""Finite root-owned B11 handlers; no candidate SQL, DSN, paths or code."""
from dataclasses import asdict,replace
from datetime import datetime,timezone,timedelta
import base64,gzip,hashlib,json,os,secrets,shutil,subprocess,sys,time,uuid
from pathlib import Path
from ops.pi.backup import create_backup,restore_check,record_restore,mark_released,release_allowed,digest,encoded,private_path,verify_artifacts,durable_file
from ops.pi.contracts import Identity
from ops.pi.ledger import Ledger
from ops.pi.lab.verify import BASE,verify_runtime,verify_test_environment,_docker
from ops.pi.resources import sample_resources
PRIVATE=Path('/mnt/e/tools/myink-pi')
COLLECTIONS=PRIVATE/'backups/collections'
MATERIALS=BASE/'backup-materials'
SOURCE=BASE/'b11-source.json'
ROLES=('myink','myink_app','myink_report','myink_maintenance_control','myink_maintenance_stats')


def run(*args,input=None,timeout=90):
    result=subprocess.run(args,input=input,capture_output=True,timeout=timeout)
    debug=MATERIALS/'debug'/current_operation();debug.mkdir(parents=True,exist_ok=True,mode=0o700)
    token=str(uuid.uuid4())
    for stream in ('stdout','stderr'):durable_file(debug/(token+'.'+stream),getattr(result,stream))
    durable_file(debug/(token+'.command.json'),encoded({'executable':args[0],'arguments':list(args[1:]),'returncode':result.returncode}))
    result.check_returncode();return result


def current_operation():return json.loads((BASE/'current-operation.json').read_text())['operation_id']


def source_environment(original,proof):
    return {**original,'DATABASE_URL':original['DATABASE_URL'].rsplit('/',1)[0]+'/'+proof['database'],
        'ADMIN_DATABASE_URL':original['ADMIN_DATABASE_URL'].rsplit('/',1)[0]+'/'+proof['database'],
        'REDIS_URL':original['REDIS_URL'].rsplit('/',1)[0]+'/15','QUEUE_PREFIX':proof['prefix']}


def verify_source(r,original,operation):
    if SOURCE.is_symlink() or SOURCE.stat().st_uid!=0 or SOURCE.stat().st_mode&0o077:raise ValueError('untrusted B11 source')
    proof=json.loads(SOURCE.read_text())
    if proof['creation_status']!='ready' or proof['lab_uuid']!=r['lab_uuid'] or proof['material_ref']!=proof['creator_operation']:raise ValueError('source creation incomplete')
    creator=str(uuid.UUID(proof['creator_operation']))
    if (proof['database']!='myink_b11_'+uuid.UUID(creator).hex or proof['prefix']!='-pi-'+r['lab_uuid']+'-b11-'+creator+'-'
            or proof['redis_db']!=15 or proof['service_ids']!={name:_docker('inspect',name)[0]['Id'] for name in r['test_containers']}):raise ValueError('source identity drift')
    binding=BASE/('b11-binding-'+operation+'.json')
    if binding.is_symlink() or binding.stat().st_uid!=0 or binding.stat().st_mode&0o077:raise ValueError('untrusted transport binding')
    if json.loads(binding.read_text())!={'operation_id':operation,'creator_operation':creator,'source_sha256':digest(SOURCE),'lab_uuid':r['lab_uuid']}:raise ValueError('binding drift')
    env=source_environment(original,proof)
    import psycopg,redis
    with psycopg.connect(env['ADMIN_DATABASE_URL'].replace('postgresql+psycopg:','postgresql:')) as db:
        if list(db.execute('SELECT current_database(),system_identifier::text FROM pg_control_system()').fetchone())!=[proof['database'],proof['system_identifier']]:raise ValueError('PG source drift')
        if [list(v) for v in db.execute('SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=ANY(%s) ORDER BY rolname',(list(ROLES),))]!=proof['roles']:raise ValueError('source role drift')
    if not redis.Redis.from_url(env['REDIS_URL']).ping():raise ValueError('Redis15 unavailable')
    return env


def bind_source(proof,r,environment):
    operation=current_operation()
    durable_file(BASE/('b11-binding-'+operation+'.json'),encoded({'operation_id':operation,'creator_operation':proof['creator_operation'],'source_sha256':digest(SOURCE),'lab_uuid':r['lab_uuid']}))
    os.environ.update(source_environment(environment,proof),B11_SOURCE_DESCRIPTOR=str(SOURCE))
    verify_test_environment()


def initialize_source():
    r,environment=verify_test_environment()
    if SOURCE.exists() or 'myink.config' in sys.modules:raise ValueError('source claimed or business imported')
    import psycopg,redis
    from psycopg import sql
    client=redis.Redis.from_url(environment['REDIS_URL'].rsplit('/',1)[0]+'/15')
    if not client.ping() or client.dbsize()!=0:raise ValueError('Redis15 unavailable or entire database not empty')
    creator=current_operation();database='myink_b11_'+uuid.UUID(creator).hex
    proof={'creator_operation':creator,'lab_uuid':r['lab_uuid'],'database':database,'prefix':'-pi-'+r['lab_uuid']+'-b11-'+creator+'-',
        'redis_db':15,'redis_initial_dbsize':0,'service_ids':{name:_docker('inspect',name)[0]['Id'] for name in r['test_containers']},
        'source_hashes':{name:digest(BASE/'trusted-source'/name) for name in ('ops/pi/backup.py','ops/pi/lab/backup_lab.py','ops/pi/lab/verify.py','src/myink/db.py')},'creation_status':'claimed'}
    with psycopg.connect(environment['ADMIN_DATABASE_URL'].replace('postgresql+psycopg:','postgresql:'),autocommit=True) as db:
        proof['system_identifier']=db.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
        if db.execute('SELECT 1 FROM pg_database WHERE datname=%s',(database,)).fetchone():raise ValueError('source DB exists')
        durable_file(SOURCE,encoded(proof));db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        for role,bypass in [('myink_app',False),('myink_report',True)]:
            attrs=db.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=%s',(role,)).fetchone()
            if attrs is None:db.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER '+('BYPASSRLS' if bypass else 'NOBYPASSRLS')).format(sql.Identifier(role)))
            elif attrs!=(False,bypass):raise ValueError('existing required role unsafe')
    material=MATERIALS/creator;material.mkdir(parents=True,mode=0o700)
    durable_file(material/'model.key',secrets.token_urlsafe(48).encode())
    run('/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','7','-subj','/CN=b11.synthetic.invalid','-keyout',str(material/'certificate.key'),'-out',str(material/'certificate.pem'))
    for p in material.iterdir():p.chmod(0o600)
    durable_file(material/'config.json',encoded({'synthetic':True,'database':database,'model_http_disabled':True,'queue_prefix':proof['prefix']}))
    os.environ.update(source_environment(environment,proof));os.environ['MODEL_CREDENTIAL_KEY']=(material/'model.key').read_text()
    run(sys.executable,'-m','myink.cli','init','--seed')
    from myink.db import get_admin_engine,ensure_maintenance_schema
    from sqlalchemy import text
    with get_admin_engine().begin() as db:
        tables=[row[0] for row in db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('maintenance_control','admission_intents','queue_handoffs','maintenance_executions')"))]
        for table in tables:
            db.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON '+table+' TO myink_app'))
            db.execute(text('GRANT SELECT ON '+table+' TO myink_report'))
        db.execute(text('GRANT USAGE ON SCHEMA public TO myink_app,myink_report'))
        db.execute(text('ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO myink_app'))
        db.execute(text('ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT ON TABLES TO myink_report'))
        db.execute(text('ALTER ROLE myink_report SET default_transaction_read_only=on'))
    ensure_maintenance_schema();fixture=seed_dataset(material)
    with psycopg.connect(os.environ['ADMIN_DATABASE_URL'].replace('postgresql+psycopg:','postgresql:')) as db:
        proof['roles']=[list(v) for v in db.execute('SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=ANY(%s) ORDER BY rolname',(list(ROLES),))]
    proof.update(creation_status='ready',fixture=fixture,material_ref=creator)
    temp=SOURCE.with_suffix('.ready.part');durable_file(temp,encoded(proof));temp.replace(SOURCE)
    bind_source(proof,r,environment)
    return proof


def seed_dataset(material):
    from sqlalchemy.orm import Session
    from myink.db import get_admin_engine
    from myink.models import User,Project,Chapter,Task,Entity,Relation,EmbeddingRow,Feedback
    from myink.providers.credentials import encrypt_api_key
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.checkpoint.base import empty_checkpoint
    from psycopg.rows import dict_row
    import psycopg
    ids={name:str(uuid.uuid4()) for name in ('user_a','user_b','project_a','project_b','task','entity_a','entity_b','feedback')}
    attachment=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWZkAAAAASUVORK5CYII=')
    attachment_path=material/'attachments'/ids['feedback']/'synthetic.png';attachment_path.parent.mkdir(parents=True,mode=0o700)
    durable_file(attachment_path,attachment)
    with Session(get_admin_engine()) as db:
        for suffix in ('a','b'):
            db.add(User(id=uuid.UUID(ids['user_'+suffix]),username='b11-'+suffix+'-'+ids['user_'+suffix][:8],environment={'synthetic_credential':encrypt_api_key('b11-synthetic-token')} if suffix=='a' else {}))
        db.flush()
        for suffix in ('a','b'):db.add(Project(id=uuid.UUID(ids['project_'+suffix]),user_id=uuid.UUID(ids['user_'+suffix]),title='B11 '+suffix))
        db.flush()
        for suffix in ('a','b'):db.add(Chapter(project_id=uuid.UUID(ids['project_'+suffix]),chapter_seq=1,title='B11 '+suffix,content='synthetic '+suffix,status='confirmed'))
        db.add(Task(id=uuid.UUID(ids['task']),project_id=uuid.UUID(ids['project_a']),task_type='chapter_generate',status='done',payload={'thread_id':ids['task'],'synthetic':True},chapter_seq=1))
        for suffix in ('a','b'):db.add(Entity(id=uuid.UUID(ids['entity_'+suffix]),project_id=uuid.UUID(ids['project_a']),entity_type='character',canonical_name='Synthetic '+suffix))
        db.add(Relation(project_id=uuid.UUID(ids['project_a']),source_id=uuid.UUID(ids['entity_a']),target_id=uuid.UUID(ids['entity_b']),relation_type='ally',source_chapter=1))
        db.add(EmbeddingRow(project_id=uuid.UUID(ids['project_a']),level='world',source_id=uuid.UUID(ids['entity_a']),model_version='synthetic-no-model',embedding=[1.0]+[0.0]*1023))
        db.add(Feedback(id=uuid.UUID(ids['feedback']),user_id=uuid.UUID(ids['user_a']),description='synthetic recovery attachment',attachments=[{'name':'synthetic.png','mime':'image/png','bytes':len(attachment),'stored':'synthetic.png'}]))
        db.commit()
    with psycopg.connect(os.environ['ADMIN_DATABASE_URL'].replace('postgresql+psycopg:','postgresql:'),autocommit=True,row_factory=dict_row) as conn:
        saver=PostgresSaver(conn);saver.setup();checkpoint=empty_checkpoint()
        checkpoint['channel_values']={'state':{'task_id':ids['task'],'project_id':ids['project_a'],'draft':'synthetic checkpoint','chapter_seq':1}}
        checkpoint['channel_versions']={'state':'1'}
        config=saver.put({'configurable':{'thread_id':ids['task'],'checkpoint_ns':''}},checkpoint,{'source':'update','step':1,'parents':{}},{'state':'1'})
        saver.put_writes(config,[('state',{'draft':'synthetic pending write'})],'persist-next');ids['checkpoint_id']=checkpoint['id']
        conn.execute("UPDATE maintenance_control SET epoch=%s,deployment_id='b11-pre',generation=1,owner='trusted-b11',image_ids=%s,deadline=%s,admission_closed=true,consumer_blocked=true WHERE id=1",('b11-'+current_operation(),json.dumps({'worker':'synthetic-fixed-source'}),datetime.now(timezone.utc)+timedelta(minutes=10)))
    durable_file(material/'expected.json',encoded(ids))
    return ids


def prepare(selection):
    if selection not in ('b11-source','b11-restore','b11-verify'):raise ValueError('unknown B11 selection')
    r,environment=verify_test_environment()
    if selection=='b11-source':initialize_source()
    else:
        proof=json.loads(SOURCE.read_text());bind_source(proof,r,environment)
    if selection=='b11-verify':
        print(json.dumps(observe_source()));return
    observe_source()
    subprocess.run([sys.executable,'-m','pytest','ops/pi/tests/integration/test_restore.py','-q','-m','pi_lab','--pi-lab','--tb=short','-x','-vv'],check=True,timeout=540)


def get_boundary(*,observing=False):
    r,_=verify_test_environment();proof=json.loads(SOURCE.read_text())
    os.environ['MODEL_CREDENTIAL_KEY']=(MATERIALS/proof['material_ref']/'model.key').read_text()
    boundary=Boundary(proof,r)
    if not observing:
        verified=boundary.ledger.get('source-verification:'+current_operation())
        hashes={name:digest(BASE/'trusted-source'/name) for name in ('ops/pi/backup.py','ops/pi/lab/backup_lab.py','ops/pi/lab/verify.py')}
        if (not verified or verified['status']!='done' or verified['payload']['source_sha256']!=digest(SOURCE)
            or verified['payload']['creator_operation']!=proof['creator_operation'] or verified['payload']['lab_uuid']!=r['lab_uuid']
            or verified['payload']['current_source_hashes']!=hashes):raise ValueError('current canonical source verification required')
    return boundary


class Boundary:
    def __init__(self,proof,r):
        self.proof=proof;self.runtime=r;self.material=private_path(MATERIALS,proof['material_ref'])
        self.ledger=Ledger(PRIVATE/'state/b11-backup-ledger.sqlite');self.started=time.monotonic();self.target=None;self.owned_target=None

    def capacity(self):
        import psycopg
        with psycopg.connect(os.environ['ADMIN_DATABASE_URL'].replace('postgresql+psycopg:','postgresql:')) as db:size=db.execute('SELECT pg_database_size(current_database())').fetchone()[0]
        peak=max(1024*1024**2,size*10);reserve=5*1024**3
        proof={'planned_peak_bytes':peak,'reserve_bytes':reserve,'e_free_bytes':shutil.disk_usage('/mnt/e').free,'guest_free_bytes':shutil.disk_usage('/').free}
        if min(proof['e_free_bytes'],proof['guest_free_bytes'])<peak+reserve:raise ValueError('disk peak+5GiB gate failed')
        if time.monotonic()-self.started>=600:raise TimeoutError('deadline')
        return proof

    def quiet(self,identity):
        verify_test_environment();self.capacity()
        from sqlalchemy.orm import Session
        from sqlalchemy import text
        from myink.db import get_admin_engine
        from myink.maintenance import maintenance_view
        from myink.worker.handoff import reconcile_queue
        with Session(get_admin_engine()) as db:
            control=maintenance_view(db)
            if any(control[k]!=identity[k] for k in ('deployment_id','generation','owner','image_ids')):raise ValueError('deployment drift')
            census=reconcile_queue(db,control['epoch'])
            if not census['verified'] or census['unknown'] or census['queue_messages'] or census['planned']:raise ValueError('source not quiescent')
            if db.execute(text("SELECT count(*) FROM tasks WHERE status NOT IN ('done','cancelled','failed')")).scalar():raise ValueError('unconfirmed active task')
            self.census=census
        return {'verified':True,'consistency_id':control['epoch']+':'+digest(SOURCE)}

    def __call__(self,action,context):
        if action=='verify_identity':return self.quiet(context['identity'])
        if action=='collect':return self.collect(context)
        if action=='restore':return self.restore(context)
        raise ValueError('unknown finite action')

    def collect(self,context):
        directory=Path(context['directory'])
        if directory!=COLLECTIONS/hashlib.sha256(context['operation_id'].encode()).hexdigest():raise ValueError('foreign collection path')
        before=self.quiet(context['identity'])
        dump=run('/usr/bin/docker','--host','unix:///var/run/docker.sock','exec',self.runtime['project']+'-pg','pg_dump','-U','postgres','-d',self.proof['database'])
        if not dump.stdout or dump.stderr:raise ValueError('dump empty or stderr')
        durable_file(directory/'database.sql.gz.part',gzip.compress(dump.stdout,compresslevel=1))
        with gzip.open(directory/'database.sql.gz.part','rb') as f:
            if f.read()!=dump.stdout:raise ValueError('gzip verification failed')
        (directory/'database.sql.gz.part').replace(directory/'database.sql.gz')
        durable_file(directory/'roles.sql',export_roles());paths={'database':'database.sql.gz','roles':'roles.sql'}
        for role,name in [('crypto','model.key'),('config','config.json'),('certificate','certificate.pem'),('certificate_key','certificate.key'),('expected','expected.json')]:
            shutil.copyfile(self.material/name,directory/name);(directory/name).chmod(0o600);paths[role]=name
        attachment='attachments/'+self.proof['fixture']['feedback']+'/synthetic.png'
        target=directory/attachment;target.parent.mkdir(parents=True,mode=0o700)
        shutil.copyfile(self.material/attachment,target);target.chmod(0o600);paths['attachments']=attachment
        if self.quiet(context['identity'])!=before:raise ValueError('consistency changed')
        return {**before,'dump_exit':dump.returncode,'dump_stderr_bytes':len(dump.stderr),'source_id':self.proof['database'],
            'roles':list(ROLES),'artifacts':paths,'not_applicable':['production TLS','remote offsite','real upstream credentials'],**self.capacity()}

    def new_target(self,collection,fault):
        self.capacity();r=verify_runtime();operation=current_operation()
        case_id=str(uuid.uuid5(uuid.UUID(operation),fault+str(collection)))
        suffix=uuid.UUID(case_id).hex[:16]
        name=r['project']+'-b11-restore-'+suffix;volume=name+'-data'
        for kind,obj in [('container',name),('volume',volume)]:
            check=subprocess.run(['/usr/bin/docker','--host','unix:///var/run/docker.sock',kind,'inspect',obj],capture_output=True,timeout=10)
            if check.returncode==0:raise ValueError('restore resource exists')
        label=['--label','myink.pi.lab='+r['lab_uuid'],'--label','myink.pi.owner=b11-restore','--label','myink.pi.operation='+operation]
        image=_docker('inspect',r['project']+'-pg')[0]['Image']
        target_operation='restore-target:'+case_id
        self.ledger.intent(target_operation,'restore_target',{'case_uuid':case_id,'operation_id':operation,'fault':fault,'collection_id':collection.name,
            'name':name,'volume':volume,'image':image,'lab_uuid':r['lab_uuid']})
        self.owned_target=(name,volume,operation,image,target_operation)
        run('/usr/bin/docker','--host','unix:///var/run/docker.sock','volume','create',*label,volume)
        run('/usr/bin/docker','--host','unix:///var/run/docker.sock','run','-d','--name',name,*label,'--cgroup-parent','myinkpi-heavy.slice',
            '--memory','256m','--memory-swap','256m','--cpus','.5','--mount','type=volume,source='+volume+',target=/var/lib/postgresql/data',
            '--network',r['project']+'-fixtures','-p','127.0.0.1::5432','-e','POSTGRES_PASSWORD=synthetic-b11-restore-only','-e','POSTGRES_DB=b11_restored',image)
        from ops.pi.lab.verify import _configuration
        created=_docker('inspect',name)[0]
        registry={'case_uuid':case_id,'target_operation':target_operation,'operation_id':operation,'container_id':created['Id'],
            'lab_uuid':r['lab_uuid'],'volume':volume,'volume_labels':_docker('volume','inspect',volume)[0]['Labels'],'configuration':_configuration(created)}
        registry_path=PRIVATE/'evidence'/('b11-target-created-'+case_id+'.json');durable_file(registry_path,encoded(registry))
        self.ledger.append_event('restore_target_created',{'target_operation':target_operation,'registry_sha256':digest(registry_path),'container_id':created['Id']})
        for _ in range(60):
            check=subprocess.run(['/usr/bin/docker','--host','unix:///var/run/docker.sock','exec',name,'pg_isready','-h','127.0.0.1','-U','postgres'],capture_output=True,timeout=5)
            if not check.returncode:break
            time.sleep(.2)
        info=_docker('inspect',name)[0];vol=_docker('volume','inspect',volume)[0];labels=info['Config']['Labels']
        if any(labels.get(k)!=v for k,v in {'myink.pi.lab':r['lab_uuid'],'myink.pi.owner':'b11-restore','myink.pi.operation':operation}.items()):raise ValueError('target label drift')
        if vol['Labels']!=labels:raise ValueError('volume ownership drift')
        if (info['Image']!=image or info['HostConfig']['CgroupParent']!='myinkpi-heavy.slice' or info['HostConfig']['Memory']!=256*1024**2
            or info['HostConfig']['MemorySwap']!=256*1024**2 or info['HostConfig']['NanoCpus']!=500000000
            or set(info['NetworkSettings']['Networks'])!={r['project']+'-fixtures'}):raise ValueError('target isolation drift')
        if '/myinkpi.slice/myinkpi-heavy.slice/' not in Path('/proc/'+str(info['State']['Pid'])+'/cgroup').read_text():raise ValueError('target outside heavy')
        if len(info['Mounts'])!=1 or info['Mounts'][0]['Name']!=volume:raise ValueError('target mounts drift')
        bindings=info['NetworkSettings']['Ports']['5432/tcp'];assert len(bindings)==1 and bindings[0]['HostIp']=='127.0.0.1'
        import psycopg
        dsn='postgresql://postgres:synthetic-b11-restore-only@127.0.0.1:'+bindings[0]['HostPort']+'/b11_restored'
        with psycopg.connect(dsn) as db:
            system=db.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
            if db.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0]!=0 or system==self.proof['system_identifier']:raise ValueError('nonempty or source target')
            if db.execute('SHOW server_version_num').fetchone()[0][:2]!='16':raise ValueError('PG16 required')
        target={'clean':True,'system_identifier':system,'source_system_identifier':self.proof['system_identifier'],
            'collection_directory':str(collection),'name':name,'volume':volume,'dsn':dsn,'fault':fault}
        self.target=target
        durable_file(PRIVATE/'evidence'/('b11-target-'+suffix+'.json'),encoded({k:v for k,v in target.items() if k!='dsn'}))
        return target

    def stop_owned_target(self,case_status='failed'):
        if self.owned_target is None:return
        name,volume,operation,image,target_operation=self.owned_target
        intent=self.ledger.get(target_operation);case_id=intent['payload']['case_uuid']
        registry_path=PRIVATE/'evidence'/('b11-target-created-'+case_id+'.json');registry=json.loads(registry_path.read_text())
        with self.ledger.transaction() as db:
            events=[json.loads(row[0]) for row in db.execute("SELECT payload FROM events WHERE kind='restore_target_created'")]
        bound=[event for event in events if event['target_operation']==target_operation]
        if len(bound)!=1 or bound[0]['registry_sha256']!=digest(registry_path):raise ValueError('target creation registry unconfirmed')
        info=_docker('inspect',name)[0]
        expected={'myink.pi.lab':self.runtime['lab_uuid'],'myink.pi.owner':'b11-restore','myink.pi.operation':operation}
        if (info['Config']['Labels']!=expected or info['Image']!=image or info['HostConfig']['CgroupParent']!='myinkpi-heavy.slice'
            or len(info['Mounts'])!=1 or info['Mounts'][0]['Name']!=volume or _docker('volume','inspect',volume)[0]['Labels']!=expected):raise ValueError('target cleanup ownership drift')
        if operation!=current_operation():raise ValueError('foreign target transport')
        from ops.pi.lab.verify import _configuration
        if info['Id']!=registry['container_id'] or _configuration(info)!=registry['configuration']:raise ValueError('target registry/config drift')
        self.ledger.finish(__import__('ops.pi.contracts',fromlist=['Receipt']).Receipt(target_operation,case_status,{'case_uuid':case_id,'container_id':info['Id'],'fault':intent['payload']['fault'],'effect_state':'restore_assertions_complete' if case_status=='done' else 'failed_or_negative_preserved'}))
        evidence={'name':name,'id':info['Id'],'labels':expected,'configuration':__import__('ops.pi.lab.verify',fromlist=['_configuration'])._configuration(info),
            'state':info['State'],'volume_retained':volume,'case_uuid':case_id,'case_status':case_status,'registry_sha256':digest(registry_path)}
        durable_file(PRIVATE/'evidence'/('b11-target-retained-'+operation+'-'+name.rsplit('-',1)[-1]+'.json'),encoded(evidence))
        run('/usr/bin/docker','--host','unix:///var/run/docker.sock','logs',name)
        if info['State']['Running']:run('/usr/bin/docker','--host','unix:///var/run/docker.sock','stop','--time','10',info['Id'],timeout=30)
        stopped=_docker('inspect',info['Id'])[0]
        if stopped['State']['Running'] or stopped['State']['Pid']!=0:raise ValueError('target PID exit unconfirmed')
        verify_test_environment()
        self.ledger.append_event('restore_target_stopped',{'target_operation':target_operation,'container_id':info['Id'],'pid_exited':True,'source_stable_runtime_verified':True})

    def restore(self,context):
        target=context['target'];manifest=context['manifest']
        if target!=self.target or target['fault'] not in ('positive','wrong-key','missing-key','missing-role','missing-attachment','missing-certificate'):raise ValueError('foreign restore target')
        self.capacity();verify_test_environment();directory=Path(target['collection_directory']);verify_artifacts(manifest,directory)
        roles=(directory/'roles.sql').read_bytes()
        if target['fault']=='missing-role':roles=b'-- deliberately omitted required roles\n'
        for body in (roles,gzip.decompress((directory/'database.sql.gz').read_bytes())):
            run('/usr/bin/docker','--host','unix:///var/run/docker.sock','exec','-i',target['name'],'psql','-U','postgres','-d','b11_restored','-v','ON_ERROR_STOP=1',input=body)
        assertions=assert_restored(target['dsn'],directory,self.proof,wrong_key=target['fault']=='wrong-key')
        return {'verified':True,'target_system_identifier':target['system_identifier'],'source_system_identifier':self.proof['system_identifier'],
            'assertions':assertions,'snapshot_event_hwm':manifest['ledger_snapshot']['event_hwm'],**self.capacity()}


def export_roles():
    import psycopg
    from psycopg import sql
    with psycopg.connect(os.environ['ADMIN_DATABASE_URL'].replace('postgresql+psycopg:','postgresql:')) as db:
        rows=db.execute('SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=ANY(%s) ORDER BY rolname',(list(ROLES),)).fetchall()
        if len(rows)!=len(ROLES):raise ValueError('required role missing')
        result=[]
        for name,*attrs in rows:
            opts=[('' if value else 'NO')+option for value,option in zip(attrs,('SUPERUSER','INHERIT','CREATEROLE','CREATEDB','LOGIN','REPLICATION','BYPASSRLS'))]
            result.append(sql.SQL('CREATE ROLE {} '+ ' '.join(opts)+';').format(sql.Identifier(name)).as_string(db))
        if db.execute("SELECT 1 FROM pg_roles WHERE rolname='myink_app' AND (rolsuper OR rolbypassrls)").fetchone():raise ValueError('app bypasses RLS')
        result.append('ALTER ROLE myink_report SET default_transaction_read_only=on;')
        for member,parent in db.execute('SELECT m.rolname,r.rolname FROM pg_auth_members a JOIN pg_roles r ON r.oid=a.roleid JOIN pg_roles m ON m.oid=a.member WHERE m.rolname=ANY(%s)',(list(ROLES),)):
            if parent not in ROLES:raise ValueError('role membership outside allowlist')
            result.append(sql.SQL('GRANT {} TO {};').format(sql.Identifier(parent),sql.Identifier(member)).as_string(db))
    return ('\n'.join(result)+'\n').encode()


def assert_restored(dsn,directory,proof,wrong_key=False):
    import psycopg
    from psycopg.rows import dict_row
    from langgraph.checkpoint.postgres import PostgresSaver
    from myink.providers import credentials
    ids=proof['fixture'];assert json.loads((directory/'expected.json').read_text())==ids
    key=(directory/'model.key').read_text()
    if not key:raise ValueError('explicit key required')
    if wrong_key:key='wrong-explicit-key'
    with psycopg.connect(dsn,autocommit=True,row_factory=dict_row) as db:
        task=db.execute('SELECT project_id,payload,status FROM tasks WHERE id=%s',(ids['task'],)).fetchone()
        assert str(task['project_id'])==ids['project_a'] and task['payload']['thread_id']==ids['task'] and task['status']=='done'
        saver=PostgresSaver(db);saved=saver.get_tuple({'configurable':{'thread_id':ids['task'],'checkpoint_ns':'','checkpoint_id':ids['checkpoint_id']}})
        assert saved.checkpoint['channel_values']['state']=={'task_id':ids['task'],'project_id':ids['project_a'],'draft':'synthetic checkpoint','chapter_seq':1}
        assert ('persist-next','state',{'draft':'synthetic pending write'}) in saved.pending_writes
        assert db.execute('SELECT source_id,target_id FROM relations WHERE project_id=%s',(ids['project_a'],)).fetchone()=={'source_id':uuid.UUID(ids['entity_a']),'target_id':uuid.UUID(ids['entity_b'])}
        assert db.execute('SELECT count(*) n FROM entities WHERE id=ANY(%s::uuid[])',([ids['entity_a'],ids['entity_b']],)).fetchone()['n']==2
        assert db.execute('SELECT vector_dims(embedding) dims,embedding::text value FROM embeddings WHERE project_id=%s',(ids['project_a'],)).fetchone()=={'dims':1024,'value':'['+','.join(['1']+['0']*1023)+']'}
        encrypted=db.execute('SELECT environment FROM users WHERE id=%s',(ids['user_a'],)).fetchone()['environment']['synthetic_credential']
        old=credentials.settings;credentials.settings=replace(old,model_credential_key=key)
        try:
            if credentials.decrypt_api_key(encrypted)!='b11-synthetic-token':raise ValueError('credential decrypt failed')
        finally:credentials.settings=old
        meta=db.execute('SELECT attachments FROM feedback WHERE id=%s',(ids['feedback'],)).fetchone()['attachments'][0]
        attachment=directory/'attachments'/ids['feedback']/meta['stored']
        assert meta['bytes']==attachment.stat().st_size and meta['mime']=='image/png' and attachment.read_bytes().startswith(b'\x89PNG')
        assert db.execute("SELECT bool_and(relrowsecurity AND relforcerowsecurity) value FROM pg_class WHERE relname IN ('chapters','relations','entities','embeddings')").fetchone()['value']
        assert db.execute("SELECT count(*) n FROM pg_policies WHERE policyname='tenant_isolation' AND tablename IN ('chapters','relations','entities','embeddings')").fetchone()['n']==4
        assert db.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='myink_app'").fetchone()=={'rolsuper':False,'rolbypassrls':False}
        db.execute('SET ROLE myink_app')
        for suffix in ('a','b'):
            with db.transaction():
                db.execute("SELECT set_config('app.tenant_id',%s,true)",(ids['project_'+suffix],))
                assert db.execute('SELECT project_id,content FROM chapters').fetchall()==[{'project_id':uuid.UUID(ids['project_'+suffix]),'content':'synthetic '+suffix}]
            assert db.execute('SELECT count(*) n FROM chapters').fetchone()['n']==0
        db.execute("SELECT set_config('app.tenant_id','',false)");assert db.execute('SELECT count(*) n FROM chapters').fetchone()['n']==0
        db.execute('RESET ROLE');db.execute('SET ROLE myink_report')
        assert db.execute('SELECT count(*) n FROM chapters').fetchone()['n']>=2
        assert not db.execute("SELECT has_table_privilege(current_user,'chapters','INSERT') value").fetchone()['value']
        db.execute('RESET ROLE')
        assert [list(row.values()) for row in db.execute('SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=ANY(%s) ORDER BY rolname',(list(ROLES),))]==proof['roles']
        assert db.execute("SELECT pg_get_userbyid(proowner) owner FROM pg_proc WHERE proname='myink_lock_maintenance'").fetchone()['owner']=='postgres'
        assert db.execute("SELECT count(*) n FROM pg_default_acl WHERE defaclrole='postgres'::regrole").fetchone()['n']>=1
    assert json.loads((directory/'config.json').read_text())['database']==proof['database']
    run('/usr/bin/openssl','x509','-in',str(directory/'certificate.pem'),'-noout','-checkend','0')
    assert run('/usr/bin/openssl','x509','-in',str(directory/'certificate.pem'),'-pubkey','-noout').stdout==run('/usr/bin/openssl','pkey','-in',str(directory/'certificate.key'),'-pubout').stdout
    return ['task_thread_association','checkpoint_state','pending_writes','chapter_contents','relation_endpoints','vector_1024',
        'explicit_credential_decrypt','attachment_metadata_bytes_hash','RLS_two_tenants_absent_empty_no_leak','roles_owners_grants_defaults','config_certificate_key','external_ledger_integrity_watermarks']


def identities():
    pre=Identity('b11-pre',1,'trusted-b11',{'worker':'synthetic-fixed-source'},commit_sha='5bf325b254dcbcb6d998cd20502e041127267b1c')
    post=Identity('b11-post',2,'trusted-b11',{'worker':'synthetic-fixed-source'},commit_sha=pre.commit_sha)
    proof=json.loads(SOURCE.read_text())
    return pre,post,{'release_pair_id':'b11-'+proof['creator_operation'],'pre_identity':asdict(pre),'post_identity':asdict(post),'plan_hash':hashlib.sha256(b'B11 synthetic backup transition').hexdigest()}


def run_actual_pair():
    boundary=get_boundary();pre,post,pair=identities()
    pre_receipt=create_backup(boundary.ledger,'PRE',pre,boundary,COLLECTIONS,pair=pair)
    assert pre_receipt.status=='done',pre_receipt
    collection=Path(pre_receipt.evidence['manifest_path']).parent;m=json.loads((collection/'manifest.json').read_text())
    try:
        target=boundary.new_target(collection,'positive')
        restored=restore_check(m,target,boundary);record_restore(boundary.ledger,pre_receipt,restored)
    finally:boundary.stop_owned_target(restored.status if 'restored' in locals() else 'failed')
    assert restored.status=='done',restored
    released=boundary.ledger.get('release:'+pair['release_pair_id'])
    if not released:
        assert release_allowed(boundary.ledger,pair['release_pair_id'])
        mark_released(boundary.ledger,pair['release_pair_id'],asdict(post))
        import psycopg
        with psycopg.connect(os.environ['ADMIN_DATABASE_URL'].replace('postgresql+psycopg:','postgresql:')) as db:
            db.execute("UPDATE maintenance_control SET deployment_id='b11-post',generation=2 WHERE id=1 AND deployment_id='b11-pre' AND admission_closed AND consumer_blocked")
    if not boundary.ledger.get('backup:'+pair['release_pair_id']+':POST'):assert not release_allowed(boundary.ledger,'next-release')
    post_receipt=create_backup(boundary.ledger,'POST',post,boundary,COLLECTIONS,pair=pair)
    assert post_receipt.status=='done',post_receipt
    post_collection=Path(post_receipt.evidence['manifest_path']).parent;post_manifest=json.loads((post_collection/'manifest.json').read_text())
    try:
        post_target=boundary.new_target(post_collection,'positive')
        post_restore=restore_check(post_manifest,post_target,boundary);record_restore(boundary.ledger,post_receipt,post_restore)
    finally:boundary.stop_owned_target(post_restore.status if 'post_restore' in locals() else 'failed')
    assert post_restore.status=='done',post_restore
    boundary.quiet(asdict(post));assert_restored(os.environ['ADMIN_DATABASE_URL'].replace('postgresql+psycopg:','postgresql:'),post_collection,boundary.proof)
    result={'pre':pre_receipt.status,'post':post_receipt.status,'restore':post_restore.status,'offsite_status':'not_configured',
        'census_unknown':boundary.census['unknown'],'source_unchanged':True,'pre_receipt':asdict(pre_receipt),'post_receipt':asdict(post_receipt),
        'restores':[asdict(restored),asdict(post_restore)],'source_descriptor_sha256':digest(SOURCE),'creator':boundary.proof['creator_operation'],
        'current_operation':current_operation(),'resources':sample_resources('heavy'),'capacity':boundary.capacity()}
    durable_file(PRIVATE/'evidence'/('b11-pair-'+current_operation()+'.json'),encoded(result))
    return result


def run_restore_fault(fault):
    boundary=get_boundary();pre,_,pair=identities()
    receipt=boundary.ledger.get('backup:'+pair['release_pair_id']+':PRE')
    collection=Path(receipt['evidence']['manifest_path']).parent;manifest=json.loads((collection/'manifest.json').read_text())
    copy=PRIVATE/'backups/faults'/(current_operation()+'-'+fault);copy.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(collection,copy)
    for kind,role in [('missing-key','crypto'),('missing-attachment','attachments'),('missing-certificate','certificate')]:
        if fault==kind:private_path(copy,manifest['artifacts'][role]['path']).unlink()
    try:
        target=boundary.new_target(copy,fault);result=restore_check(manifest,target,boundary)
    finally:boundary.stop_owned_target(result.status if 'result' in locals() else 'failed')
    boundary.ledger.intent(result.operation_id,'restore_negative',{'fault':fault,'backup_id':manifest['backup_id'],'transport_operation':current_operation()})
    boundary.ledger.finish(result)
    durable_file(PRIVATE/'evidence'/('b11-fault-'+current_operation()+'-'+fault+'.json'),encoded(asdict(result)))
    return result


def observe_source():
    """Current observation only; original creator parent remains failed/unreceipted."""
    boundary=get_boundary(observing=True);pre,post,pair=identities();operation='source-verification:'+current_operation()
    payload={'creator_operation':boundary.proof['creator_operation'],'source_sha256':digest(SOURCE),'lab_uuid':boundary.runtime['lab_uuid'],
        'current_source_hashes':{name:digest(BASE/'trusted-source'/name) for name in ('ops/pi/backup.py','ops/pi/lab/backup_lab.py','ops/pi/lab/verify.py')}}
    boundary.ledger.intent(operation,'source_verification',payload)
    from ops.pi.contracts import Receipt
    try:
        # Immutable creator source attribution uses its preserved frozen source manifest and actual failed transport events.
        created=json.loads((PRIVATE/'evidence/b11-source1.json').read_text())
        if any(created.get(name)!=value for name,value in boundary.proof['source_hashes'].items() if name in created):raise ValueError('creator tested source attribution drift')
        host=Ledger(PRIVATE/'state/b11-executor-ledger.sqlite')
        with host.transaction() as db:
            events=[json.loads(row[0]) for row in db.execute("SELECT payload FROM events WHERE kind='tool_receipt'")]
        creator=[v for v in events if v['operation_id']==boundary.proof['creator_operation']]
        if not creator or creator[-1]['lab_uuid']!=boundary.runtime['lab_uuid'] or creator[-1]['command_id']!='backup' or creator[-1]['status']!='failed':raise ValueError('creator failure provenance missing')
        identity=post if boundary.ledger.get('release:'+pair['release_pair_id']) else pre
        quiet=boundary.quiet(asdict(identity))
        assertions=assert_restored(os.environ['ADMIN_DATABASE_URL'].replace('postgresql+psycopg:','postgresql:'),boundary.material,boundary.proof)
        import redis
        cardinality=redis.Redis.from_url(os.environ['REDIS_URL']).dbsize()
        if cardinality!=0:raise ValueError('unexpected current synthetic Redis15 content')
        existing=boundary.ledger.get('backup:'+pair['release_pair_id']+':PRE')
        from ops.pi.backup import revalidate_collection
        if not existing or revalidate_collection(boundary.ledger,existing,COLLECTIONS).status!='done':raise ValueError('PRE publication reconciliation failed')
        m=json.loads(Path(existing['evidence']['manifest_path']).read_text())
        if m['consistency_id']!=quiet['consistency_id']:raise ValueError('PRE quiet point drift')
        evidence={**payload,**quiet,'assertions':assertions,'census':boundary.census,'redis15_current_cardinality':cardinality,
            'pre_manifest_sha256':existing['evidence']['manifest_sha256'],'snapshot_hwm':m['ledger_snapshot'],
            'original_creation_status':'unreceipted_parent_failed','observed_source_status':'verified','capacity':boundary.capacity()}
        receipt=Receipt(operation,'done',evidence)
    except Exception as exc:
        receipt=Receipt(operation,'failed',{'reason':'source_observation_failed','error_class':type(exc).__name__})
        boundary.ledger.finish(receipt)
        durable_file(PRIVATE/'evidence'/('b11-source-observation-'+current_operation()+'.json'),encoded(asdict(receipt)))
        raise
    boundary.ledger.finish(receipt)
    durable_file(PRIVATE/'evidence'/('b11-source-observation-'+current_operation()+'.json'),encoded(asdict(receipt)))
    return asdict(receipt)
