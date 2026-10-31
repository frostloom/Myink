"""Standard-library fixed checker core; no SDK, model client or paid launcher imports."""
from hashlib import sha256
import os
from pathlib import Path
import shutil
import time
import uuid
from .audit import strict_json
from .container_probe import ProbeHost,verify_inspect
from .unit_feedback import REPORT_FIELDS,validate_report

WORKERS=Path(__file__).parent/'workers'


def require(value,reason):
    if not value:raise ValueError(reason)


def file_hash(path):return sha256(Path(path).read_bytes()).hexdigest()


def atomic_write(path,raw):
    tmp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    try:
        with tmp.open('xb') as out:
            os.chmod(tmp,0o600);out.write(raw);out.flush();os.fsync(out.fileno())
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


class CheckDeadline:
    def __init__(self,seconds,cancel):
        require(type(seconds) is int and 0<seconds<=300,'bounded fixed checker deadline required')
        self.cancel=cancel;self.deadline=time.monotonic()+seconds

    def alive(self):
        require(not self.cancel.is_set() and time.monotonic()<self.deadline,'fixed checker cancelled or expired')


def cleanup_hosts(host, *, on_removed=None):
    host.reconcile()
    result=[]
    for cid in list(host.owned):
        receipt=host.cleanup(cid)
        result.append(receipt)
        if on_removed is not None:on_removed(receipt)
    require(not host.pending and all(v['removed'] for v in result),'owned cleanup incomplete')
    host.reconcile()
    require(not host.pending and not host.owned,'owned containers remain')
    host._daemon()
    remaining=host._call('ps','-a','--no-trunc','--filter',
        'label=myink.pi.operation='+host.operation_id,'--format','{{.ID}}').stdout.split()
    require(not remaining,'operation label still owns containers')
    return result


class OwnedHosts:
    """Keep every checker ownership alive through the execution-level final sweep."""
    def __init__(self,cancel,write):
        self.cancel,self.write=cancel,write
        self.hosts=[];self.history=[];self.failed=False

    def add(self,host):
        self.write('owned-host-'+str(len(self.hosts))+'.json',dict(operation_id=host.operation_id))
        self.hosts.append(host)
        return host

    def cleanup(self,host):
        try:
            return cleanup_hosts(host,on_removed=self.history.append)
        except BaseException:
            self.failed=True;self.cancel.set()
            raise

    def finish(self):
        errors=[]
        for host in self.hosts:
            try:self.cleanup(host)
            except Exception as exc:errors.append(type(exc).__name__)
        if errors:raise RuntimeError('owned cleanup incomplete')
        return self.history


def parse_check_output(output):
    # Docker demultiplexes stdout/stderr without preserving cross-stream order.
    # Require one complete fixed report; ambiguous/missing reports fail closed.
    reports=[]
    for line in output.splitlines():
        try:
            value=strict_json(line)
        except (ValueError,TypeError):
            continue
        if isinstance(value,dict) and set(value)==REPORT_FIELDS:
            reports.append(value)
    require(len(reports)==1,'missing or ambiguous fixed checker report')
    return reports[0]


def run_fixed_check(c,candidate,destination,limits,write,owners,*,host_factory=None,write_bytes=None):
    limits.alive()
    destination.mkdir(mode=0o755)
    shutil.copytree(candidate/'src',destination/'src')
    shutil.copyfile(c['test_path'],destination/'test.py')
    shutil.copyfile(Path(__file__).parent/'unit_feedback.py',destination/'feedback.py')
    require(file_hash(destination/'test.py')==c['test_sha256'],'fixed test drift')
    for p in [destination,*destination.rglob('*')]:
        p.chmod(0o755 if p.is_dir() else 0o644)
    factory=host_factory or (lambda:ProbeHost(docker=Path(c['docker']),endpoint=c['endpoint'],daemon_id=c['daemon_id'],image_id=c['checker_image_id'],operation_id=str(uuid.uuid4())))
    host=owners.add(factory())
    result=None; cleanup=[]
    try:
        cid=host.create('isolation',worker=WORKERS/'development_check.py',source=destination,
                        foreign=destination/'not-mounted')
        require(verify_inspect(host.inspect(cid)),'checker isolation mismatch')
        captured=host.capture(cid,seconds=max(.1,min(30,limits.deadline-time.monotonic())),output_limit=65536)
        (write_bytes or atomic_write)(destination/'output.log',captured['output'])
        require(captured['reason'] in ('completed','process_failed'),'checker execution incomplete')
        result=parse_check_output(captured['output'].decode())
        info=host.inspect(cid)
        require(not info['State']['Running'] and info['State']['Pid']==0,'checker still running')
        validate_report(result,info['State']['ExitCode'],c['test_cases'])
        require((captured['reason']=='completed') is result['passed'],'checker attach/exit mismatch')
        result.update(attach_returncode=info['State']['ExitCode'],container_id=cid)
    finally:
        cleanup=owners.cleanup(host)
        write(destination.name+'-cleanup.json',cleanup)
    require(cleanup and cleanup[0]['exit_code']==result['attach_returncode'],'checker exit not authenticated')
    result['cleanup']=cleanup
    return result

