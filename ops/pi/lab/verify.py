"""Trusted private-lab runtime checks; configuration receipts alone authorize nothing."""
import json
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

BASE = Path('/opt/myink-pi-lab')
DAEMON = '364e8400-3844-47e2-b86d-8b626332f61c'
HOST_KEYS = ('CgroupParent','ReadonlyRootfs','CapDrop','SecurityOpt','Dns','DnsOptions','Sysctls','Memory','MemorySwap','NanoCpus','PortBindings')


def _run(*args):
    executable={'docker':'/usr/bin/docker','systemctl':'/usr/bin/systemctl','iptables':'/usr/sbin/iptables'}[args[0]]
    return subprocess.check_output((executable,*args[1:]), text=True, timeout=10).strip()


def _docker(*args):
    return json.loads(_run('docker','--host','unix:///var/run/docker.sock',*args))


def _configuration(info):
    return {'id':info['Id'],'image':info['Image'],'user':info['Config']['User'],
            'host':{k:info['HostConfig'].get(k) for k in HOST_KEYS},
            'mounts':sorted([{k:m.get(k) for k in ('Type','Source','Destination','RW','Name')} for m in info['Mounts']],key=lambda m:m['Destination']),
            'networks':{k:v['IPAddress'] for k,v in info['NetworkSettings']['Networks'].items()}}


def freeze_runtime(identity):
    # Called only after trusted provisioning (or explicit root-verified adoption), never on preflight.
    names=identity['test_containers']+identity.get('maintenance_containers',[])+[identity['sandbox'],identity['gateway'],identity['project']+'-denied']
    frozen={'lab_uuid':identity['lab_uuid'],'containers':{n:_configuration(_docker('inspect',n)[0]) for n in names}}
    if identity.get('maintenance_snapshot'):
        frozen['maintenance_snapshot']=identity['maintenance_snapshot']
    (BASE/'runtime-manifest.json').write_text(json.dumps(frozen))
    (BASE/'runtime-manifest.json').chmod(0o600)


def verify_container(info, expected, lab_uuid, group):
    if (not info['State']['Running'] or info['State']['Pid']<=0
            or info['Config']['Labels'].get('myink.pi.lab')!=lab_uuid
            or info['HostConfig']['CgroupParent']!='myinkpi-'+group+'.slice'
            or _configuration(info)!=expected):
        actual=_configuration(info)
        fields=[k for k in expected if actual[k]!=expected[k]]
        raise ValueError('owned container configuration drift: '+info.get('Name','unknown')+' fields='+str(fields)+' required_group='+group+' actual_parent='+info['HostConfig']['CgroupParent']+' running='+str(info['State']['Running'])+' label_match='+str(info['Config']['Labels'].get('myink.pi.lab')==lab_uuid))
    cgroup=Path('/proc/'+str(info['State']['Pid'])+'/cgroup').read_text().strip()
    if '/myinkpi.slice/myinkpi-'+group+'.slice/' not in cgroup:
        raise ValueError('intended container PID outside required group')


def verify_firewall():
    expected=['-N MYINKPI_B7',
              '-A MYINKPI_B7 -s 172.29.220.10/32 -d 172.29.220.2/32 -p tcp -m tcp --dport 8765 -j RETURN',
              '-A MYINKPI_B7 -s 172.29.220.10/32 -j DROP','-A MYINKPI_B7 -j RETURN']
    if _run('iptables','-S','MYINKPI_B7').splitlines()!=expected:
        raise ValueError('candidate firewall policy drift')
    for chain,required in [('INPUT',['-A INPUT -i pi-lab-agent -j DROP']),
                           ('DOCKER-USER',['-A DOCKER-USER -i pi-lab-agent -j MYINKPI_B7',
                            '-A DOCKER-USER -i pi-lab-fixtures ! -o pi-lab-fixtures -j DROP'])]:
        rules=[r for r in _run('iptables','-S',chain).splitlines() if r.startswith('-A ')]
        if rules[:len(required)]!=required:
            raise ValueError('scoped firewall order or fixture deny drift')


