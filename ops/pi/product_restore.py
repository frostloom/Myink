"""Owned, network-none PostgreSQL recovery. Never restores original control state.

This proves database import and material recovery; application cold-start and
business probes remain independent release requirements, recorded explicitly.
"""
from hashlib import sha256
import gzip
import os
from pathlib import Path, PurePosixPath
import tarfile
import time
import uuid

from . import backup
from .audit import _path, _plain, digest, encoded, require, strict_json
from .contracts import Receipt
from .product_commands import DockerCommandError
from .product_backup import META_SQL, _copy

LABEL='myink.pi.restore.operation'


def materialize_archive(source,target,*,maximum_bytes):
    source=_path(source);_plain(source);target=_path(target)
    require(type(maximum_bytes) is int and 0<maximum_bytes<=536870912,'bounded recovery materials required')
    members=[];seen=set();total=0
    with tarfile.open(source,mode='r:') as stream:
        for entry in stream:
            path=PurePosixPath(entry.name)
            require(entry.name and not path.is_absolute() and '..' not in path.parts and path.parts and not any('\\' in v or any(ord(c)<32 for c in v) for v in path.parts),'unsafe material path')
            name=path.as_posix();require(name not in seen and (entry.isfile() or entry.isdir()) and len(members)<20000,'unsafe material member')
            require(not any(parent.as_posix() in seen and parent.as_posix() not in {m.name.rstrip('/') for m in members if m.isdir()} for parent in path.parents if parent.as_posix()!='.'),'material parent is not directory')
            seen.add(name);total+=entry.size if entry.isfile() else 0
            require(entry.size>=0 and total<=maximum_bytes,'material expansion exceeds limit');members.append(entry)
        target.mkdir(mode=0o700)
        hashes={}
        for entry in members:
            relative=PurePosixPath(entry.name);destination=target.joinpath(*relative.parts)
            destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            if entry.isdir():destination.mkdir(mode=0o700,exist_ok=True);continue
            fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);hashed=sha256();remaining=entry.size
            with stream.extractfile(entry) as incoming,os.fdopen(fd,'wb') as outgoing:
                while remaining:
                    block=incoming.read(min(remaining,65536));require(bool(block),'truncated material member')
                    outgoing.write(block);hashed.update(block);remaining-=len(block)
                outgoing.flush();os.fsync(outgoing.fileno())
            hashes[relative.as_posix()]=hashed.hexdigest()
    return dict(files=len(hashes),bytes=total,content_sha256=digest(hashes))


