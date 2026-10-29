"""Application restore against owned PG; production and host DSNs are forbidden."""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
from pathlib import Path
import base64,importlib.util,io,json,subprocess,tarfile,time,uuid
from dataclasses import replace
import pytest
from test_product_backup import product_backup,bootstrap_case,write
pytestmark=pytest.mark.pi_followup_docker


@pytest.mark.parametrize('fault',[None,'wrong-key','missing-attachment','disabled-rls','missing-tls-key','cross-tenant-policy'])
def test_frozen_images_read_restored_business_data_without_models(product_backup,fault):
    assert importlib.util.find_spec('ops.pi.product_cold_probe'), 'missing restored application qualification'
    from ops.pi.product_commands import DockerCommands,DockerCommandError
    from ops.pi.product_backup import LinuxProductBackup
    from ops.pi.product_restore import OwnedPostgresRestore
    from ops.pi.backup import create_backup
    from ops.pi.audit import digest
    from myink.providers import credentials
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    host,c,proofs,fee,_,quiet,_=product_backup
    docker=Path('/Users/a1/开发工具/bin/docker')
    if not docker.exists():docker=Path('/usr/bin/docker')
    docker=docker.resolve();nonce=str(uuid.uuid4());cid=None;seed=None
    def run(*args):return subprocess.check_output([str(docker),*args],stderr=subprocess.PIPE,text=True,timeout=90).strip()
    endpoint=json.loads(run('context','inspect','--format','{{json .Endpoints.docker.Host}}'))
    assert run('--host',endpoint,'info','--format','{{.ID}}')!='0f90c176-9c45-4708-8103-37b5ff2464f1'
    def image(ref):return json.loads(run('--host',endpoint,'image','inspect',ref))[0]['Id']
    pgimage=image('pgvector/pgvector:pg16');legacy=image('myink-api:d25d8275');candidate=image('myink-api:pi-maintenance-rehearsal-8179')
    def sql(query):return run('--host',endpoint,'exec',cid,'psql','-X','-q','-A','-t','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',query)
    def pack(entries):
        raw=io.BytesIO()
        with tarfile.open(fileobj=raw,mode='w') as stream:
            for name,body in entries.items():
                entry=tarfile.TarInfo(name);entry.size=len(body);stream.addfile(entry,io.BytesIO(body))
        return raw.getvalue()
    key='synthetic-private-key';original=credentials.settings
    try:
        credentials.settings=replace(original,model_credential_key=key)
        encrypted=credentials.encrypt_api_key('synthetic-model-credential');mfa=credentials.encrypt_totp_secret('JBSWY3DPEHPK3PXP')
    finally:credentials.settings=original
    ids=[str(uuid.uuid4()) for _ in range(6)];pa,pb,ua,ub,task,feedback=ids
    attachment=b'\x89PNG\r\n\x1a\n'+b'synthetic-attachment'
    tlskey=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    cert=x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'synthetic.invalid')])).issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'synthetic.invalid')])).public_key(tlskey.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1)).not_valid_after(datetime.now(timezone.utc)+timedelta(days=7)).sign(tlskey,hashes.SHA256())
    certificate=pack({'data/caddy/certificates/synthetic.invalid/site.crt':cert.public_bytes(serialization.Encoding.PEM),'data/caddy/certificates/synthetic.invalid/site.key':tlskey.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())})
    if fault=='missing-tls-key':certificate=pack({'data/caddy/certificates/synthetic.invalid/site.crt':cert.public_bytes(serialization.Encoding.PEM)})
    try:
        cid=run('--host',endpoint,'create','--name','myink-pi-app-source-'+nonce[:12],'--label','myink.pi.app-source='+nonce,'--network','none','--read-only','--tmpfs','/var/lib/postgresql/data:rw,size=268435456','--tmpfs','/var/run/postgresql:rw,size=16777216','--tmpfs','/tmp:rw,size=16777216','--memory','384m','--memory-swap','384m','--pids-limit','96','--env','POSTGRES_USER=myink','--env','POSTGRES_DB=myink','--env','POSTGRES_HOST_AUTH_METHOD=trust',pgimage)
        run('--host',endpoint,'start',cid);until=time.monotonic()+25
        while True:
            try:
                run('--host',endpoint,'exec',cid,'pg_isready','-h','127.0.0.1','-U','myink','-d','myink');break
            except subprocess.CalledProcessError:assert time.monotonic()<until;time.sleep(.2)
        environment=json.dumps({'model_connections':[{'api_key_encrypted':encrypted}]})
        metadata=json.dumps([dict(stored='synthetic.png',bytes=len(attachment),mime='image/png')])
        sql(f"CREATE ROLE myink_app LOGIN NOSUPERUSER NOBYPASSRLS;CREATE ROLE myink_report LOGIN;CREATE TABLE users(id uuid,environment json,totp_secret text);CREATE TABLE projects(id uuid PRIMARY KEY,user_id uuid);CREATE TABLE tasks(id uuid PRIMARY KEY,project_id uuid,payload json,status text);CREATE TABLE agent_runs(id integer,detail json);CREATE TABLE chapters(id integer,project_id uuid,content text);CREATE TABLE feedback(id uuid,attachments json);INSERT INTO users VALUES('{ua}','{environment}','{mfa}');INSERT INTO projects VALUES('{pa}','{ua}'),('{pb}','{ub}');INSERT INTO tasks VALUES('{task}','{pa}','{{}}','done');INSERT INTO agent_runs VALUES(1,'{{}}');INSERT INTO chapters VALUES(1,'{pa}','first tenant'),(2,'{pb}','second tenant');INSERT INTO feedback VALUES('{feedback}','{metadata}');GRANT SELECT ON ALL TABLES IN SCHEMA public TO myink_app;ALTER TABLE chapters ENABLE ROW LEVEL SECURITY;ALTER TABLE chapters FORCE ROW LEVEL SECURITY;CREATE POLICY tenant_isolation ON chapters USING(project_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;ALTER TABLE tasks FORCE ROW LEVEL SECURITY;CREATE POLICY tenant_isolation ON tasks USING(project_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);")
        if fault=='disabled-rls':sql('ALTER TABLE chapters DISABLE ROW LEVEL SECURITY')
        if fault=='cross-tenant-policy':sql('ALTER POLICY tenant_isolation ON tasks USING(true)')
        # Real LangGraph checkpoint and pending writes, created inside the owned
        # PG network namespace. No host port, provider or original state.
        seedscript="""import psycopg
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.base import empty_checkpoint
with psycopg.connect('postgresql://myink@127.0.0.1/myink',autocommit=True,row_factory=dict_row) as db:
 saver=PostgresSaver(db);saver.setup();cp=empty_checkpoint();cp['channel_values']={'state':{'draft':'synthetic checkpoint'}};cp['channel_versions']={'state':'1'}
 config=saver.put({'configurable':{'thread_id':THREAD,'checkpoint_ns':''}},cp,{'source':'update','step':1,'parents':{}},{'state':'1'})
 saver.put_writes(config,[('state',{'draft':'synthetic pending write'})],'persist-next')
""".replace('THREAD',repr(task))
        seed=run('--host',endpoint,'create','--name','myink-pi-app-seed-'+nonce[:12],'--label','myink.pi.app-seed='+nonce,'--network','container:'+cid,'--read-only','--tmpfs','/tmp:rw,size=33554432','--memory','512m','--memory-swap','512m','--pids-limit','64',candidate,'python','-B','-c',seedscript)
        run('--host',endpoint,'start','--attach',seed)
        seeded=json.loads(run('--host',endpoint,'inspect',seed))[0];assert seeded['State']['ExitCode']==0
        run('--host',endpoint,'rm',seed);seed=None
        pg=next(v for v in host.plan['legacy']['containers'] if v['service']=='postgres');pg.update(id=cid,image_id=pgimage)
        for row in host.plan['legacy']['containers']:
            if row['service'] in ('api','worker'):row['image_id']=legacy
        host.plan['legacy']['source_commit']='d25d82752d4821ae701f3ed7ebbffea01b4b63f7';host.plan['candidate']['image_ids']['python']=candidate
        pin=digest(host.plan);proofs['close_ingress']['plan_sha256']=pin;quiet['plan_sha256']=pin
        # Only the expected app source comes from Git. Actual imported packages
        # in both images must match before any data-level query.
        repo=Path(__file__).resolve().parents[4]
        for role,commit in [('legacy',host.plan['legacy']['source_commit']),('candidate','HEAD')]:
            names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'src/myink'],cwd=repo).decode().splitlines()
            files={name:sha256(subprocess.check_output(['git','show',commit+':'+name],cwd=repo)).hexdigest() for name in names if name.endswith('.py')}
            manifest=host.root/(role+'-manifest.json');manifest_pin=write(manifest,dict(source_commit=host.plan[role]['source_commit'] if role=='legacy' else host.plan['candidate']['commit_sha'],files=files))
            host.config.update({role+'_manifest_path':str(manifest),role+'_manifest_sha256':manifest_pin})
        if fault=='wrong-key':
            c['environment_sha256']=write(Path(c['environment_path']),b'MODEL_CREDENTIAL_KEY=wrong-key\n')
            host.config['backup_sha256']=write(Path(host.config['backup_path']),c)
        host.commands=DockerCommands(docker,endpoint,host.root/'commands');oldrun=host._run
        def native(args,**kw):
            if args[0]=='cp' and args[-1]=='-' and ':/' in args[1] and not args[1].endswith('/app/src'):
                data=certificate if '/data/feedback' not in args[1] else pack({} if fault=='missing-attachment' else {'feedback/'+feedback+'/synthetic.png':attachment})
                command=str(uuid.uuid4());folder=host.root/'commands'/command;folder.mkdir(mode=0o700);write(folder/'stdout.bin',data)
                return dict(command_id=command,status='done',returncode=0,stdout=dict(bytes=len(data),sha256=sha256(data).hexdigest()),stderr=dict(bytes=0))
            return host.commands.run(args,timeout=kw.get('seconds',90),output_limit=kw.get('limit',1048576),stdin_path=kw.get('stdin_path'))
        host._run=native;host._json=lambda args:json.loads(host._bytes(host._run(args)))
        bridge=LinuxProductBackup(host,proofs);receipt=create_backup(host.ledger,'PRE',bridge.legacy,bridge,bridge.collections,pair=bridge.pair)
        assert receipt.status=='done',receipt
        if fault:
            with pytest.raises((ValueError,DockerCommandError)):OwnedPostgresRestore(bridge).restore(receipt,qualification='application')
        else:
            result=OwnedPostgresRestore(bridge).restore(receipt,qualification='application')
            assert result.status=='done'
            assert set(result.evidence['application_probes'])=={'legacy','candidate'}
            for value in result.evidence['application_probes'].values():
                assert value['api_health'] is True and value['credentials']==1 and value['mfa_secrets']==1
                assert value['attachments']==1 and value['tls_certificates']==1 and value['checkpoints']==1 and value['pending_writes']==1
                assert value['tenant_tables']>=2 and value['tenant_cases']==4 and value['model_requests']==0
            assert result.evidence['business_probe']=='restored_read_paths_verified'
        assert sql('SELECT count(*) FROM chapters')=='2'
        assert all(fee.get('unknown-'+str(n))['status']=='pending' for n in range(9))
        assert not run('--host',endpoint,'ps','-aq','--filter','label=myink.pi.restore.operation='+host.plan['operation_id'])
        assert not run('--host',endpoint,'ps','-aq','--filter','label=myink.pi.restore-probe.operation='+host.plan['operation_id'])
    finally:
        for resource,label,expected in [(seed,'myink.pi.app-seed',candidate),(cid,'myink.pi.app-source',pgimage)]:
            if resource:
                info=json.loads(run('--host',endpoint,'inspect',resource))[0]
                assert info['Image']==expected and info['Config']['Labels'].get(label)==nonce
                run('--host',endpoint,'rm','--force',resource)