def verify_runtime():
    from ops.pi.resources import sample_resources,verify_limits
    r=json.loads((BASE/'lab-env.json').read_text())
    daemon=_docker('info','--format','{{json .}}')
    if (daemon['ID']!=DAEMON or r['daemon_id']!=DAEMON or daemon['CgroupVersion']!='2'
            or daemon['CgroupDriver']!='systemd' or daemon['DockerRootDir']!='/var/lib/docker'):
        raise ValueError('private daemon drift')
    for group in ('agent','heavy'):
        proof=sample_resources(group)
        if not verify_limits(proof,group): raise ValueError('kernel proof missing')
        r[group+'_proof']=proof
    infra=sample_resources('infra')
    if (infra.get('memory.max')!=str(768*1024**2) or infra.get('memory.swap.max')!='0'
            or infra.get('cpu.max')!='100000 100000'
            or not infra.get('membership_verified') or not infra.get('ancestor_verified')):
        raise ValueError('infra parent accounting drift')
    r['infra_proof']=infra
    r['kernel_proof']=r['heavy_proof']
    manifest=BASE/'runtime-manifest.json'
    if manifest.is_symlink() or manifest.stat().st_uid!=0 or manifest.stat().st_mode & 0o022:
        raise ValueError('untrusted frozen configuration')
    frozen=json.loads(manifest.read_text())
    names=r['test_containers']+r.get('maintenance_containers',[])+[r['sandbox'],r['gateway'],r['project']+'-denied']
    if frozen['lab_uuid']!=r['lab_uuid'] or set(frozen['containers'])!=set(names):
        raise ValueError('foreign frozen resources')
    for name in names:
        group='agent' if name==r['sandbox'] else 'heavy' if name in r['test_containers'] else 'infra'
        verify_container(_docker('inspect',name)[0],frozen['containers'][name],r['lab_uuid'],group)
    for suffix,internal,bridge in [('agent',True,'pi-lab-agent'),('fixtures',False,'pi-lab-fixtures')]:
        net=_docker('network','inspect',r['project']+'-'+suffix)[0]
        if (net['Labels'].get('myink.pi.lab')!=r['lab_uuid'] or net['Internal']!=internal
                or net['EnableIPv6'] or net['Options'].get('com.docker.network.bridge.name')!=bridge):
            raise ValueError('owned network drift')
    candidate=frozen['containers'][r['sandbox']]
    if (candidate['user']!='65534:65534' or not candidate['host']['ReadonlyRootfs']
            or candidate['host']['CapDrop']!=['ALL'] or 'no-new-privileges' not in candidate['host']['SecurityOpt']
            or candidate['host']['Dns']!=['127.0.0.1']
            or candidate['networks']!={r['project']+'-agent':'172.29.220.10'}):
        raise ValueError('sandbox isolation configuration missing')
    for name in r.get('maintenance_containers', []):
        info = _docker('inspect', name)[0]
        if info['Config']['Labels'].get('myink.pi.owner') != 'maintenance-infra':
            raise ValueError('maintenance owner missing')
        if name.endswith('-entry'):
            if (info['HostConfig']['CapAdd'] != ['CAP_NET_BIND_SERVICE'] or info['HostConfig']['CapDrop'] != ['ALL']
                    or info['Config']['User'] != '65534:65534' or not info['HostConfig']['ReadonlyRootfs']
                    or 'no-new-privileges' not in info['HostConfig']['SecurityOpt']
                    or list(info['NetworkSettings']['Networks']) != [r['project']+'-maintenance']):
                raise ValueError('stable maintenance entry policy drift')
        if info['HostConfig']['Memory'] <= 0 or info['HostConfig']['MemorySwap'] != info['HostConfig']['Memory']:
            raise ValueError('maintenance resource accounting missing')
    if r.get('maintenance_containers'):
        snapshot=r.get('maintenance_snapshot')
        if not snapshot or frozen.get('maintenance_snapshot')!=snapshot:
            raise ValueError('maintenance snapshot identity missing or drifted')
        for filename,digest in snapshot['sha256'].items():
            if filename not in ('maintenance.Caddyfile','maintenance.html') or hashlib.sha256((BASE/'maintenance'/filename).read_bytes()).hexdigest()!=digest:
                raise ValueError('maintenance snapshot content drift')
        net = _docker('network','inspect',r['project']+'-maintenance')[0]
        if (net['Labels'].get('myink.pi.lab') != r['lab_uuid'] or net['EnableIPv6']
                or net['Options'].get('com.docker.network.bridge.name') != 'pi-lab-maint'):
            raise ValueError('maintenance network drift')
        rules = _run('iptables','-S','DOCKER-USER').splitlines()
        if '-A DOCKER-USER -i pi-lab-maint ! -o pi-lab-maint -j DROP' not in rules:
            raise ValueError('maintenance egress deny missing')
    verify_firewall()
    return r


