"""Trusted, local Docker containment acceptance with fixed synthetic canaries.

Not a Pi launcher, paid-run grant, or accepted_envelope. A shared daemon is
addressed explicitly; only exact operation-owned containers can be stopped.
"""
import argparse
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import select
import subprocess
import time
from urllib.parse import urlsplit
import uuid


KINDS = ('isolation', 'resources', 'timeout', 'overflow')
LABEL = 'myink.pi.operation'
PURPOSE = 'myink.pi.probe'


def _path(value):
    value = Path(value)
    if (not value.is_absolute() or '..' in value.parts or any(c in str(value) for c in ',\r\n\0')
            or any(p.is_symlink() for p in (value, *value.parents))):
        raise ValueError('absolute non-symlink probe path required')
    return value


def verify_isolation(data):
    checks = ('no_new_privileges','no_capabilities','positive_source_read','positive_tmp_write',
        'source_write_denied','harness_write_denied','foreign_files_denied',
        'foreign_native_aliases_denied','ledger_credentials_sessions_denied',
        'host_sockets_denied','network_denied','nested_network_denied')
    return (data.get('uid') == data.get('gid') == 65534
        and data.get('authenticated_mock') == 200 and data.get('wrong_token') == 403
        and all(data.get(k) is True for k in checks))


def verify_resources(data):
    numeric = ('memory_max','swap_max','pids_max','memory_peak','oom_kills_delta',
               'memory_child_returncode','throttled_delta','pids_peak','guest_available_before')
    return (all(type(data.get(k)) is int for k in numeric)
        and data['memory_max'] == 402653184 and data['swap_max'] == 0
        and data.get('cpu_max') == '50000 100000' and data['pids_max'] == 64
        and 0 < data['memory_peak'] <= 402653184 and data['oom_kills_delta'] > 0
        and data['memory_child_returncode'] == -9 and data['throttled_delta'] > 0
        and data.get('pids_denied') is True and 0 < data['pids_peak'] <= 64
        and data['guest_available_before'] >= 512*1024**2)


def verify_inspect(info):
    try:
        h = info['HostConfig']
        return (info['Config']['User'] == '65534:65534' and h['ReadonlyRootfs'] is True
            and h['NetworkMode'] == 'none' and h['Privileged'] is False
            and h['CapDrop'] == ['ALL'] and not h['CapAdd']
            and h['SecurityOpt'] == ['no-new-privileges=true']
            and h['PidMode'] == '' and h['CgroupnsMode'] == 'private'
            and h['Memory'] == h['MemorySwap'] == 402653184
            and h['NanoCpus'] == 500000000 and h['PidsLimit'] == 64
            and not h['Binds'] and not h['Devices'] and not h['VolumesFrom'] and not h['Links']
            and h['LogConfig']['Type'] == 'none'
            and len(h['Mounts']) == 2
            and all(m['Type'] == 'bind' and m['ReadOnly'] is True for m in h['Mounts']))
    except (KeyError, TypeError):
        return False


