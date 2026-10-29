"""Bounded private Docker transport for trusted product host adapters only.

No model tool or authorization is provided here. A command's successful exit is
an execution receipt; its business meaning is verified by the owning adapter.
"""
from datetime import datetime, timezone
from hashlib import sha256
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import time
import uuid

from .audit import _path, _plain, encoded, require

MAX_OUTPUT = 512 * 1024 * 1024
STDERR_LIMIT = 65536


class DockerCommandError(RuntimeError):
    def __init__(self, receipt):
        self.receipt=receipt
        super().__init__('native product command: '+receipt['reason'])


def _sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def _write(path, value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())
    _sync(path.parent)


class DockerCommands:
    def __init__(self, docker, endpoint, root):
        require(os.name=='posix','native product transport requires POSIX')
        self.docker=_path(docker);_plain(self.docker)
        require(os.access(self.docker,os.X_OK),'fixed Docker executable required')
        require(isinstance(endpoint,str) and re.fullmatch(r'unix:///[^\s?,#\x00]+',endpoint),'fixed local Docker endpoint required')
        self.endpoint=endpoint;self.root=_path(root)
        require(self.root.is_dir() and stat.S_IMODE(self.root.stat().st_mode)==0o700 and self.root.stat().st_uid==os.geteuid(),'private owned command root required')
        self.root_identity=(self.root.stat().st_dev,self.root.stat().st_ino)

    def run(self, args, *, command_id=None, timeout=30, output_limit=1048576, stdin_path=None):
        require(isinstance(args,(list,tuple)) and 0<len(args)<=128 and all(isinstance(v,str) and 0<len(v)<=8192 and '\0' not in v for v in args),'bounded fixed Docker arguments required')
        require(type(timeout) in (int,float) and math.isfinite(timeout) and 0<timeout<=600,'bounded command timeout required')
        require(type(output_limit) is int and 0<output_limit<=MAX_OUTPUT,'bounded command output required')
        deadline=time.monotonic()+timeout
        input_meta=None;input_identity=None
        if stdin_path is not None:
            stdin_path=_path(stdin_path);_plain(stdin_path)
            require(stdin_path.is_relative_to(self.root.parent) and stat.S_IMODE(stdin_path.stat().st_mode)==0o600 and stdin_path.stat().st_uid==os.geteuid(),'private operation input artifact required')
            info=stdin_path.stat();require(info.st_size<=MAX_OUTPUT,'bounded input artifact required')
            hashed=sha256()
            with stdin_path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(65536),b''):
                    require(time.monotonic()<deadline,'input verification deadline expired');hashed.update(chunk)
            input_meta=dict(path=stdin_path.relative_to(self.root.parent).as_posix(),bytes=info.st_size,sha256=hashed.hexdigest())
            input_identity=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
        identity=command_id if command_id is not None else str(uuid.uuid4())
        require(isinstance(identity,str) and str(uuid.UUID(identity))==identity,'canonical command identity required')
        require(_path(self.root)==self.root and (self.root.stat().st_dev,self.root.stat().st_ino)==self.root_identity and stat.S_IMODE(self.root.stat().st_mode)==0o700,'command root replaced')
        require(shutil.disk_usage(self.root).free>=output_limit+1048576,'insufficient private command capacity')
        folder=self.root/identity
        try:folder.mkdir(mode=0o700)
        except FileExistsError:raise DockerCommandError(dict(status='blocked',reason='existing_command_identity',command_id=identity)) from None
        _sync(self.root)
        argv=[str(self.docker),'--host',self.endpoint,*args]
        intent=dict(command_id=identity,argv=argv,timeout_seconds=timeout,output_limit=output_limit,started_at=datetime.now(timezone.utc).isoformat(),stdin=input_meta)
        require(len(encoded(intent))<=65536,'command intent exceeds bound')
        _write(folder/'intent.json',intent)  # Durable before spawning any process.
        counts={'stdout':0,'stderr':0};hashes={k:sha256() for k in counts};limits=dict(stdout=output_limit,stderr=STDERR_LIMIT)
        process=None;input_stream=None;reason=None;failure_class=None;completed=False;streams=selectors.DefaultSelector();files={}
        try:
            for name in counts:
                fd=os.open(folder/(name+'.bin'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                files[name]=os.fdopen(fd,'wb')
            if stdin_path is not None:
                fd=os.open(stdin_path,os.O_RDONLY|os.O_NOFOLLOW)
                input_stream=os.fdopen(fd,'rb');info=os.fstat(fd)
                require((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)==input_identity and info.st_nlink==1,'verified input artifact replaced')
            if time.monotonic()>=deadline:reason='deadline';raise TimeoutError()
            process=subprocess.Popen(argv,stdin=input_stream if input_stream is not None else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                start_new_session=True,env=dict(PATH='/usr/bin:/bin',HOME='/nonexistent',DOCKER_CONFIG='/nonexistent',LANG='C.UTF-8',PYTHONDONTWRITEBYTECODE='1'))
            for name,pipe in (('stdout',process.stdout),('stderr',process.stderr)):
                os.set_blocking(pipe.fileno(),False);streams.register(pipe,selectors.EVENT_READ,name)
            while streams.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0:reason='deadline';raise TimeoutError()
                for selected,_ in streams.select(min(remaining,.1)):
                    name=selected.data;data=os.read(selected.fileobj.fileno(),min(65536,limits[name]-counts[name]+1))
                    if not data:streams.unregister(selected.fileobj);continue
                    retained=data[:limits[name]-counts[name]];files[name].write(retained);hashes[name].update(retained);counts[name]+=len(retained)
                    if len(retained)!=len(data):reason='output_limit';raise ValueError('bounded native output exceeded')
            remaining=deadline-time.monotonic()
            if remaining<=0:reason='deadline';raise TimeoutError()
            try:code=process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:reason='deadline';raise
            if code!=0:reason='nonzero_exit'
            completed=reason is None
        except Exception as error:
            reason=reason or 'command_unconfirmed';failure_class=type(error).__name__
        finally:
            if process is not None:
                # Descendants can retain pipes after the direct CLI has exited.
                # This kills only the new CLI session, never Docker containers.
                if not completed:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                process.wait(timeout=5)
                process.stdout.close();process.stderr.close()
            streams.close()
            if input_stream is not None:input_stream.close()
            for stream in files.values():
                try:stream.flush();os.fsync(stream.fileno())
                finally:stream.close()
        result=dict(command_id=identity,status='done' if reason is None else 'uncertain',reason=reason or 'completed',
                    returncode=None if process is None else process.returncode,pid=None if process is None else process.pid,
                    intent_sha256=sha256(encoded(intent)).hexdigest(),completed_at=datetime.now(timezone.utc).isoformat(),
                    stdout=dict(path='stdout.bin',bytes=counts['stdout'],sha256=hashes['stdout'].hexdigest()),
                    stderr=dict(path='stderr.bin',bytes=counts['stderr'],sha256=hashes['stderr'].hexdigest()))
        if failure_class is not None:result['failure_class']=failure_class
        try:_write(folder/'receipt.json',result)
        except OSError:
            raise DockerCommandError(dict(result,status='uncertain',reason='receipt_persistence')) from None
        if reason is not None:raise DockerCommandError(result)
        return result