def _sealed_source():
    source=BASE/'trusted-source'
    module=Path(__file__).resolve()
    return module.is_relative_to(source) and module.stat().st_uid==0 and Path.cwd()==source


def verify_test_environment():
    # A caller-supplied JSON file is not proof; only this fixed root-owned runtime and active unit count.
    if sys.platform!='linux' or os.environ.get('PI_LAB_ENV')!=str(BASE/'lab-env.json') or not _sealed_source():
        raise ValueError('guarded native lab required')
    r=verify_runtime()
    owner=json.loads((BASE/'current-operation.json').read_text())
    operation=str(uuid.UUID(owner['operation_id']))
    unit='myinkpi-test-'+operation
    if (owner['unit']!=unit or owner['lab_uuid']!=r['lab_uuid'] or owner['group']!='heavy'
            or owner.get('status')!='active' or _run('systemctl','is-active',unit)!='active'):
        raise ValueError('stale or fabricated operation')
    group=_run('systemctl','show',unit,'--property=ControlGroup','--value')
    if not group.startswith('/myinkpi.slice/myinkpi-heavy.slice/') or group not in Path('/proc/self/cgroup').read_text():
        raise ValueError('test process outside owned active operation')
    environment={}
    for line in (BASE/'test.env').read_text().splitlines():
        key,value=shlex.split(line.removeprefix('export '))[0].split('=',1)
        environment[key]=value
    ports={}
    for name,port,key in [(r['project']+'-pg','5432/tcp','pg'),(r['project']+'-redis','6379/tcp','redis'),(r['project']+'-rabbit','5672/tcp','rabbit')]:
        bindings=_docker('inspect',name)[0]['NetworkSettings']['Ports'][port]
        if len(bindings)!=1 or bindings[0]['HostIp']!='127.0.0.1': raise ValueError('foreign fixture endpoint')
        ports[key]=int(bindings[0]['HostPort'])
    expected={'DATABASE_URL':f"postgresql+psycopg://postgres:synthetic-lab-only@127.0.0.1:{ports['pg']}/myink",
              'ADMIN_DATABASE_URL':f"postgresql+psycopg://postgres:synthetic-lab-only@127.0.0.1:{ports['pg']}/myink",
              'REDIS_URL':f"redis://127.0.0.1:{ports['redis']}/0",
              'AMQP_URL':f"amqp://myink:synthetic-lab-only@127.0.0.1:{ports['rabbit']}/",
              'QUEUE_PREFIX':'-pi-'+r['lab_uuid']+'-','JWT_SECRET':'synthetic-b7-jwt-secret-at-least-32-bytes','EMBED_ENABLED':'0'}
    if environment!=expected:
        raise ValueError('original sealed fixture configuration drift')
    if os.environ.get('B11_SOURCE_DESCRIPTOR'):
        if os.environ['B11_SOURCE_DESCRIPTOR']!=str(BASE/'b11-source.json'):raise ValueError('foreign B11 descriptor')
        from ops.pi.lab.backup_lab import verify_source
        expected=verify_source(r,expected,operation)
    if os.environ.get('B10_CENSUS_DESCRIPTOR'):
        descriptor=BASE/('b10-census-'+operation+'.json')
        if (os.environ['B10_CENSUS_DESCRIPTOR']!=str(descriptor) or descriptor.is_symlink()
                or descriptor.stat().st_uid!=0 or descriptor.stat().st_mode & 0o077):
            raise ValueError('untrusted B10 census descriptor')
        proof=json.loads(descriptor.read_text())
        creation=proof.get('ancestor_id',operation)
        if creation!=operation:
            if creation!=B10_PARENT or proof['selection'] not in B10_RECHECKS:raise ValueError('foreign retained B10 ancestry')
            _b10_parent_evidence()
            if any(hashlib.sha256((BASE/'trusted-source'/name).read_bytes()).hexdigest()!=digest for name,digest in proof['source_hashes'].items()):raise ValueError('retained B10 source drift')
        database='myink_b10_'+uuid.UUID(creation).hex
        prefix='-pi-'+r['lab_uuid']+'-b10-'+creation+'-'
        if (proof['operation_id']!=operation or proof['lab_uuid']!=r['lab_uuid'] or proof['ports']!=ports
                or proof['database']!=database or proof['prefix']!=prefix
                or proof['selection'] not in ('b10-census','b10-defer','b10-fresh',*B10_RECHECKS)
                or proof['redis_db']!={'b10-census':12,'b10-defer':13,'b10-fresh':14,**{name:14 for name in B10_RECHECKS}}[proof['selection']]):
            raise ValueError('foreign B10 census identity')
        expected={**expected,'DATABASE_URL':expected['DATABASE_URL'].rsplit('/',1)[0]+'/'+database,
                  'ADMIN_DATABASE_URL':expected['ADMIN_DATABASE_URL'].rsplit('/',1)[0]+'/'+database,
                  'REDIS_URL':expected['REDIS_URL'].rsplit('/',1)[0]+'/'+str(proof['redis_db']),'QUEUE_PREFIX':prefix}
        import psycopg
        with psycopg.connect(expected['ADMIN_DATABASE_URL'].replace('postgresql+psycopg:','postgresql:')) as db:
            actual=db.execute('SELECT current_database(),system_identifier::text FROM pg_control_system()').fetchone()
            roles=db.execute("SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname IN ('postgres','myink') ORDER BY rolname").fetchall()
        if list(actual)!=[database,proof['system_identifier']] or [list(v) for v in roles]!=proof['roles']:
            raise ValueError('actual B10 PostgreSQL identity drift')
        import redis
        client=redis.Redis.from_url(expected['REDIS_URL'])
        if not client.ping():raise ValueError('B10 Redis partition unavailable')
    if any(os.environ.get(k)!=v for k,v in expected.items()):
        raise ValueError('foreign or inherited fixture environment')
    if "myink.config" in sys.modules:
        actual=sys.modules["myink.config"].settings
        fields=(("database_url","DATABASE_URL"),("admin_database_url","ADMIN_DATABASE_URL"),("redis_url","REDIS_URL"),("amqp_url","AMQP_URL"),("queue_prefix","QUEUE_PREFIX"))
        if any(getattr(actual,field)!=expected[key] for field,key in fields):
            raise ValueError("frozen business fixture settings drift")
    return r,expected


