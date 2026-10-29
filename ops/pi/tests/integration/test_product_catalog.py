"""Explicit owned PostgreSQL catalog test; never uses an application DSN."""
import json
from pathlib import Path
import subprocess
import time
import uuid

import pytest

pytestmark=pytest.mark.pi_followup_docker


def test_provenance_catalog_matches_json_storage_without_rewriting_legacy_rows(tmp_path):
    from ops.pi.product_reality import METADATA_SQL
    docker=Path('/Users/a1/开发工具/bin/docker')
    if not docker.exists():docker=Path('/usr/bin/docker')
    docker=docker.resolve();owner=str(uuid.uuid4());name='myink-pi-catalog-'+owner[:12]
    def run(*args):
        p=subprocess.run([str(docker),*args],capture_output=True,text=True,timeout=30,check=True)
        assert len(p.stdout.encode())<1048576;return p.stdout
    endpoint=json.loads(run('context','inspect','--format','{{json .Endpoints.docker.Host}}'));assert endpoint.startswith('unix:///')
    daemon=run('--host',endpoint,'info','--format','{{.ID}}').strip();assert daemon!='0f90c176-9c45-4708-8103-37b5ff2464f1'
    image=json.loads(run('--host',endpoint,'image','inspect','pgvector/pgvector:pg16'))[0]['Id'];cid=None
    format='{"id":{{json .Id}},"image":{{json .Image}},"labels":{{json .Config.Labels}}}'
    def owned():
        value=json.loads(run('--host',endpoint,'inspect','--format',format,cid or name));assert value['image']==image and value['labels'].get('myink.pi.catalog')==owner and (cid is None or value['id']==cid);return value
    def sql(query):return run('--host',endpoint,'exec',cid,'psql','-X','-q','-A','-t','-U','catalog_test','-d','postgres','-v','ON_ERROR_STOP=1','-c',query).strip()
    try:
        cid=run('--host',endpoint,'create','--name',name,'--label','myink.pi.catalog='+owner,'--network','none','--read-only','--tmpfs','/var/lib/postgresql/data:rw,size=268435456','--tmpfs','/var/run/postgresql:rw,size=16777216','--tmpfs','/tmp:rw,size=16777216','--memory','384m','--memory-swap','384m','--cpus','0.5','--pids-limit','96','--env','POSTGRES_USER=catalog_test','--env','POSTGRES_HOST_AUTH_METHOD=trust',image).strip();assert len(cid)==64;owned()
        run('--host',endpoint,'start',cid);until=time.monotonic()+25
        while True:
            result=subprocess.run([str(docker),'--host',endpoint,'exec',cid,'pg_isready','-h','127.0.0.1','-U','catalog_test','-d','postgres'],capture_output=True,timeout=3)
            if result.returncode==0:break
            assert time.monotonic()<until;time.sleep(.2)
        sql("CREATE TABLE tasks(id integer,payload json);CREATE TABLE agent_runs(id integer,detail json);INSERT INTO tasks VALUES(1,'{}');INSERT INTO agent_runs VALUES(1,'{\"legacy\":true}');")
        before=sql('SELECT detail::text FROM agent_runs WHERE id=1')
        observed=json.loads(sql(METADATA_SQL))
        assert observed['task_provenance'] is True and observed['agent_run_provenance'] is True,'catalog must recognize actual JSON storage, not invented columns'
        assert sql('SELECT detail::text FROM agent_runs WHERE id=1')==before
        sql('ALTER TABLE agent_runs ALTER COLUMN detail TYPE text USING detail::text')
        assert json.loads(sql(METADATA_SQL))['agent_run_provenance'] is False
        sql('ALTER TABLE agent_runs ALTER COLUMN detail TYPE jsonb USING detail::jsonb')
        assert json.loads(sql(METADATA_SQL))['agent_run_provenance'] is True
    finally:
        if cid is not None:
            value=owned();run('--host',endpoint,'rm','--force',value['id'])
