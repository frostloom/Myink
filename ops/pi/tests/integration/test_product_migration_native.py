"""New candidate code installs only maintenance schema in an owned old database."""
import importlib.util
import json
from pathlib import Path
import subprocess
import time
import uuid
from hashlib import sha256
import pytest
from test_product_backup import product_backup, bootstrap_case

pytestmark=pytest.mark.pi_followup_docker


@pytest.mark.parametrize('fault',[None,'runtime-mismatch','foreign-owner'])
def test_native_schema_and_identity_keep_historical_rows_and_closed_admission(product_backup,fault):
    assert importlib.util.find_spec('ops.pi.product_migration'), 'missing fixed native migration adapter'
    from ops.pi.product_migration import NativeProductMigration
    from ops.pi.product_commands import DockerCommands
    from ops.pi.audit import digest
    host,_,proofs,_,_,quiet,_=product_backup
    docker=Path('/Users/a1/开发工具/bin/docker')
    if not docker.exists():docker=Path('/usr/bin/docker')
    docker=docker.resolve();owner=str(uuid.uuid4());cid=None
    def run(*args):
        p=subprocess.run([str(docker),*args],capture_output=True,text=True,timeout=30,check=True)
        assert len(p.stdout.encode())<1048576;return p.stdout.strip()
    endpoint=json.loads(run('context','inspect','--format','{{json .Endpoints.docker.Host}}'))
    assert run('--host',endpoint,'info','--format','{{.ID}}')!='0f90c176-9c45-4708-8103-37b5ff2464f1'
    pgimage=json.loads(run('--host',endpoint,'image','inspect','pgvector/pgvector:pg16'))[0]['Id']
    candidate=json.loads(run('--host',endpoint,'image','inspect','myink-api:pi-maintenance-rehearsal-8179'))[0]['Id']
    def sql(query):return run('--host',endpoint,'exec',cid,'psql','-X','-q','-A','-t','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',query)
    try:
        cid=run('--host',endpoint,'create','--name','myink-pi-migrate-source-'+owner[:12],'--label','myink.pi.migration-source='+owner,'--network','none','--read-only','--tmpfs','/var/lib/postgresql/data:rw,size=268435456','--tmpfs','/var/run/postgresql:rw,size=16777216','--tmpfs','/tmp:rw,size=16777216','--memory','384m','--memory-swap','384m','--cpus','0.5','--pids-limit','96','--env','POSTGRES_USER=myink','--env','POSTGRES_DB=myink','--env','POSTGRES_HOST_AUTH_METHOD=trust',pgimage)
        run('--host',endpoint,'start',cid);until=time.monotonic()+25
        while True:
            result=subprocess.run([str(docker),'--host',endpoint,'exec',cid,'pg_isready','-h','127.0.0.1','-U','myink','-d','myink'],capture_output=True,timeout=3)
            if result.returncode==0:break
            assert time.monotonic()<until;time.sleep(.2)
        sql("CREATE ROLE myink_app LOGIN;CREATE ROLE myink_report LOGIN;CREATE TABLE projects(id uuid PRIMARY KEY);CREATE TABLE tasks(id uuid PRIMARY KEY,project_id uuid,payload json,status text);CREATE TABLE agent_runs(id integer,detail json);INSERT INTO tasks VALUES('11111111-1111-4111-8111-111111111111',NULL,'{\"legacy\":true}','done');INSERT INTO agent_runs VALUES(1,'{\"old\":true}');")
        pg=next(r for r in host.plan['legacy']['containers'] if r['service']=='postgres');pg.update(id=cid,image_id=pgimage)
        host.plan['candidate']['image_ids']['python']=candidate
        proofpin=digest(host.plan);proofs['close_ingress']['plan_sha256']=proofpin;quiet['plan_sha256']=proofpin
        manifest={'source_commit':host.plan['candidate']['commit_sha'],'files':{}}
        source=Path(__file__).resolve().parents[4]/'src/myink'
        for f in source.rglob('*'):
            if f.is_file() and '__pycache__' not in f.parts and f.suffix not in ('.pyc','.pyo'):
                manifest['files']['src/myink/'+f.relative_to(source).as_posix()]=sha256(f.read_bytes()).hexdigest()
        mp=host.root/'candidate.json';mp.write_text(json.dumps(manifest));mp.chmod(0o600)
        host.config.update(candidate_manifest_path=str(mp),candidate_manifest_sha256=sha256(mp.read_bytes()).hexdigest())
        host.commands=DockerCommands(docker,endpoint,host.root/'commands')
        def native(args,**kw):
            args=list(args)
            if fault=='runtime-mismatch' and args[0]=='create':
                script_index=args.index('-c');args[script_index+2]='0'*64
            return host.commands.run(args,timeout=kw.get('seconds',30),output_limit=kw.get('limit',1048576),stdin_path=kw.get('stdin_path'))
        host._run=native
        host._json=lambda args:json.loads(host._bytes(host._run(args)))
        host.ledger.intent(host.plan['operation_id'],'product_bootstrap',dict(plan_sha256=proofpin))
        for action in ('install_schema','bind_identity'):
            host.ledger.intent(host.plan['operation_id']+':'+action,'product_bootstrap_step',dict(plan_sha256=proofpin,action=action))
        migration=NativeProductMigration(host)
        before=sql("SELECT json_build_object('task',(SELECT payload FROM tasks LIMIT 1),'run',(SELECT detail FROM agent_runs LIMIT 1))")
        if fault=='runtime-mismatch':
            from ops.pi.product_commands import DockerCommandError
            with pytest.raises((ValueError,DockerCommandError)):migration.install(host.plan,proofs)
            assert sql("SELECT to_regclass('public.maintenance_control') IS NULL")=='t'
            assert before==sql("SELECT json_build_object('task',(SELECT payload FROM tasks LIMIT 1),'run',(SELECT detail FROM agent_runs LIMIT 1))")
            assert not run('--host',endpoint,'ps','-aq','--filter','label=myink.pi.migration.operation='+host.plan['operation_id'])
            return
        result=migration.install(host.plan,proofs)
        assert result['historical_provenance_updated'] is False
        assert result['protocol']==dict(protocol=1,schema=1,state=1,effect_keys=1,serialization='jsonplus')
        if fault=='foreign-owner':
            from ops.pi.product_commands import DockerCommandError
            sql("UPDATE maintenance_control SET owner='manual-release',generation=9001,epoch='manual-epoch',deployment_id='manual-deployment'")
            with pytest.raises((ValueError,DockerCommandError)):migration.bind(host.plan,proofs)
            state=json.loads(sql('SELECT row_to_json(m) FROM maintenance_control m'))
            assert state['owner']=='manual-release' and state['generation']==9001 and state['epoch']=='manual-epoch'
            assert not run('--host',endpoint,'ps','-aq','--filter','label=myink.pi.migration.operation='+host.plan['operation_id'])
            return
        identity=migration.bind(host.plan,proofs)
        assert identity['identity']==host.plan['candidate']
        assert before==sql("SELECT json_build_object('task',(SELECT payload FROM tasks LIMIT 1),'run',(SELECT detail FROM agent_runs LIMIT 1))")
        state=json.loads(sql('SELECT row_to_json(m) FROM maintenance_control m'))
        assert state['admission_closed'] is True and state['consumer_blocked'] is True
        assert state['deployment_id']==host.plan['candidate']['deployment_id'] and state['generation']==host.plan['candidate']['generation']
        with pytest.raises(ValueError):migration.bind(host.plan,proofs)
        assert not run('--host',endpoint,'ps','-aq','--filter','label=myink.pi.migration.operation='+host.plan['operation_id'])
    finally:
        if cid:
            info=json.loads(run('--host',endpoint,'inspect',cid))[0]
            assert info['Image']==pgimage and info['Config']['Labels'].get('myink.pi.migration-source')==owner
            run('--host',endpoint,'rm','--force',cid)