def _write_owner(owner):
    temporary=BASE/'.current-operation.tmp'
    temporary.write_text(json.dumps(owner))
    temporary.replace(BASE/'current-operation.json')


def cancel_owned(operation, lab_uuid):
    # Caller holds ownership.lock, also used by start and completion; never acquire the busy heavy lock.
    operation=str(uuid.UUID(operation))
    current=json.loads((BASE/'current-operation.json').read_text())
    identity=json.loads((BASE/'lab-env.json').read_text())
    unit='myinkpi-test-'+operation
    if (current.get('operation_id')!=operation or current.get('unit')!=unit
            or current.get('lab_uuid')!=lab_uuid or identity['lab_uuid']!=lab_uuid
            or current.get('status')!='active' or _run('systemctl','is-active',unit)!='active'):
        return {'status':'refused','reason':'stale_operation','operation_id':operation}
    group=_run('systemctl','show',unit,'--property=ControlGroup','--value')
    if not group.startswith('/myinkpi.slice/myinkpi-heavy.slice/'):
        return {'status':'refused','reason':'foreign_group','operation_id':operation}
    current['status']='cancelled'
    _write_owner(current)
    root=Path('/sys/fs/cgroup/myinkpi.slice/myinkpi-heavy.slice')
    (root/'cgroup.kill').write_text('1')
    import time
    for _ in range(30):
        pids=[p for f in root.rglob('cgroup.procs') for p in f.read_text().split()]
        if not pids: break
        time.sleep(.1)
    if pids: raise ValueError('heavy group not empty')
    return {'status':'done','operation_id':operation,'lab_uuid':lab_uuid,'heavy_empty':True,'cgroup_events':(root/'cgroup.events').read_text().strip()}