class OwnedPostgresRestore:
    def __init__(self,backend):
        self.backend=backend;self.host=backend.host;self.plan=backend.plan;self.ledger=self.host.ledger
        if self.host.config['mode']=='ACTUAL':
            from .product_runtime import LinuxProductHost
            require(type(self.host) is LinuxProductHost,'canonical native recovery host required')
        self.cid=None;self.registry=None;self.attempt=None

    def _run(self,args,**kwargs):return self.host._run(args,**kwargs)
    def _json(self,args):return strict_json(self.host._bytes(self._run(args)))

    def _owned(self):
        require(self.cid is not None and self.registry is not None,'owned recovery registry required')
        # Cleanup is permitted after the product lease expires, but only for
        # this exact registry. It cannot stop, remove or import into a product.
        result=self.host.commands.run(['inspect',self.cid],timeout=15)
        values=strict_json(self.host._bytes(result));require(isinstance(values,list) and len(values)==1,'complete owned target inspect required');info=values[0]
        require(info['Id']==self.cid and self.cid not in {v['id'] for v in self.plan['legacy']['containers']} and info['Image']==self.registry['image_id'],'foreign recovery container')
        require(info['Config']['Labels'].get(LABEL)==self.plan['operation_id'] and info['Config']['Labels'].get('myink.pi.restore.attempt')==self.registry['attempt_uuid'],'recovery labels drift')
        c=info['HostConfig'];require(c['NetworkMode']=='none' and c['ReadonlyRootfs'] is True and not c.get('Binds') and not c.get('PortBindings') and not c.get('Privileged') and not c.get('ExtraHosts'),'recovery isolation drift')
        require(all(m['Type']=='tmpfs' for m in info['Mounts']) and not info['NetworkSettings'].get('Ports'),'recovery mounts or ports drift')
        require(c['Memory']==1073741824 and c['MemorySwap']==1073741824 and c['PidsLimit']==128 and set(c.get('Tmpfs',{}))=={'/var/lib/postgresql/data','/var/run/postgresql','/tmp'},'recovery resource drift')
        return info

    def _sql(self,query=None,stdin_path=None):
        self._owned();args=['exec']+(['-i'] if stdin_path is not None else [])+[self.cid,'psql','-X','-q','-A','-t','-w','-U',self.admin,'-d','myink','-v','ON_ERROR_STOP=1']
        if query is not None:args+=['-c',query]
        return self._run(args,seconds=600,stdin_path=stdin_path)

    def _prepare(self,receipt,manifest,directory):
        operation=str(uuid.uuid5(uuid.UUID(self.plan['operation_id']),receipt.evidence['backup_id']))
        case=str(uuid.uuid5(uuid.UUID(operation),'positive'+str(directory)))
        self.attempt='restore-check:attempt:'+case
        require(self.ledger.get(self.attempt) is None,'existing recovery intent cannot be redispatched')
        backup.start_rehearsal_attempt(self.ledger,receipt,operation,context=self.backend.context)
        target_operation='restore-target:'+case
        image=next(v['image_id'] for v in self.plan['legacy']['containers'] if v['service']=='postgres')
        self.registry=dict(target_operation=target_operation,attempt_uuid=operation,image_id=image)
        self.folder=self.backend.root/('restore-'+operation);self.folder.mkdir(mode=0o700)
        self.admin='pi_restore_'+uuid.UUID(operation).hex
        self.ledger.intent(target_operation,'restore_target',dict(case_uuid=case,operation_id=operation,collection_id=receipt.evidence['backup_id'],fault='positive',image_id=image))
        name='myink-pi-restore-'+operation
        result=self._run(['create','--name',name,'--label',LABEL+'='+self.plan['operation_id'],'--label','myink.pi.restore.attempt='+operation,'--network','none','--read-only','--tmpfs','/var/lib/postgresql/data:rw,size=805306368','--tmpfs','/var/run/postgresql:rw,size=16777216','--tmpfs','/tmp:rw,size=16777216','--memory','1073741824','--memory-swap','1073741824','--cpus','0.5','--pids-limit','128','--env','POSTGRES_USER='+self.admin,'--env','POSTGRES_DB=myink','--env','POSTGRES_HOST_AUTH_METHOD=trust',image])
        self.cid=self.host._bytes(result).decode().strip();require(len(self.cid)==64 and all(c in '0123456789abcdef' for c in self.cid),'actual target creation ID required')
        self.registry.update(container_id=self.cid);backup.durable_file(self.folder/'registry.json',encoded(self.registry));self._owned()
        self.ledger.append_event('restore_target_created',dict(target_operation=target_operation,registry_sha256=backup.digest(self.folder/'registry.json'),container_id=self.cid))
        self._run(['start',self.cid]);until=time.monotonic()+40
        # Probe TCP: the entrypoint also starts a temporary Unix-only server.
        while True:
            info=self._owned();require(info['State']['Running'],'recovery PostgreSQL exited')
            try:
                self._run(['exec',self.cid,'pg_isready','-h','127.0.0.1','-U',self.admin,'-d','myink'],seconds=3)
                break
            except DockerCommandError as error:
                require(error.receipt['reason']=='nonzero_exit' and error.receipt['returncode'] in (1,2),'recovery readiness unconfirmed')
            require(time.monotonic()<until,'recovery startup deadline');time.sleep(.5)
        meta=strict_json(self.host._bytes(self._sql(META_SQL)))
        require(meta['database']=='myink' and not meta['tables'] and meta['system_identifier']!=manifest['source_id'],'target must be fresh and physically distinct')
        target=dict(target_operation=target_operation,container_id=self.cid,clean=True,system_identifier=meta['system_identifier'],source_system_identifier=manifest['source_id'])
        backup.bind_rehearsal_target(self.ledger,self.attempt,target)
        return target

    def restore(self,receipt,*,qualification="materials"):
        require(qualification in ("materials","application") and (self.host.config["mode"]!="ACTUAL" or qualification=="application"),"ACTUAL requires application recovery qualification")
        self.host.authorize(self.plan)
        phase=receipt.evidence.get('phase');require(phase in ('PRE','POST') and receipt.status=='done' and receipt.operation_id=='backup:'+self.plan['operation_id']+':'+phase,'exact completed paired backup required')
        if phase=='POST':
            release=self.ledger.get('release:'+self.plan['operation_id'])
            require(release and release['kind']=='release' and release['status']=='done' and release['payload']==dict(release_pair_id=self.plan['operation_id'],candidate=self.backend.pair['post_identity']),'original published candidate release required')
        captured=self.ledger.get(receipt.operation_id);require(captured and captured['status']=='done' and captured['evidence']==receipt.evidence,'original backup publication required')
        directory=_path(receipt.evidence['manifest_path']).parent
        require(directory.parent==self.backend.collections and directory.name==receipt.evidence['backup_id'],'original scoped recovery directory required')
        require(backup.digest(directory/'manifest.json')==receipt.evidence['manifest_sha256'],'recovery manifest drift')
        manifest=strict_json((directory/'manifest.json').read_bytes());backup.verify_artifacts(manifest,directory)
        require(manifest['release_pair_id']==self.plan['operation_id'] and manifest['phase']==phase and manifest['identity']==self.backend.pair[phase.lower()+'_identity'] and manifest['plan_hash']==digest(self.plan),'recovery identity drift')
        source=strict_json((directory/manifest['artifacts']['source_metadata']['path']).read_bytes())
        require(source['system_identifier']==manifest['source_id'] and source['size_bytes']<268435456,'recovery database exceeds owned capacity')
        target=None;result=None
        try:
            target=self._prepare(receipt,manifest,directory)
            # Reconstitute privately; neither snapshot is an import destination.
            materials={}
            for role in ('attachments','config','certificate'):
                item=manifest['artifacts'][role]
                materials[role]=materialize_archive(directory/item['path'],self.folder/role,maximum_bytes=self.backend.config['maximum_artifact_bytes'])
            for role in ('crypto','billing_snapshot','manager_snapshot'):
                _copy(directory/manifest['artifacts'][role]['path'],self.folder/role)
            plain=self.folder/'database.sql';fd=os.open(plain,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);total=0
            with gzip.open(directory/manifest['artifacts']['database']['path'],'rb') as incoming,os.fdopen(fd,'wb') as outgoing:
                for chunk in iter(lambda:incoming.read(65536),b''):
                    total+=len(chunk);require(total<=self.backend.config['maximum_artifact_bytes'],'expanded SQL exceeds recovery limit');outgoing.write(chunk)
                outgoing.flush();os.fsync(outgoing.fileno())
            roles=directory/manifest['artifacts']['roles']['path']
            self._sql(stdin_path=roles);self._sql(stdin_path=plain)
            observed=strict_json(self.host._bytes(self._sql(META_SQL)))
            restored_roles={k:v for k,v in observed['roles'].items() if k!=self.admin}
            require(observed['system_identifier']==target['system_identifier'] and observed['tables']==source['tables'] and observed['content']==source['content'] and restored_roles==source['roles'],'restored relation or role census differs')
            probes={}
            if qualification=='application':
                from .product_cold_probe import OwnedApplicationProbe
                for role in ('legacy','candidate'):probes[role]=OwnedApplicationProbe(self).check(role,target)
                require(strict_json(self.host._bytes(self._sql(META_SQL)))==observed,'application probe changed restored data')
            backup.verify_artifacts(manifest,directory)
            result=Receipt('restore:'+manifest['backup_id']+':'+target['system_identifier'],'done',dict(verified=True,target_system_identifier=target['system_identifier'],source_system_identifier=source['system_identifier'],table_count=len(source['tables']),materials=materials,original_control_state_restored=False,business_probe='restored_read_paths_verified' if probes else 'pending_separate_qualification',application_probes=probes))
        except Exception as error:
            if self.attempt and self.ledger.get(self.attempt):
                self.ledger.finish(Receipt(self.attempt,'uncertain',dict(reason='native_recovery_unconfirmed',error_class=type(error).__name__)))
            raise
        finally:
            if self.cid is not None:
                self._owned();self.host.commands.run(['rm','--force',self.cid],timeout=30)
                absent=self.host.commands.run(['ps','--all','--quiet','--no-trunc','--filter','label=myink.pi.restore.attempt='+self.registry['attempt_uuid']],timeout=15)
                require(not self.host._bytes(absent).strip(),'owned recovery cleanup unconfirmed')
                self.ledger.append_event('restore_target_removed',dict(target_operation=self.registry['target_operation'],container_id=self.cid))
        require(result is not None,'recovery result missing')
        result=Receipt(result.operation_id,'done',dict(result.evidence,cleanup_confirmed=True))
        backup.record_restore(self.ledger,receipt,result,context=self.backend.context,now=self.host.clock(),attempt_operation=self.attempt)
        self.ledger.finish(Receipt(self.registry['target_operation'],'done',dict(container_id=self.cid,cleanup_confirmed=True)))
        return result
