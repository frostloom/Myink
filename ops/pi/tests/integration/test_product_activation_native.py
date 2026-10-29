"""Owned real seven-service bootstrap and candidate/rollback cohort lifecycle."""
from datetime import datetime,timedelta,timezone
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import importlib.util,json,subprocess,tarfile,time,uuid
import pytest
from ops.pi.audit import digest
from ops.pi.contracts import Identity
from ops.pi.ledger import Ledger
from test_product_backup import write
pytestmark=pytest.mark.pi_followup_docker


@pytest.mark.parametrize('flow',['lifecycle','release','runtime','runtime-bad-report','runtime-writable-report','runtime-business','runtime-business-bad'])
def test_owned_full_stack_candidate_and_fresh_rollback_cohorts(tmp_path,flow):
    assert importlib.util.find_spec('ops.pi.product_activation'),'missing native cohort factory'
    from ops.pi.product_activation import NativeActivation,context_from_inspects,ACTIONS
    assert callable(getattr(NativeActivation,'create',None)), 'missing real cohort creation'
    from ops.pi.product_runtime import LinuxProductHost
    from ops.pi.product_bootstrap import prepare_bootstrap,STEPS
    docker=Path('/Users/a1/开发工具/bin/docker')
    if not docker.exists():docker=Path('/usr/bin/docker')
    docker=docker.resolve();op=str(uuid.uuid4());project='myink-pi-rehearsal-'+op;label='myink.pi.rehearsal='+op
    resources=[];network=None;volume=None;root=(tmp_path/'operation').resolve();root.mkdir(mode=0o700)
    def run(*args,body=None,seconds=120):
        p=subprocess.run([str(docker),*args],input=body,capture_output=True,timeout=seconds,check=True)
        assert len(p.stdout)<=67108864
        return p.stdout.decode().strip()
    endpoint=json.loads(run('context','inspect','--format','{{json .Endpoints.docker.Host}}'))
    def d(*args,**kw):return run('--host',endpoint,*args,**kw)
    daemon=d('info','--format','{{.ID}}');assert daemon!='0f90c176-9c45-4708-8103-37b5ff2464f1'
    def image(ref):return json.loads(d('image','inspect',ref))[0]['Id']
    images=dict(python=image('myink-api:d25d8275'),frontend=image('myink-caddy:a8a4361e'),postgres=image('pgvector/pgvector:pg16'),redis=image('redis:7-alpine'),rabbitmq=image('rabbitmq:3.13-management'))
    candidate=image('myink-api:pi-maintenance-rehearsal-8179');containers={};application=[]
    def create(role,alias,img,args=None,env=None,mounts=None,command=None):
        name=project+'-'+role+'-'+str(len(resources));argv=['create','--name',name,'--label',label,'--label','com.docker.compose.project='+project,'--label','com.docker.compose.service='+alias,'--network',network,'--network-alias',alias]
        for value in env or []:argv+=['--env',value]
        argv+=(args or [])+(mounts or [])+[img]+(command or [])
        cid=d(*argv);assert len(cid)==64;resources.append((cid,img));containers.setdefault(role,[]).append(cid);return cid
    def inspect(cid):return json.loads(d('inspect',cid))[0]
    def wait_ready(cid,cmd,seconds=60):
        until=time.monotonic()+seconds
        while True:
            v=inspect(cid);assert v['State']['Running'],v['State']
            try:return d('exec',cid,*cmd,seconds=10)
            except subprocess.CalledProcessError:
                assert time.monotonic()<until;time.sleep(.5)
    repo=Path(__file__).resolve().parents[4]
    def manifest(img,commit,path):
        probe=d('create','--label',label,'--network','none',img,'python','-c','pass');resources.append((probe,img))
        raw=subprocess.run([str(docker),'--host',endpoint,'cp',probe+':/app/src','-'],capture_output=True,check=True,timeout=30).stdout
        archive=root/(path+'.tar');archive.write_bytes(raw);files={}
        with tarfile.open(archive) as stream:
            for item in stream:
                if item.isfile() and '__pycache__' not in Path(item.name).parts and Path(item.name).suffix not in ('.pyc','.pyo'):files[item.name]=sha256(stream.extractfile(item).read()).hexdigest()
        d('rm',probe);resources.remove((probe,img))
        p=root/(path+'.json');pin=write(p,dict(source_commit=commit,files=files));return p,pin,files
    try:
        network=d('network','create','--internal','--label',label,project+'-fixtures')
        volume=d('volume','create','--label',label,project+'-feedback')
        pg=create('postgres','myink-pg',images['postgres'],args=['--read-only','--memory','384m','--memory-swap','384m','--pids-limit','96','--tmpfs','/var/lib/postgresql/data:rw,size=268435456','--tmpfs','/var/run/postgresql:rw,size=16777216','--tmpfs','/tmp:rw,size=16777216'],env=['POSTGRES_USER=myink','POSTGRES_DB=myink','POSTGRES_PASSWORD=synthetic-pg','MYINK_APP_PASSWORD=synthetic-app','MYINK_REPORT_PASSWORD=synthetic-report'])
        redis=create('redis','myink-redis',images['redis'],args=['--read-only','--memory','96m','--memory-swap','96m','--pids-limit','32','--tmpfs','/data:rw,size=16777216'],env=['REDIS_PASSWORD=synthetic-redis'],command=['redis-server','--requirepass','synthetic-redis','--save','','--appendonly','no'])
        rabbit=create('rabbitmq','myink-rabbitmq',images['rabbitmq'],args=['--memory','512m','--memory-swap','512m','--pids-limit','256'],env=['RABBITMQ_DEFAULT_USER=myink','RABBITMQ_DEFAULT_PASS=synthetic-rabbit','RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS=+S 2:2'])
        for cid in (pg,redis,rabbit):d('start',cid)
        wait_ready(pg,['pg_isready','-h','127.0.0.1','-U','myink','-d','myink'])
        wait_ready(redis,['redis-cli','--no-auth-warning','-a','synthetic-redis','ping'])
        wait_ready(rabbit,['gosu','rabbitmq','rabbitmq-diagnostics','-q','check_port_connectivity'],seconds=100)
        d('exec','-i',pg,'sh',body=(repo/'docker/initdb/01-roles.sh').read_bytes())
        common=['API_HOST=0.0.0.0','API_PORT=8100','APP_ENV=dev','SITE_ADDRESS=http://fixture.invalid','EMBED_ENABLED=0','JWT_SECRET=synthetic-jwt-at-least-thirty-two-bytes','MODEL_CREDENTIAL_KEY=synthetic-private-key','DATABASE_URL=postgresql+psycopg://myink_app:synthetic-app@myink-pg:5432/myink','REDIS_URL=redis://:synthetic-redis@myink-redis:6379/0','AMQP_URL=amqp://myink:synthetic-rabbit@myink-rabbitmq:5672/','WORKER_HEARTBEAT_INTERVAL=1']
        init=d('create','--label',label,'--network',network,'--memory','768m','--pids-limit','128',*[v for env in common for v in ('--env',env)],'--env','ADMIN_DATABASE_URL=postgresql+psycopg://myink:synthetic-pg@myink-pg:5432/myink',images['python'],'myink','init');resources.append((init,images['python']))
        d('start','--attach',init,seconds=180);assert inspect(init)['State']['ExitCode']==0
        d('rm',init);resources.remove((init,images['python']))
        d('exec',pg,'psql','-X','-q','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',"CREATE TABLE pi_native_release_marker(id integer PRIMARY KEY,value text);INSERT INTO pi_native_release_marker VALUES(1,'before-release')")
        business_ids=[str(uuid.uuid4()) for _ in range(4)]
        if flow in ('runtime-business','runtime-business-bad'):
            seed_program="""import uuid
from sqlalchemy.orm import Session
from myink.db import get_admin_engine
from myink.models import User,Project,Chapter
ids=IDS
with Session(get_admin_engine()) as db:
 db.add_all([User(id=uuid.UUID(ids[0]),username='probe_owner',daily_quota=2,concurrent_limit=1),User(id=uuid.UUID(ids[1]),username='probe_foreign',daily_quota=2,concurrent_limit=1)]);db.flush()
 db.add(Project(id=uuid.UUID(ids[2]),user_id=uuid.UUID(ids[0]),title='隔离探针项目'));db.flush()
 db.add(Chapter(id=uuid.UUID(ids[3]),project_id=uuid.UUID(ids[2]),chapter_seq=1,title='探针章节',content='本人可读的固定内容',summary=None,status='confirmed',version=1));db.commit()
""".replace('IDS',repr(business_ids))
            seed=d('create','--label',label,'--network',network,'--memory','512m','--pids-limit','128',*[v for env in common for v in ('--env',env)],'--env','ADMIN_DATABASE_URL=postgresql+psycopg://myink:synthetic-pg@myink-pg:5432/myink',images['python'],'python','-B','-c',seed_program);resources.append((seed,images['python']))
            d('start','--attach',seed);assert inspect(seed)['State']['ExitCode']==0;d('rm',seed);resources.remove((seed,images['python']))
        api=create('api','myink-api',images['python'],args=['--memory','512m','--memory-swap','512m','--cpus','1','--pids-limit','128'],env=common+['ADMIN_DATABASE_URL=postgresql+psycopg://myink_report:synthetic-report@myink-pg:5432/myink'],mounts=['--mount','type=volume,source='+volume+',target=/data/feedback'],command=['myink-api']);application.append(api)
        for n in range(2):application.append(create('worker','myink-worker',images['python'],args=['--memory','512m','--memory-swap','512m','--cpus','1','--pids-limit','128'],env=common,command=['myink-worker']))
        caddy_config=dict(admin={'listen':'localhost:2019'},apps={'http':{'servers':{'srv0':{'listen':[':80'],'routes':[{'handle':[{'handler':'reverse_proxy','upstreams':[{'dial':'myink-api:8100'}]}]}]}}}})
        tls_files=[]
        if flow in ('runtime-business','runtime-business-bad'):
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes,serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.x509.oid import NameOID
            key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'fixture.invalid')])
            certificate=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1)).not_valid_after(datetime.now(timezone.utc)+timedelta(days=7)).add_extension(x509.SubjectAlternativeName([x509.DNSName('fixture.invalid')]),critical=False).sign(key,hashes.SHA256())
            for filename,body in [('site.crt',certificate.public_bytes(serialization.Encoding.PEM)),('site.key',key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))]:
                file=root/filename;file.write_bytes(body);file.chmod(0o600);tls_files.append(file)
            caddy_config['apps']['tls']={'certificates':{'load_files':[{'certificate':'/data/caddy/certificates/fixture.invalid/site.crt','key':'/data/caddy/certificates/fixture.invalid/site.key'}]}}
            caddy_config['apps']['http']['servers']['tls']=dict(listen=[':443'],routes=caddy_config['apps']['http']['servers']['srv0']['routes'],tls_connection_policies=[{}],automatic_https={'disable':True})
        configfile=root/'caddy.json';configfile.write_text(json.dumps(caddy_config))
        front=create('frontend','myink-caddy',images['frontend'],args=['--memory','192m','--memory-swap','192m','--pids-limit','64'],command=['caddy','run','--config','/tmp/fixture.json'])
        d('cp',str(configfile),front+':/tmp/fixture.json')
        if tls_files:
            # Docker cp can populate the image-owned /data before startup.
            # Temporary command override is not used; copy a prepared owned tar
            # into /data so its final startup still uses the approved Caddy cmd.
            import io
            incoming=io.BytesIO()
            with tarfile.open(fileobj=incoming,mode='w') as archive:
                for file in tls_files:
                    entry=tarfile.TarInfo('caddy/certificates/fixture.invalid/'+file.name);entry.size=file.stat().st_size;entry.uid=entry.gid=10001;entry.mode=0o600;archive.addfile(entry,io.BytesIO(file.read_bytes()))
            d('cp','-',front+':/data',body=incoming.getvalue())
        for cid in [*application,front]:d('start',cid)
        wait_ready(front,['/usr/bin/curl','-fsS','http://myink-api:8100/readyz'],seconds=120)
        d('exec',api,'python','-B','-c',"from pathlib import Path;Path('/data/feedback/owned-fixture.txt').write_bytes(b'owned material survives release')")
        d('exec',redis,'redis-cli','--no-auth-warning','-a','synthetic-redis','SET','pi:restore:quota-sentinel','retained')
        # Warm source worker topology: five exact queues must exist before drain.
        until=time.monotonic()+60
        while True:
            names=d('exec',rabbit,'rabbitmqctl','list_queues','name','--quiet')
            if all(q in names for q in ('queue:tasks','queue:tasks:vip','queue:delay','queue:delay:vip','queue:dlq')):break
            assert time.monotonic()<until;time.sleep(.5)
        legacy_commit='d25d82752d4821ae701f3ed7ebbffea01b4b63f7';candidate_commit='efd26876dee6aa6ae8c5b8de94e4519a452ab5be'
        lp,lpin,files=manifest(images['python'],legacy_commit,'legacy');cp,cpin,_=manifest(candidate,candidate_commit,'candidate')
        legacy=dict(source_commit=legacy_commit,source_sha256=digest(files),containers=[dict(id=cid,service=role,image_id=images['python' if role in ('api','worker') else role]) for role,ids in containers.items() for cid in ids])
        cimages=dict(images,python=candidate);identity=asdict(Identity('candidate-'+op,1,'pi-'+op,cimages,commit_sha=candidate_commit,schema_id='maintenance-v1',config_hash='0'*64))
        plan=dict(schema='pi-product-bootstrap-v1',mode='SIMULATED',operation_id=op,legacy=legacy,candidate=identity,expires_at=(datetime.now(timezone.utc)+timedelta(minutes=25)).isoformat())
        settings=dict(mode='SIMULATED',target='rehearsal',project=project)
        ctx=context_from_inspects(plan,settings,[inspect(cid) for cid in application],json.loads(d('network','inspect',network))[0],json.loads(d('volume','inspect',volume)))
        plan['candidate']['config_hash']=ctx['configuration_sha256'];ctx['plan_sha256']=digest(plan)
        context_path=root/'activation-context.json';context_pin=write(context_path,ctx)
        a_path=root/'activation-approval.json';a_pin=write(a_path,dict(schema='pi-product-activation-approval-v2',mode='SIMULATED',target='rehearsal',plan_sha256=digest(plan),context_sha256=context_pin,approved_actions=list(ACTIONS),expires_at=plan['expires_at']))
        pp=root/'plan.json';ppin=write(pp,plan);approval=root/'bootstrap-approval.json';apin=write(approval,dict(schema='pi-product-release-approval-v1',mode='SIMULATED',target='rehearsal',authority='owned_rehearsal',plan_sha256=digest(plan),approved_actions=list(STEPS),expires_at=plan['expires_at']))
        compose=root/'compose';compose.mkdir(mode=0o700);env=compose/'.env';envpin=write(env,('MODEL_CREDENTIAL_KEY=synthetic-private-key\nJWT_SECRET=synthetic-jwt-at-least-thirty-two-bytes\nSITE_ADDRESS=http://fixture.invalid\n').encode());yaml=compose/'docker-compose.yml';ypin=write(yaml,b'services: {}\n')
        fee=Ledger(root/'original-fee.sqlite');manager=Ledger(root/'original-manager.sqlite');fee.path.chmod(0o600);manager.path.chmod(0o600)
        for n in range(9):fee.intent('unknown-'+str(n),'billing',dict(held_microyuan=2000000))
        backup_settings=dict(schema='pi-product-backup-v1',release_pair_id=op,environment_path=str(env),environment_sha256=envpin,compose_path=str(yaml),compose_sha256=ypin,billing_ledger_path=str(fee.path),manager_state_path=str(manager.path),maximum_artifact_bytes=16777216)
        if flow.startswith('runtime'):backup_settings.update(schema='pi-product-backup-v2',runtime_context_path=str(context_path),runtime_context_sha256=context_pin)
        bp=root/'backup.json';bpin=write(bp,backup_settings)
        lock=root/'maintenance.lock';lock.write_bytes(b'');lock.chmod(0o600)
        hp=root/'host.json';hpin=write(hp,dict(schema='pi-linux-product-host-v1',mode='SIMULATED',target='rehearsal',docker=str(docker),endpoint=endpoint,daemon_id=daemon,root=str(root),lock_path=str(lock),project=project,plan_path=str(pp),plan_sha256=ppin,approval_path=str(approval),approval_sha256=apin,legacy_manifest_path=str(lp),legacy_manifest_sha256=lpin,candidate_manifest_path=str(cp),candidate_manifest_sha256=cpin,backup_path=str(bp),backup_sha256=bpin,compose_dir=str(compose),drain_seconds=120,queue_prefix=''))
        h=LinuxProductHost(hp,hpin)
        if flow=='runtime-bad-report':d('exec',pg,'psql','-X','-q','-U','myink','-d','myink','-c',"ALTER ROLE myink_report PASSWORD 'different-source-report-password'")
        if flow=='runtime-writable-report':d('exec',pg,'psql','-X','-q','-U','myink','-d','myink','-c','ALTER ROLE myink_report SET default_transaction_read_only=off')
        prepared=prepare_bootstrap(h.ledger,plan,h)
        if flow in ('runtime-bad-report','runtime-writable-report'):
            assert prepared.status=='uncertain' and prepared.evidence['stopped_at']=='backup_pre',prepared
            expected='password authentication failed' if flow=='runtime-bad-report' else 'report role is not default read only'
            assert any(expected in p.read_text(errors='replace') for p in (root/'commands').glob('*/stderr.bin'))
            assert all(fee.get('unknown-'+str(n))['status']=='pending' for n in range(9))
            assert d('exec',front,'/usr/bin/curl','-sS','-o','/dev/null','-w','%{http_code}','http://127.0.0.1/api/v1/projects')=='503'
            return
        assert prepared.status=='done',prepared
        with h.lock(plan):
            if flow in ('release','runtime','runtime-business','runtime-business-bad'):
                from ops.pi.product_release import NativeProductRelease
                before=digest(json.loads((root/'ingress-before.json').read_bytes()))
                release_settings=dict(schema='pi-product-control-v1',mode='SIMULATED',target='rehearsal',plan_sha256=digest(plan),context_path=str(context_path),context_sha256=context_pin,activation_approval_path=str(a_path),activation_approval_sha256=a_pin,ingress_before_sha256=before,maximum_stopped_seconds=1800,expires_at=plan['expires_at'])
                if flow in ('runtime-business','runtime-business-bad'):
                    expected=dict(id=business_ids[3],chapter_seq=1,title='探针章节',status='confirmed',content='本人可读的固定内容',version=1,summary=None)
                    cases=dict(schema='pi-business-read-probe-v1',mode='SIMULATED',plan_sha256=digest(plan),context_sha256=context_pin,expires_at=plan['expires_at'],cases=[dict(user_id=business_ids[0],auth_version=1,foreign_user_id=business_ids[1],foreign_auth_version=1,project_id=business_ids[2],chapter_id=business_ids[3],expected_sha256='0'*64 if flow=='runtime-business-bad' else digest(expected))])
                    probe_path=root/'business-cases.json';probe_pin=write(probe_path,cases)
                    release_settings.update(schema='pi-product-control-v2',business_probe_path=str(probe_path),business_probe_sha256=probe_pin)
                settings_path=root/'control.json';settings_pin=write(settings_path,release_settings)
                permit=root/'control-approval.json';permit_pin=write(permit,dict(schema='pi-product-control-approval-v1',mode='SIMULATED',target='rehearsal',plan_sha256=digest(plan),config_sha256=settings_pin,approved_actions=['activate','rollback'],expires_at=plan['expires_at']))
                release=NativeProductRelease(h,settings_path,settings_pin,permit,permit_pin)
                alien=d('create','--label',label,'--network',network,'--network-alias','myink-api','--memory','64m','--pids-limit','32',images['python'],'python','-B','-c','import time;time.sleep(60)');resources.append((alien,images['python']))
                d('start',alien)
                with pytest.raises(ValueError,match='foreign network'):release._scope()
                alien_info=inspect(alien);assert alien_info['Config']['Labels'].get('myink.pi.rehearsal')==op and alien_info['Image']==images['python']
                d('rm','--force',alien);resources.remove((alien,images['python']))
                if flow=='runtime-business-bad':
                    with pytest.raises(Exception):release.activate()
                    assert any('business content differs' in p.read_text(errors='replace') for p in (root/'commands').glob('*/stderr.bin'))
                    assert h.ledger.get('backup:'+op+':POST') is None
                    assert h.ledger.get('native:'+op+':start_candidate_admission') is None
                    assert d('exec',front,'/usr/bin/curl','-sS','-o','/dev/null','-w','%{http_code}','http://127.0.0.1/api/v1/projects')=='503'
                    assert all(fee.get('unknown-'+str(n))['status']=='pending' for n in range(9));return
                opened=release.activate();assert opened.status=='done' and opened.evidence['phase']=='native_candidate_open'
                assert opened.evidence['business_probe']=='pending_separate_qualification'
                postdir=root/'collections'/sha256(('backup:'+op+':POST').encode()).hexdigest()
                with tarfile.open(postdir/'attachments.tar') as materials:assert materials.extractfile('feedback/owned-fixture.txt').read()==b'owned material survives release'
                assert json.loads(d('exec',front,'/usr/bin/curl','-fsS','http://127.0.0.1/api/v1/projects'))==[]
                ingress_pin=digest(h._caddy())
                d('exec',pg,'psql','-X','-q','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',"UPDATE maintenance_control SET owner='manual-owner' WHERE id=1")
                with pytest.raises(ValueError,match='superseded'):release._close()
                assert digest(h._caddy())==ingress_pin
                # Test-only owner restoration; production never rewinds manual ownership.
                d('exec',pg,'psql','-X','-q','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',"UPDATE maintenance_control SET owner='"+plan['candidate']['owner']+"' WHERE id=1")
                d('exec',pg,'psql','-X','-q','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',"INSERT INTO pi_native_release_marker VALUES(2,'after-open')")
                if flow=='runtime-business':
                    # Physical native return with a SIMULATED +8h authority
                    # clock, not actual elapsed observation or a production clock.
                    issued=datetime.now(timezone.utc)
                    lease=dict(schema='pi-product-rollback-lease-v1',mode='SIMULATED',target='rehearsal',authority='owned_rehearsal',plan_sha256=digest(plan),control_sha256=settings_pin,candidate=plan['candidate'],approved_action='rollback',issued_at=issued.isoformat(),expires_at=(issued+timedelta(hours=48)).isoformat(),maximum_stopped_seconds=release_settings['maximum_stopped_seconds'])
                    lease_path=root/'rollback-lease.json';lease_pin=write(lease_path,lease);h.use_rollback_lease(lease_path,lease_pin)
                    h.clock=lambda:datetime.now(timezone.utc)+timedelta(hours=8)
                    assert datetime.fromisoformat(plan['expires_at'])<h.clock()
                    with pytest.raises(ValueError,match='rollback-only'):release.activate()
                returned=release.rollback();assert returned.status=='done' and returned.evidence['phase']=='native_legacy_return'
                if flow=='runtime-business':
                    timer=json.loads((root/'native-control/rollback/start.json').read_bytes());assert timer['lease_sha256']==lease_pin and datetime.fromisoformat(timer['started_at'])>datetime.fromisoformat(plan['expires_at'])
                    assert h.ledger.get('product-control:'+op+':rollback')['status']=='done'
                assert returned.evidence['identity']['generation']==2 and returned.evidence['original_control_state_restored'] is False
                if flow in ('runtime','runtime-business'):
                    pre=next(root.glob('restore-*/application-legacy/receipt.json'))
                    proof_rows=[]
                    for folder in root.glob('restore-*'):
                        for role in ('legacy','candidate'):
                            proof=json.loads((folder/('application-'+role)/'receipt.json').read_bytes());assert proof['authenticated_roles']==proof['wrong_passwords_rejected']==2;proof_rows.append(proof)
                    assert len(proof_rows)==4
                    for proof in proof_rows:
                        main=proof['main_api'];assert main['main_process'] is True and main['api_health'] is True and main['natural_exit_code']==0 and main['anonymous_rejections']==1 and main['attachment_files']==1 and main['model_requests']==0
                        if flow=='runtime-business':assert main['owner_cases']==1
                        service=main['services'];assert service['ready'] is True and service['caddy_ready'] is True and service['worker_heartbeats']==2 and service['retained_redis_keys']==1 and service['tls_pinned'] is True
                        assert service['authentication']['wrong_passwords_rejected']==2 and service['authentication']['empty_queues']==5 and service['worker_exit_codes']==[0,0] and len(service['worker_connections'])==2
                        assert all(v['wrong_database_password_rejected'] is True and v['application_role']=='myink_app' and v['read_only'] is True for v in service['worker_connections'])
                    assert not d('ps','-aq','--filter','label=myink.pi.restored-api.operation='+op)
                    assert not d('ps','-aq','--filter','label=myink.pi.restored-service.operation='+op)
                    assert not d('network','ls','--quiet','--filter','label=myink.pi.restore.operation='+op)
                    runtime_material=json.loads((postdir/'effective-runtime.json').read_bytes())
                    assert runtime_material['phase']=='POST' and all('DEPLOYMENT_GENERATION=1' in v['config']['Env'] for v in runtime_material['containers'])
                assert d('exec',pg,'psql','-X','-q','-A','-t','-U','myink','-d','myink','-c','SELECT count(*) FROM pi_native_release_marker')=='2'
                assert all(fee.get('unknown-'+str(n))['status']=='pending' for n in range(9))
                assert json.loads(d('exec',front,'/usr/bin/curl','-fsS','http://127.0.0.1/api/v1/projects'))==[]
                if flow=='runtime-business':
                    parent='product-control:'+op+':activate'
                    proof=h.ledger.get(parent+':business');assert proof['status']=='done' and proof['evidence']['cases']==1 and proof['evidence']['tenant_rejections']==2
                    assert all(h.ledger.get('native:'+op+':'+action)['status']=='done' for action in ('start_candidate','stop_candidate','start_candidate_admission','stop_candidate_admission'))
                    assert h.ledger.get(parent+':stop-validation')['status']=='done'
                with pytest.raises(ValueError):release.activate()
                return
            actor=NativeActivation(h,context_path,context_pin,a_path,a_pin)
            created=actor.create('candidate');assert len(created)==3
            for row in created:resources.append((row['id'],cimages['python']))
            assert h.inspect_candidate(plan)==plan['candidate']
            ready=actor.start('candidate');assert ready['verified'] is True
            assert all(v['provenance']['generation']==1 for v in ready['backends'])
            stopped=actor.stop('candidate');assert stopped['verified'] is True
            assert all(not inspect(row['id'])['State']['Running'] for row in created)
            assert all(fee.get('unknown-'+str(n))['status']=='pending' for n in range(9))
            # The fixed factory may prepare rollback containers, but does not
            # claim a business rollback or mutate the control row itself.
            rolled=actor.create('rollback');assert len(rolled)==3
            for row in rolled:resources.append((row['id'],images['python']))
            rollback=ctx['rollback_identity'];sql="UPDATE maintenance_control SET epoch='rollback-"+op+"',deployment_id='"+rollback['deployment_id']+"',generation="+str(rollback['generation'])+",owner='"+rollback['owner']+"',image_ids='"+json.dumps(rollback['image_ids'])+"'::json WHERE id=1"
            d('exec',pg,'psql','-X','-q','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',sql)
            returned=actor.start('rollback');assert returned['verified'] is True
            assert all(environment_record['identity']['generation']==2 for environment_record in returned['backends'])
            actor.stop('rollback')
            with pytest.raises(ValueError):actor.create('candidate')
            intents=list((root/'commands').glob('*/intent.json'));assert intents
            assert all(b'synthetic-private-key' not in p.read_bytes() for p in intents)
        assert d('exec',front,'/usr/bin/curl','-sS','-o','/dev/null','-w','%{http_code}','http://127.0.0.1/api/v1/projects')=='503'
    finally:
        # Include registered partial cohorts after assertion failures, by exact
        # operation label plus pinned image before removal; never product names.
        own=d('ps','-aq','--no-trunc','--filter','label='+label).splitlines()
        factory=d('ps','-aq','--no-trunc','--filter','label=myink.pi.release.operation='+op).splitlines()
        known=dict(resources)
        for cid in dict.fromkeys([*factory,*own]):
            v=inspect(cid);assert v['Config']['Labels'].get('myink.pi.rehearsal')==op or v['Config']['Labels'].get('myink.pi.release.operation')==op
            assert v['Image'] in set(images.values())|{candidate}
            if cid in known:assert v['Image']==known[cid]
            log=subprocess.run([str(docker),'--host',endpoint,'logs',cid],capture_output=True,timeout=20)
            target=root/(cid[:12]+'.log');target.write_bytes(log.stdout+log.stderr);target.chmod(0o600)
            statefile=root/(cid[:12]+'-state.json');statefile.write_text(json.dumps(v['State']));statefile.chmod(0o600)
            d('rm','--force',cid)
        if volume:
            v=json.loads(d('volume','inspect',volume))[0];assert v['Labels'].get('myink.pi.rehearsal')==op;d('volume','rm',volume)
        if network:
            n=json.loads(d('network','inspect',network))[0];assert n['Labels'].get('myink.pi.rehearsal')==op and not n['Containers'];d('network','rm',network)
