"""Trusted private-lab runtime checks; configuration receipts alone authorize nothing."""
import json
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
    names=identity['test_containers']+[identity['sandbox'],identity['gateway'],identity['project']+'-denied']
    frozen={'lab_uuid':identity['lab_uuid'],'containers':{n:_configuration(_docker('inspect',n)[0]) for n in names}}
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
    r['kernel_proof']=r['heavy_proof']
    manifest=BASE/'runtime-manifest.json'
    if manifest.is_symlink() or manifest.stat().st_uid!=0 or manifest.stat().st_mode & 0o022:
        raise ValueError('untrusted frozen configuration')
    frozen=json.loads(manifest.read_text())
    names=r['test_containers']+[r['sandbox'],r['gateway'],r['project']+'-denied']
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
    if environment!=expected or any(os.environ.get(k)!=v for k,v in expected.items()):
        raise ValueError('foreign or inherited fixture environment')
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
