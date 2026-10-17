"""Finite model-free protocol probe. Historical PG receipts are read-only attribution."""
import hashlib,json,os,shutil,sqlite3,stat,subprocess,sys,tarfile,time,uuid
import pytest
from pathlib import Path
from ops.pi.backup import digest,durable_file,encoded
from ops.pi.contracts import Receipt
from ops.pi.ledger import Ledger
from ops.pi.lab.backup_lab import PRIVATE,current_operation
from ops.pi.lab.verify import BASE,verify_test_environment
from ops.pi.resources import sample_resources

SPEC_SHA256='8bc8e4ceb6c7c0286d45d9a6093da501e3a8e5d9471746d47918fd94e9a3c365'
SPEC_NAME='b11-fix2-spec3.json'
SOURCE_FILES=('ops/pi/backup.py','ops/pi/lab/backup_lab.py','ops/pi/lab/backup_fresh.py','ops/pi/lab/backup_probe.py','ops/pi/lab/provision.sh','ops/pi/executor.py','ops/pi/tests/test_backup.py','ops/pi/tests/test_backup_lab.py','ops/pi/tests/test_executor.py')


def historical_binding(spec):
    ancestor=spec['historical_operation'];native=PRIVATE/'state'/('b11-fresh-'+ancestor+'.sqlite');controller=PRIVATE/'state/b11-executor-ledger.sqlite'
    if digest(native)!=spec['native_ledger_sha256'] or digest(controller)!=spec['controller_ledger_sha256']:raise ValueError('historical ledger drift')
    with sqlite3.connect('file:'+native.as_posix()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        restores=[dict(row) for row in db.execute("SELECT * FROM operations WHERE kind='restore_check' ORDER BY rowid")]
    with sqlite3.connect('file:'+controller.as_posix()+'?mode=ro',uri=True) as db:
        receipts=[json.loads(row[0]) for row in db.execute("SELECT payload FROM events WHERE kind='tool_receipt'") if json.loads(row[0]).get('operation_id') in [ancestor,spec['historical_gate_operation']]]
    if hashlib.sha256(encoded(restores)).hexdigest()!=spec['restore_rows_sha256'] or hashlib.sha256(encoded(receipts)).hexdigest()!=spec['controller_receipts_sha256']:raise ValueError('historical receipt drift')
    if len(restores)!=2 or any(row['status']!='done' or json.loads(row['evidence']).get('verified') is not True or len(json.loads(row['evidence'])['assertions'])!=12 for row in restores) or len(receipts)!=2 or any(row['status']!='done' for row in receipts):raise ValueError('historical actual proof missing')
    return {'scope':'historical_actual_PG_restore_only','native_ledger_sha256':digest(native),'controller_ledger_sha256':digest(controller),'restore_rows_sha256':spec['restore_rows_sha256'],'controller_receipts_sha256':spec['controller_receipts_sha256'],'actual_restores':2,'assertions_each':12,'new_actual_restores':0}



def protocol_workspace(operation):
    """Only a new fixed root-private native directory; never adopt an old probe."""
    operation=str(uuid.UUID(operation))
    root=BASE/('b11-protocol-'+operation)
    from ops.pi.backup import private_path
    private_path(BASE,root.name)
    root.mkdir(mode=0o700)
    if os.name=='posix' and (root.stat().st_uid!=0 or root.stat().st_mode&0o077):raise ValueError('native work directory not private')
    return root


def native_filesystem(spec):
    proof_path=PRIVATE/'evidence/b11-fix2-filesystem.json'
    if digest(proof_path)!=spec['filesystem_proof_sha256']:raise ValueError('filesystem ownership proof drift')
    proof=json.loads(proof_path.read_text())
    line=next(row for row in Path('/proc/self/mountinfo').read_text().splitlines() if row.split()[4]=='/')
    left,right=line.split(' - ',1);fields=right.split();actual={'major_minor':left.split()[2],'fs_type':fields[0],'source':fields[1]}
    trusted_base = proof['base_path'].lower().startswith('e:') or proof['base_path'].startswith('/Users/a1/项目/Myink/myink-pi')
    if proof['distribution']!='MyinkPiLab' or not trusted_base or actual!=proof['root_filesystem'] or actual['fs_type']!='ext4':raise ValueError('foreign native filesystem')
    return proof


def protocol_temporary_directory(nodeid):
    """Fixed child plugin only: no stock tmp_path aliases or adopted directories."""
    spec_path=PRIVATE/'evidence'/SPEC_NAME
    if digest(spec_path)!=SPEC_SHA256:raise ValueError('fixed probe spec drift')
    spec=json.loads(spec_path.read_text())
    if nodeid not in spec['tests']:raise ValueError('unknown protocol node')
    verify_test_environment();native_filesystem(spec)
    operation=str(uuid.UUID(current_operation()));work=BASE/('b11-protocol-'+operation)
    validate_protocol_entry(work,directory=True)
    if os.name=='posix' and work.stat().st_mode&0o077:raise ValueError('native work directory not private')
    fixtures=work/'fixtures'
    if not fixtures.exists():fixtures.mkdir(mode=0o700)
    validate_protocol_entry(fixtures,directory=True)
    if os.name=='posix' and fixtures.stat().st_mode&0o077:raise ValueError('native fixture directory not private')
    directory=fixtures/str(uuid.uuid5(uuid.UUID(operation),nodeid))
    directory.mkdir(mode=0o700)
    validate_protocol_entry(directory,directory=True)
    return directory


@pytest.fixture(name='tmp_path')
def protocol_tmp_path(request):
    return protocol_temporary_directory(request.node.nodeid)


def validate_protocol_entry(path,directory=False):
    info=path.lstat()
    if (path.is_symlink() or getattr(path,'is_junction',lambda:False)()
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or (not directory and info.st_nlink!=1) or (os.name=='posix' and info.st_uid!=0)):
        raise ValueError('unsafe protocol entry')
    return info


def retain_protocol_files(work,root,limit):
    validate_protocol_entry(work,directory=True);validate_protocol_entry(root,directory=True)
    inventory={};paths={};summaries={}
    for path in sorted(work.rglob('*')):
        relative=path.relative_to(work).as_posix()
        if relative.startswith('/') or '..' in relative.split('/'):raise ValueError('unsafe protocol member')
        directory=stat.S_ISDIR(path.lstat().st_mode);info=validate_protocol_entry(path,directory)
        inventory[relative]={'type':'directory' if directory else 'file','bytes':0 if directory else info.st_size,
            'sha256':None if directory else digest(path)};paths[relative]=path
        if not directory and path.name=='ledger.sqlite':
            with sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True) as db:
                rows=db.execute('SELECT operation_id,kind,status FROM operations ORDER BY rowid').fetchall()
                high=db.execute('SELECT coalesce(max(id),0),count(*) FROM events').fetchone()
            summaries[relative]={'operations':[{'operation_id':r[0],'kind':r[1],'status':r[2]} for r in rows],
                'event_high_water':high[0],'event_count':high[1],'sqlite_sha256':digest(path)}
    native_bytes=sum(row['bytes'] for row in inventory.values())
    existing=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    # Metadata, canonical ledger and final receipt allowance; never grow the estimate.
    if native_bytes*2+existing+len(inventory)*2048+256*1024>limit:raise ValueError('combined protocol footprint exceeds estimate')
    archive=root/'native-fixture.tar'
    with archive.open('xb') as stream:
        with tarfile.open(fileobj=stream,mode='w',format=tarfile.USTAR_FORMAT) as retained:
            for relative,path in paths.items():retained.add(path,arcname=relative,recursive=False)
        stream.flush();os.fsync(stream.fileno())
    archive.chmod(0o600)
    with tarfile.open(archive,mode='r') as retained:
        members=retained.getmembers()
        if len(members)!=len(inventory) or {m.name for m in members}!=set(inventory):raise ValueError('protocol archive member drift')
        for member in members:
            expected=inventory[member.name]
            if (member.isdir() if expected['type']=='directory' else member.isreg()) is not True or member.size!=expected['bytes']:raise ValueError('protocol archive type or size drift')
            if member.isreg():
                with retained.extractfile(member) as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
                if sha!=expected['sha256'] or digest(paths[member.name])!=sha:raise ValueError('protocol archive hash drift')
    durable_file(root/'native-copy-manifest.json',encoded(inventory))
    durable_file(root/'native-ledger-summaries.json',encoded(summaries))
    copied=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    if native_bytes+copied+256*1024>limit:raise ValueError('combined protocol footprint exceeds estimate')
    return {'native_root':str(work),'native_bytes':native_bytes,'archive_bytes':archive.stat().st_size,
        'archive_sha256':digest(archive),'inventory_sha256':digest(root/'native-copy-manifest.json'),
        'ledger_summaries_sha256':digest(root/'native-ledger-summaries.json'),'member_count':len(inventory),
        'combined_bytes_with_metadata_allowance':native_bytes+copied+256*1024,'verified_without_extraction':True}