def run_b10_census(selection):
    """Fixed operation-derived partition on verified existing services, never reset history."""
    if selection not in ('b10-census','b10-fresh','b10-defer'):raise ValueError('unknown finite B10 selection')
    r,environment=verify_test_environment()
    if 'myink.config' in sys.modules:raise ValueError('B10 namespace must precede business import')
    operation=json.loads((BASE/'current-operation.json').read_text())['operation_id']
    database='myink_b10_'+uuid.UUID(operation).hex
    prefix='-pi-'+r['lab_uuid']+'-b10-'+operation+'-'
    import psycopg,redis
    from psycopg import sql
    partition={'b10-census':12,'b10-defer':13,'b10-fresh':14}[selection]
    client=redis.Redis.from_url(environment['REDIS_URL'].rsplit('/',1)[0]+'/'+str(partition))
    if client.dbsize()!=0:raise ValueError('B10 reserved Redis partition has preexisting data')
    with psycopg.connect(environment['ADMIN_DATABASE_URL'].replace('postgresql+psycopg:','postgresql:'),autocommit=True) as db:
        system=db.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
        roles=db.execute("SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname IN ('postgres','myink') ORDER BY rolname").fetchall()
        if not roles or not any(v==('postgres',True,True) for v in roles):raise ValueError('sealed PostgreSQL roles drift')
        if db.execute('SELECT 1 FROM pg_database WHERE datname=%s',(database,)).fetchone():raise ValueError('B10 fresh database already exists')
        db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    ports={kind:int(environment[key].split('127.0.0.1:')[1].split('/')[0]) for kind,key in [('pg','DATABASE_URL'),('redis','REDIS_URL'),('rabbit','AMQP_URL')]}
    descriptor=BASE/('b10-census-'+operation+'.json')
    proof=dict(operation_id=operation,lab_uuid=r['lab_uuid'],database=database,prefix=prefix,redis_db=partition,selection=selection,ports=ports,system_identifier=system,roles=roles)
    with descriptor.open('x') as stream:json.dump(proof,stream)
    descriptor.chmod(0o600)
    os.environ.update(B10_CENSUS_DESCRIPTOR=str(descriptor),DATABASE_URL=environment['DATABASE_URL'].rsplit('/',1)[0]+'/'+database,
        ADMIN_DATABASE_URL=environment['ADMIN_DATABASE_URL'].rsplit('/',1)[0]+'/'+database,
        REDIS_URL=environment['REDIS_URL'].rsplit('/',1)[0]+'/'+str(partition),QUEUE_PREFIX=prefix)
    verify_test_environment()
    subprocess.run([sys.executable,'-m','myink.cli','init','--seed'],check=True,timeout=150)
    verify_test_environment()
    commands=[[sys.executable,'-m','pytest','tests/test_maintenance_reconciliation.py','-q','-k','actual_fresh_census','--tb=short']]
    if selection=='b10-defer':commands.append([sys.executable,'-m','pytest','tests/test_queue_handoff.py','-q','-k','real_successive_defer','--tb=short'])
    if selection=='b10-fresh':commands.append([sys.executable,'-m','pytest','tests/test_queue_handoff.py','tests/test_maintenance_reconciliation.py','tests/test_worker.py','tests/test_enqueue_gates.py','tests/test_multiprocess.py','-q','-k','not actual_fresh_census','--tb=short'])
    for command in commands:subprocess.run(command,check=True,timeout=400)


B10_PARENT='ed2c61e6-d33b-4951-9d9a-fb05d06633e5'
B10_RECHECKS={'b10-review-lane':('tests/test_queue_handoff.py','-k','review_original_active'), 'b10-review':('tests/test_queue_handoff.py','tests/test_maintenance_reconciliation.py','-k','review_'), 'b10-role-diagnostic':('tests/test_maintenance_reconciliation.py','-k','trusted_adapter_uses_actual_application_role'),
    'b10-retained-queue':('tests/test_queue_handoff.py','tests/test_maintenance_reconciliation.py','-k','not actual_fresh_census'),
    'b10-retained-worker':('tests/test_worker.py',), 'b10-retained-gates':('tests/test_enqueue_gates.py',),
    'b10-retained-multiprocess':('tests/test_multiprocess.py',)}