class ProbeHost:
    def __init__(self, *, docker, endpoint, daemon_id, image_id, operation_id):
        uri = urlsplit(endpoint)
        if (not Path(docker).is_absolute() or uri.scheme != 'unix' or uri.netloc
                or not uri.path.startswith('/') or '..' in Path(uri.path).parts
                or uri.query or uri.fragment or any(c.isspace() or c=='\0' for c in endpoint)
                or not isinstance(daemon_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',daemon_id)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id)
                or str(uuid.UUID(operation_id)) != operation_id):
            raise ValueError('explicit local daemon, immutable image and UUID required')
        self.command = [str(docker), '--host', endpoint]
        self.daemon_id, self.image_id, self.operation_id = daemon_id, image_id, operation_id
        self.owned = {}
        self.pending = {}

    def _call(self, *args, check=True, timeout=15):
        result = subprocess.run(self.command + list(args), capture_output=True, text=True, timeout=timeout)
        if check and result.returncode != 0:
            raise RuntimeError('probe Docker operation failed')
        return result

    def _daemon(self):
        if self._call('info','--format','{{.ID}}').stdout.strip() != self.daemon_id:
            raise RuntimeError('Docker daemon identity changed')

    def _inspect(self, ref):
        data = json.loads(self._call('inspect',ref).stdout)
        if not isinstance(data,list) or len(data)!=1:
            raise RuntimeError('ambiguous container identity')
        return data[0]

    def _check(self, info, name, mode):
        if (not re.fullmatch(r'[0-9a-f]{64}', info.get('Id',''))
                or info.get('Name') != '/' + name or info.get('Image') != self.image_id
                or info.get('Config',{}).get('Labels',{}).get(LABEL) != self.operation_id
                or info['Config']['Labels'].get(PURPOSE) != 'containment'
                or info['Config']['Labels'].get('myink.pi.mode') != mode):
            raise RuntimeError('foreign probe container identity')
        return info

    def inspect(self, cid):
        if cid not in self.owned:
            raise ValueError('unowned container reference')
        self._daemon()
        name, mode = self.owned[cid]
        info = self._check(self._inspect(cid), name, mode)
        if info['Id'] != cid:
            raise RuntimeError('container ID changed')
        return info

    def create(self, mode, *, worker, source, foreign, interactive=False):
        if type(interactive) is not bool:
            raise ValueError('explicit interactive flag required')
        if mode not in KINDS:
            raise ValueError('fixed probe mode required')
        worker, source, foreign = map(_path, (worker,source,foreign))
        if not worker.is_file() or not source.is_dir():
            raise ValueError('fixed worker and synthetic source required')
        self._daemon()
        if self._call('image','inspect',self.image_id,'--format','{{.Id}}').stdout.strip()!=self.image_id:
            raise RuntimeError('immutable cached image missing')
        name = f'myink-pi-probe-{self.operation_id}-{mode}'
        if mode in self.pending.values() or mode in [m for _,m in self.owned.values()]:
            raise ValueError('probe mode cannot restart')
        args = ['create','--name',name,'--label',LABEL+'='+self.operation_id,
            '--label',PURPOSE+'=containment','--label','myink.pi.mode='+mode,
            '--pull','never','--network','none','--user','65534:65534','--read-only',
            '--cap-drop','ALL','--security-opt','no-new-privileges=true','--cgroupns','private',
            '--memory','384m','--memory-swap','384m','--cpus','0.5','--pids-limit','64',
            '--log-driver','none','--workdir','/work',
            '--tmpfs','/work:rw,noexec,nosuid,nodev,size=16m,uid=65534,gid=65534,mode=0700',
            '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=8m,uid=65534,gid=65534,mode=0700',
            '--mount',f'type=bind,source={worker},target=/probe/worker.py,readonly',
            '--mount',f'type=bind,source={source},target=/source,readonly',
            '--env','PYTHONDONTWRITEBYTECODE=1','--env','HOME=/work',
            '--entrypoint','/usr/local/bin/python',self.image_id,'-I','-S','-u',
            '/probe/worker.py',mode,str(foreign)]
        if interactive: args.insert(1, '--interactive')
        self.pending[name] = mode
        try:
            cid = self._call(*args).stdout.strip()
            if not re.fullmatch(r'[0-9a-f]{64}',cid):
                raise RuntimeError('missing created container ID')
            # Record the exact ID before inspecting, so later failures still clean it.
            self.owned[cid] = (name,mode)
            self.inspect(cid)
            del self.pending[name]
            return cid
        except BaseException:
            # Keep uncertain names until a later reconciliation confirms ownership.
            self.reconcile()
            raise

    def reconcile(self):
        for name, mode in list(self.pending.items()):
            self._daemon()
            found = self._call('inspect', name, check=False)
            if found.returncode != 0:
                continue  # Absence now does not prove a timed-out create cannot finish later.
            data = json.loads(found.stdout)
            if not isinstance(data, list) or len(data) != 1:
                raise RuntimeError('ambiguous pending container identity')
            info = self._check(data[0], name, mode)
            self.owned[info['Id']] = (name, mode)
            del self.pending[name]

    def stop(self, cid):
        info = self.inspect(cid)
        if info['State']['Running']:
            # The container may finish after inspect and before kill. Authority is
            # the subsequent owned inspect, not Docker's already-stopped error.
            self._call('kill','--signal','KILL',cid,check=False)
        info = self.inspect(cid)
        if info['State']['Running'] or info['State']['Pid'] != 0:
            raise RuntimeError('owned PID namespace not stopped')
        return info

    def cleanup(self, cid):
        info = self.stop(cid)
        # Recheck ownership immediately before removal, never rm --force.
        self.inspect(cid)
        self._call('rm',cid)
        self._daemon()
        remaining = self._call('ps','-a','--no-trunc','--filter','label='+LABEL+'='+self.operation_id,
                               '--format','{{.ID}}').stdout.split()
        if cid in remaining:
            raise RuntimeError('owned container removal unconfirmed')
        del self.owned[cid]
        return dict(container_id=cid,stopped=True,removed=True,exit_code=info['State']['ExitCode'])

    def capture(self, cid, *, seconds, output_limit):
        if (type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<seconds<=30
                or type(output_limit) is not int or not 0<output_limit<=65536):
            raise ValueError('bounded probe I/O required')
        self.inspect(cid)
        started = time.monotonic()
        process = subprocess.Popen(self.command+['start','-a',cid], stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        data, observed_pids, reason = bytearray(), 0, 'completed'
        try:
            while True:
                remaining = seconds-(time.monotonic()-started)
                if remaining <= 0:
                    reason='timeout'; break
                ready,_,_=select.select([process.stdout],[],[],remaining)
                if not ready:
                    reason='timeout'; break
                chunk=os.read(process.stdout.fileno(),min(4096,output_limit-len(data)+1))
                if not chunk: break
                overflow=len(data)+len(chunk)>output_limit
                data.extend(chunk[:output_limit-len(data)])
                if not observed_pids and self.owned[cid][1] in ('timeout','overflow') and b'\n' in data:
                    remaining = seconds-(time.monotonic()-started)
                    if remaining <= 0:
                        reason='timeout'; break
                    try:
                        top=self._call('top',cid,'-eo','pid,ppid',timeout=remaining).stdout.splitlines()
                    except subprocess.TimeoutExpired:
                        reason='timeout'; break
                    observed_pids=max(0,len(top)-1)
                    if time.monotonic()-started >= seconds:
                        reason='timeout'; break
                if overflow:
                    reason='output_overflow'; break
            if reason=='completed':
                remaining = seconds-(time.monotonic()-started)
                try:
                    if remaining <= 0: reason='timeout'
                    elif process.wait(timeout=remaining)!=0: reason='process_failed'
                except subprocess.TimeoutExpired:
                    reason='timeout'
            if reason!='completed': self.stop(cid)
        finally:
            # Stop the namespace before cancelling its attach client. A broken
            # client or cancellation must not strand an owned detached child.
            try:
                if process.poll() is None: self.stop(cid)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=.5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=1)
                process.stdout.close()
        return dict(reason=reason,output=bytes(data),observed_pids=observed_pids,
                    elapsed=time.monotonic()-started)


def _write(path, data):
    with path.open('x',encoding='utf-8') as f:
        os.chmod(path,0o600)
        json.dump(data,f,sort_keys=True,indent=2,allow_nan=False)
        f.write('\n')


def run_probe(root, *, docker, endpoint, daemon_id, image_id):
    root=_path(root)
    if root.exists(): raise ValueError('new private evidence directory required')
    root.mkdir(mode=0o700)
    operation=str(uuid.uuid4())
    host=ProbeHost(docker=docker,endpoint=endpoint,daemon_id=daemon_id,image_id=image_id,operation_id=operation)
    source=root/'source'; source.mkdir(mode=0o755)
    (source/'canary').write_text('synthetic-source-canary\n'); (source/'canary').chmod(0o644)
    private=root/'private'; private.mkdir(mode=0o700)
    foreign=private/'host-canary'; foreign.write_text('synthetic-not-mounted\n')
    (source/'foreign-alias').symlink_to(foreign)
    worker=root/'worker.py'
    worker.write_bytes((Path(__file__).parent/'lab/container_probe_worker.py').read_bytes()); worker.chmod(0o644)
    result=dict(schema_version=1,operation_id=operation,daemon_id=daemon_id,image_id=image_id,
        worker_sha256=sha256(worker.read_bytes()).hexdigest(),
        controller_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        endpoint_sha256=sha256(endpoint.encode()).hexdigest(),mock_only=True,paid_requests=0,
        pi_runtime_verified=False,production_ready=False,automatic_execution=False,
        fixture_kind='fixed_python_canaries',status='blocked',cases=[],cleanup=[],failure_class=None)
    try:
        for mode in KINDS:
            row=dict(mode=mode,passed=False,configured=False)
            result['cases'].append(row)
            cid=host.create(mode,worker=worker,source=source,foreign=foreign)
            configured=verify_inspect(host.inspect(cid))
            row['configured']=configured
            if not configured: raise RuntimeError('probe hardening mismatch')
            capture=host.capture(cid,seconds=15 if mode=='resources' else 5 if mode=='isolation' else 2,
                                 output_limit=65536)
            raw=capture.pop('output')
            # Private bounded raw prefix preserves a failed attempt for diagnosis.
            (root/(mode+'.stdout')).write_bytes(raw)
            proof=json.loads(raw.split(b'\n',1)[0]) if mode in ('timeout','overflow') else json.loads(raw)
            row.update(proof=proof,output_sha256=sha256(raw).hexdigest(),output_bytes=len(raw),**capture)
            stopped=host.cleanup(cid); result['cleanup'].append(stopped)
            if mode=='isolation': passed=capture['reason']=='completed' and verify_isolation(proof)
            elif mode=='resources': passed=capture['reason']=='completed' and verify_resources(proof)
            else:
                expected='timeout' if mode=='timeout' else 'output_overflow'
                passed=(capture['reason']==expected and capture['observed_pids']>=3
                    and proof.get('detached_descendants_ready') is True and stopped['exit_code']==137)
            row['passed']=passed
            if not passed: break
        result['status']='passed' if len(result['cases'])==4 and all(c['passed'] for c in result['cases']) else 'blocked'
    except Exception as exc:
        result['failure_class']=type(exc).__name__
    finally:
        try:
            host.reconcile()
        except Exception as exc:
            result['failure_class']=type(exc).__name__
            result['status']='blocked'
        for name,mode in host.pending.items():
            result['cleanup'].append(dict(name=name,mode=mode,operation_id=host.operation_id,
                daemon_id=daemon_id,image_id=image_id,stopped=False,removed=False,
                failure_class='UnresolvedCreate'))
            result['status']='blocked'
        for cid in list(host.owned):
            try: result['cleanup'].append(host.cleanup(cid))
            except Exception as exc:
                result['cleanup'].append(dict(container_id=cid,stopped=False,removed=False,failure_class=type(exc).__name__))
                result['status']='blocked'
        _write(root/'receipt.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--docker',type=Path,required=True)
    for key in ('endpoint','daemon-id','image-id'): parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    result=run_probe(args.root,docker=args.docker,endpoint=args.endpoint,daemon_id=args.daemon_id,image_id=args.image_id)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__': raise SystemExit(main())