def runtime_binding(runtime):
    """Compare every strict-runtime field except six known live observations."""
    observed={'cpu.stat','memory.current','memory.peak','pids','sample_attempts','vanished_pids'}
    bound=dict(runtime)
    for name in ('heavy_proof','infra_proof','agent_proof','kernel_proof'):
        proof=runtime[name]
        if not isinstance(proof,dict):raise ValueError('runtime proof shape drift')
        bound[name]={key:value for key,value in proof.items() if key not in observed}
    return bound


def run_protocol_probe():
    spec_path=PRIVATE/'evidence'/SPEC_NAME
    if digest(spec_path)!=SPEC_SHA256:raise ValueError('fixed probe spec drift')
    spec=json.loads(spec_path.read_text());started=time.monotonic();operation=current_operation()
    frozen=json.loads((PRIVATE/'evidence/b11-fix2-source.json').read_text())
    if set(frozen)!=set(SOURCE_FILES):raise ValueError('fixed source inventory mismatch')
    for name,sha in frozen.items():
        path=BASE/'trusted-source'/name
        if digest(path)!=sha or path.stat().st_uid!=0 or b'\r\n' in path.read_bytes():raise ValueError('native frozen source drift')
    runtime,_=verify_test_environment();historical=historical_binding(spec);filesystem=native_filesystem(spec)
    before={group:sample_resources(group) for group in ('heavy','infra','agent')}
    capacity={name:shutil.disk_usage(name)._asdict() for name in ('/mnt/e','/')}
    if min(row['free'] for row in capacity.values())<spec['new_peak_bytes']+spec['reserve_bytes']:raise ValueError('probe capacity insufficient')
    root=PRIVATE/'evidence'/('b11-fix2-'+operation);root.mkdir(mode=0o700)
    path=PRIVATE/'state'/('b11-fix2-'+operation+'.sqlite')
    if path.exists():raise ValueError('probe ledger already owned')
    work=protocol_workspace(operation)
    ledger=Ledger(path);action='protocol-probe:'+operation
    ledger.intent(action,'synthetic_protocol_probe',{'scope':spec['scope'],'spec_sha256':SPEC_SHA256,'source_sha256':digest(PRIVATE/'evidence/b11-fix2-source.json'),'historical_source_binding':historical})
    status='failed';evidence={'scope':spec['scope'],'historical_source_binding':historical,'capacity_before':capacity,'resources_before':before,'source_hashes':frozen,'filesystem_ownership':filesystem,'native_workspace':str(work),'runtime_before':runtime}
    try:
        (work/'tmp').mkdir();(work/'cache').mkdir()
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPYCACHEPREFIX':str(work/'cache/python'),'TEMP':str(work/'tmp'),'TMP':str(work/'tmp'),'PYTEST_ADDOPTS':'-o cache_dir='+str(work/'cache/pytest')+' --basetemp='+str(work/'tmp/tests')}
        command=[sys.executable,'-u','-B','-m','pytest','-p','ops.pi.lab.backup_probe',*spec['tests'],'-q','--tb=short']
        durable_file(root/'runner.json',encoded({'command':command,'env':{k:env[k] for k in ('PYTHONDONTWRITEBYTECODE','PYTHONPYCACHEPREFIX','TEMP','TMP','PYTEST_ADDOPTS')}}))
        with (root/'stdout.txt').open('xb',buffering=0) as stream:
            result=subprocess.run(command,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=max(1,75-(time.monotonic()-started)))
        (root/'stdout.txt').chmod(0o600)
        if result.returncode:raise ValueError('synthetic protocol regression failed')
        actual_bytes=sum(p.stat().st_size for p in work.rglob('*') if not p.is_symlink() and p.is_file())*2+sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        if actual_bytes>spec['new_peak_bytes']:raise ValueError('probe disk estimate exceeded')
        runtime_after,_=verify_test_environment();evidence['runtime_after']=runtime_after
        if runtime_binding(runtime_after)!=runtime_binding(runtime) or historical_binding(spec)!=historical:raise ValueError('source or historical proof changed')
        status='done';evidence.update(returncode=0,tests=len(spec['tests']),stdout_sha256=digest(root/'stdout.txt'),new_actual_restores=0,boundary_scope='target-preparation injection; synthetic artifact and restore callbacks',retained_bytes=actual_bytes)
    except Exception as exc:
        evidence.update(reason='protocol_probe_unconfirmed',error_class=type(exc).__name__)
        raise
    finally:
        retention_error=None
        try:evidence['retained_files']=retain_protocol_files(work,root,spec['new_peak_bytes'])
        except Exception as exc:
            retention_error=exc;status='failed';evidence.update(reason='protocol_retention_unconfirmed',retention_error_class=type(exc).__name__)
        if (root/'stdout.txt').exists():evidence['stdout_sha256']=digest(root/'stdout.txt')
        evidence.update(resources_after={group:sample_resources(group) for group in ('heavy','infra','agent')},capacity_after={name:shutil.disk_usage(name)._asdict() for name in ('/mnt/e','/')},elapsed=time.monotonic()-started)
        receipt=Receipt(action,status,evidence);ledger.finish(receipt);durable_file(root/'receipt.json',encoded({'operation_id':action,'status':status,'evidence':evidence}))
        if retention_error is not None:raise retention_error
    print(json.dumps({'operation_id':action,'status':status,'scope':spec['scope'],'receipt_path':str(root/'receipt.json')}))
    return evidence