def _b10_parent_evidence():
    evidence=Path('/mnt/e/tools/myink-pi/evidence')
    hashes={B10_PARENT+'.receipt.json':'4473d639eb3d707cff07be1bf8dcb979b4e4b76fe77865f42a967f4eabeac3ed',
        'b10-fresh-final-source.json':'19ca69e5b955c1001cf517b9ad2fccc6c8ffdd2534f51527eb531a73cc822888',
        'b10-census-'+B10_PARENT+'.json':'b10da7e68fe123dfcbf8343fb4a0919ad55514d8aff26401901beeef0690d7b9'}
    for name,digest in hashes.items():
        if hashlib.sha256((evidence/name).read_bytes()).hexdigest()!=digest:raise ValueError('retained B10 creation evidence drift')
    receipt=json.loads((evidence/(B10_PARENT+'.receipt.json')).read_text())
    if receipt['operation_id']!=B10_PARENT or receipt['status']!='failed':raise ValueError('retained failed B10 provenance absent')
    return json.loads((evidence/'b10-fresh-final-source.json').read_text())


def run_b10_retained(selection):
    """Finite failed-dataset diagnostics; retained unknowns never become admission proof."""
    if selection not in B10_RECHECKS:raise ValueError('unknown retained B10 selection')
    r,environment=verify_test_environment()
    if 'myink.config' in sys.modules:raise ValueError('retained B10 identity must precede imports')
    names=_b10_parent_evidence()
    original=BASE/('b10-census-'+B10_PARENT+'.json')
    if original.is_symlink() or original.stat().st_uid!=0 or original.stat().st_mode & 0o077:raise ValueError('untrusted original B10 descriptor')
    proof=json.loads(original.read_text())
    if proof['operation_id']!=B10_PARENT or proof['lab_uuid']!=r['lab_uuid'] or proof['selection']!='b10-fresh' or proof['redis_db']!=14:raise ValueError('foreign original B10 fixture')
    operation=json.loads((BASE/'current-operation.json').read_text())['operation_id']
    proof.update(operation_id=operation,ancestor_id=B10_PARENT,selection=selection,
        source_hashes={name:hashlib.sha256((BASE/'trusted-source'/name).read_bytes()).hexdigest() for name in names})
    descriptor=BASE/('b10-census-'+operation+'.json')
    with descriptor.open('x') as stream:json.dump(proof,stream)
    descriptor.chmod(0o600)
    os.environ.update(B10_CENSUS_DESCRIPTOR=str(descriptor),DATABASE_URL=environment['DATABASE_URL'].rsplit('/',1)[0]+'/'+proof['database'],
        ADMIN_DATABASE_URL=environment['ADMIN_DATABASE_URL'].rsplit('/',1)[0]+'/'+proof['database'],
        REDIS_URL=environment['REDIS_URL'].rsplit('/',1)[0]+'/14',QUEUE_PREFIX=proof['prefix'])
    verify_test_environment()
    # Lossless private inventory includes original unknowns and every quota/lock/cache key.
    import psycopg,redis
    tables=('maintenance_control','admission_intents','queue_handoffs','tasks','maintenance_executions','task_budgets','task_budget_calls','checkpoints','checkpoint_writes')
    inventory={'operation_id':operation,'ancestor_id':B10_PARENT,'descriptor':proof,'tables':{}}
    with psycopg.connect(os.environ['ADMIN_DATABASE_URL'].replace('postgresql+psycopg:','postgresql:')) as db:
        for table in tables:inventory['tables'][table]=db.execute('SELECT * FROM '+table).fetchall()
    client=redis.Redis.from_url(os.environ['REDIS_URL'])
    inventory['redis']=[{'key_hex':key.hex(),'dump_hex':client.dump(key).hex(),'ttl_ms':client.pttl(key)} for key in client.scan_iter()]
    from myink.db import get_admin_engine
    from sqlalchemy.orm import Session
    from myink.worker.handoff import reconcile_queue,_queue_census
    from myink.maintenance import maintenance_view
    with Session(get_admin_engine()) as db:inventory['census']=reconcile_queue(db,maintenance_view(db)['epoch'])
    inventory['deliveries'],inventory['broker_unknown']=_queue_census()
    target=Path('/mnt/e/tools/myink-pi/evidence')/('b10-retained-'+operation+'.json')
    raw=json.dumps(inventory,default=lambda value:{'bytes_hex':value.hex()} if isinstance(value,bytes) else str(value)).encode()
    target.write_bytes(raw);target.with_suffix('.sha256').write_text(hashlib.sha256(raw).hexdigest())
    verify_test_environment()
    subprocess.run([sys.executable,'-m','pytest',*B10_RECHECKS[selection],'-q','--tb=short'],check=True,timeout=500)
