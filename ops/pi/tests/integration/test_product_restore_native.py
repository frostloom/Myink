"""Owned local PG restore with synthetic records; never application DSNs or ports."""
import importlib.util
import json
from pathlib import Path
import subprocess
import time
import uuid
import pytest
from test_product_backup import product_backup, bootstrap_case

pytestmark=pytest.mark.pi_followup_docker


@pytest.mark.parametrize('phase,fault',[('PRE',None),('PRE','changed-row'),('POST',None)])
def test_owned_native_collection_restore_preserves_source_and_removes_target(product_backup,phase,fault,monkeypatch):
    assert importlib.util.find_spec('ops.pi.product_restore'), 'missing native PostgreSQL restore'
    from ops.pi.product_restore import OwnedPostgresRestore
    from ops.pi.product_commands import DockerCommands
    from ops.pi.product_backup import LinuxProductBackup
    from ops.pi.backup import create_backup
    host,_,proofs,fee,_,quiet,_=product_backup
    docker=Path('/Users/a1/开发工具/bin/docker')
    if not docker.exists():docker=Path('/usr/bin/docker')
    docker=docker.resolve();nonce=str(uuid.uuid4());name='myink-pi-restore-source-'+nonce[:12]
    def run(*args):
        p=subprocess.run([str(docker),*args],capture_output=True,text=True,timeout=30,check=True)
        assert len(p.stdout.encode())<1048576;return p.stdout.strip()
    endpoint=json.loads(run('context','inspect','--format','{{json .Endpoints.docker.Host}}'))
    daemon=run('--host',endpoint,'info','--format','{{.ID}}')
    assert daemon!='0f90c176-9c45-4708-8103-37b5ff2464f1'
    image=json.loads(run('--host',endpoint,'image','inspect','pgvector/pgvector:pg16'))[0]['Id'];cid=None
    def sql(query):return run('--host',endpoint,'exec',cid,'psql','-X','-q','-A','-t','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',query)
    try:
        cid=run('--host',endpoint,'create','--name',name,'--label','myink.pi.restore-source='+nonce,'--network','none','--read-only','--tmpfs','/var/lib/postgresql/data:rw,size=268435456','--tmpfs','/var/run/postgresql:rw,size=16777216','--tmpfs','/tmp:rw,size=16777216','--memory','384m','--memory-swap','384m','--cpus','0.5','--pids-limit','96','--env','POSTGRES_USER=myink','--env','POSTGRES_DB=myink','--env','POSTGRES_HOST_AUTH_METHOD=trust',image)
        run('--host',endpoint,'start',cid);until=time.monotonic()+25
        while True:
            p=subprocess.run([str(docker),'--host',endpoint,'exec',cid,'pg_isready','-h','127.0.0.1','-U','myink','-d','myink'],capture_output=True,timeout=3)
            if p.returncode==0:break
            assert time.monotonic()<until;time.sleep(.2)
        sql("CREATE ROLE myink_app LOGIN;CREATE ROLE myink_report LOGIN;CREATE EXTENSION vector;CREATE TABLE tasks(id integer PRIMARY KEY,payload jsonb);CREATE TABLE agent_runs(id integer,detail json);INSERT INTO tasks VALUES(1,'{\"legacy\":true}');INSERT INTO agent_runs VALUES(1,'{}');")
        source=json.loads(sql("SELECT json_build_object('system_identifier',(SELECT system_identifier::text FROM pg_control_system()),'count',(SELECT count(*) FROM tasks))"))
        pg=next(r for r in host.plan['legacy']['containers'] if r['service']=='postgres');pg.update(id=cid,image_id=image)
        from ops.pi.audit import digest
        proofs['close_ingress']['plan_sha256']=digest(host.plan);quiet['plan_sha256']=digest(host.plan)
        host.commands=DockerCommands(docker,endpoint,host.root/'commands');oldrun=host._run
        def native(args,**kwargs):
            if args[0]=='exec' and args[1]==cid:
                return host.commands.run(args,timeout=kwargs.get('seconds',30),output_limit=kwargs.get('limit',1048576),stdin_path=kwargs.get('stdin_path'))
            if args[0]=='cp':return oldrun(args,**kwargs)
            return host.commands.run(args,timeout=kwargs.get('seconds',30),output_limit=kwargs.get('limit',1048576),stdin_path=kwargs.get('stdin_path'))
        host._run=native;host.config.update(daemon_id=daemon)
        host._json=lambda args:json.loads(host._bytes(host._run(args)))
        bridge=LinuxProductBackup(host,proofs)
        receipt=create_backup(host.ledger,'PRE',bridge.legacy,bridge,bridge.collections,pair=bridge.pair)
        assert receipt.status=='done',receipt
        if phase=='POST':
            from dataclasses import asdict
            from ops.pi.backup import record_recovery_references,mark_released
            pre_result=OwnedPostgresRestore(bridge).restore(receipt)
            assert pre_result.status=='done'
            refs=record_recovery_references(host.ledger,'native-source-references',version=1,context=bridge.context,complete=True,stable_ids=[receipt.evidence['backup_id']],referenced_ids=[])
            assert refs.status=='done'
            mark_released(host.ledger,bridge.pair['release_pair_id'],asdict(bridge.candidate),context=bridge.context,now=host.clock())
            sql("INSERT INTO tasks VALUES(2,'{\"after_release\":true}')")
            host.inspect_candidate=lambda plan:dict(plan['candidate'])
            host.measure_candidate_quiet=host.measure_quiet
            host.backup_container_id=lambda phase,role:('a'*64 if phase=='POST' and role=='api' else host._cid(role))
            receipt=create_backup(host.ledger,'POST',bridge.candidate,bridge,bridge.collections,pair=bridge.pair)
            assert receipt.status=='done',receipt
            manifest=json.loads(Path(receipt.evidence['manifest_path']).read_bytes())
            assert manifest['phase']=='POST' and manifest['identity']==asdict(bridge.candidate)
        if fault=='changed-row':
            original=OwnedPostgresRestore._sql
            def corrupt_after_import(self,query=None,stdin_path=None):
                result=original(self,query,stdin_path)
                if stdin_path is not None and stdin_path.name=='database.sql':
                    original(self,"UPDATE tasks SET payload='{\"changed\":true}'::jsonb")
                return result
            monkeypatch.setattr(OwnedPostgresRestore,'_sql',corrupt_after_import)
            with pytest.raises(ValueError):OwnedPostgresRestore(bridge).restore(receipt)
            assert sql('SELECT payload::text FROM tasks')=='{"legacy": true}'
            assert not run('--host',endpoint,'ps','-aq','--filter','label=myink.pi.restore.operation='+host.plan['operation_id'])
            return
        result=OwnedPostgresRestore(bridge).restore(receipt)
        assert result.status=='done',result
        assert result.evidence['target_system_identifier']!=source['system_identifier']
        assert result.evidence['table_count']==2
        assert result.evidence['cleanup_confirmed'] is True
        assert result.evidence['business_probe']=='pending_separate_qualification'
        assert sql('SELECT count(*) FROM tasks')==('2' if phase=='POST' else '1')
        assert all(fee.get('unknown-'+str(n))['status']=='pending' for n in range(9))
        assert not run('--host',endpoint,'ps','-aq','--filter','label=myink.pi.restore.operation='+host.plan['operation_id'])
        with pytest.raises(ValueError):OwnedPostgresRestore(bridge).restore(receipt)
    finally:
        if cid:
            actual=json.loads(run('--host',endpoint,'inspect',cid))[0]
            assert actual['Image']==image and actual['Config']['Labels'].get('myink.pi.restore-source')==nonce
            run('--host',endpoint,'rm','--force',cid)
