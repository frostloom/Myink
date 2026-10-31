"""Operator-only telemetry bootstrap asset; never advances a pending Pi cycle."""
from pathlib import Path
import fcntl,os,sys,uuid
from .audit import _path,_plain,require,digest
from .development_inputs import file_hash,ledger_snapshot
from .nightly_bundle import verify
from .nightly_gate import BASE
from .nightly_image import LocalImage,source_files
from .nightly_rebuild import FILES,_product
from .nightly_deployment import PRODUCTION
from .product_commands import _write

PATCH='4cc8a8c376f3da586efade6942f4a4b032f0c975f0be6e4edb2034b31645c112'
PREIMAGES={
 'src/myink/config.py':'c2b3ca3f228edb35e84bb643ec48eaebd3a3e014e38a72859b61caca6bf55c15',
 'src/myink/observability.py':None,
 'src/myink/workflow/nodes.py':'9a5ce3868eab4794c8d1e19a4103b3f0ce8813e7c163f356ee987538e21435b9'}
CANDIDATES={
 'src/myink/config.py':'e3f020de80c07786db9d35c48f4043d5eeb093a5e3272aa49715bd6aea5200b4',
 'src/myink/observability.py':'832181da94bc336a1bf19e94d18864a7ecac71c7431aaf443ba37324cc8faaac',
 'src/myink/workflow/nodes.py':'46882a096f9dbb7faa57d4982622f5ed4d638842fb2c6d298329ba6524e42d8c'}


class CompatibilityImage(LocalImage):
    def __init__(self,gate,cycle,root,docker,endpoint,daemon_id,*,transport=None):
        self.gate=gate;self.cycle=cycle;self.root=_path(root);self.daemon=daemon_id;self.docker=docker;self.endpoint=endpoint;self.transport=transport;self.probes=[];self.waiting=gate.status()
        require(str(uuid.UUID(cycle))==cycle and self.waiting['cycle_id']==cycle and self.waiting['phase']=='awaiting_approval','original unapproved pending cycle required')
        require(not self.root.exists() and self.root.parent.is_dir(),'exclusive compatibility image root required')
        if gate.mode=='ACTUAL':
            require(sys.platform=='linux' and os.geteuid()==0 and transport is None and self.root==BASE/'staging'/('compatible-'+cycle)/'image' and _path(docker)==Path('/usr/bin/docker') and endpoint=='unix:///var/run/docker.sock' and daemon_id==PRODUCTION,'fixed root compatibility builder required')
        else:require(not self.root.is_relative_to(BASE) and daemon_id!=PRODUCTION,'isolated compatibility builder required')

    def _alias(self):return 'myink-pi-compatible-base:'+self.cycle

    def _active(self):require(self.gate.status()==self.waiting,'pending cycle changed during compatibility preparation')

    def _scope(self,old,new):require(old=={p:h for p,h in PREIMAGES.items() if h is not None} and new==CANDIDATES and set(new)==FILES,'fixed telemetry companion source required')

    def _probe(self,image):
        result=super()._probe(image);self.probes.append(result)
        if len(self.probes)==1:require(all(result['files'].get(p)==h for p,h in PREIMAGES.items()),'telemetry preimages differ from installed product')
        return result


def prepare(gate,bundle,root,source,candidate,patch,parent,docker,endpoint,daemon,*,transport=None):
    """Build a local compatible base, leaving approvals and original accounting alone."""
    packet=verify(gate,bundle);cycle=_path(bundle).parent.name;root=_path(root);patch=_path(patch);_plain(patch)
    require(file_hash(patch)==PATCH,'fixed main telemetry companion patch required')
    old=source_files(source)[2];new=source_files(candidate)[2]
    require(old=={p:h for p,h in PREIMAGES.items() if h is not None} and new==CANDIDATES,'fixed telemetry source files required')
    require(not root.exists() and root.parent.is_dir(),'compatibility intent cannot replay')
    lock=None
    if gate.mode=='ACTUAL':
        require(os.geteuid()==0 and transport is None and _path(bundle)==BASE/'nightly'/cycle/'bundle' and root==BASE/'staging'/('compatible-'+cycle),'fixed operator bootstrap paths required')
        lock_path=BASE/'control/nightly.lock';_plain(lock_path);lock=lock_path.open('rb')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:lock.close();return dict(status='lock_busy',model_requests=0)
    try:
        waiting=gate.status();require(waiting['cycle_id']==cycle and waiting['phase']=='awaiting_approval' and waiting['package_sha256']==digest(packet['manifest']),'original waiting package required')
        accounting=ledger_snapshot(gate.state),ledger_snapshot(gate.billing)
        root.mkdir(mode=0o700);_write(root/'intent.json',dict(schema='pi-compatible-base-intent-v1',cycle_id=cycle,package_sha256=waiting['package_sha256'],parent_image_id=parent,patch_sha256=PATCH))
        image=CompatibilityImage(gate,cycle,root/'image',docker,endpoint,daemon,transport=transport)
        # Current healthy product is checked immediately around all Docker work.
        # The first probe invokes this after DockerCommands has been initialized.
        original_probe=image._probe;cohort=[]
        def probe(value):
            if gate.mode=='ACTUAL' and not cohort:cohort.append(_product(image.commands,parent))
            return original_probe(value)
        image._probe=probe
        result=image.build(source,candidate,parent)
        if gate.mode=='ACTUAL':require(_product(image.commands,parent)==cohort[0],'current product changed during compatibility preparation')
        require(gate.status()==waiting and (ledger_snapshot(gate.state),ledger_snapshot(gate.billing))==accounting and file_hash(patch)==PATCH,'original state or companion changed during bootstrap')
        before,after=image.probes
        report=dict(schema='pi-nightly-compatible-base-v1',mode=gate.mode,issuer='trusted_compatibility_builder',cycle_id=cycle,package_sha256=waiting['package_sha256'],parent_image_id=parent,image_id=result['image_id'],parent_package_sha256=digest(before['files']),package_map_sha256=digest(after['files']),patch_sha256=PATCH,changes={p:dict(before=PREIMAGES[p],after=CANDIDATES[p]) for p in sorted(FILES)})
        _write(root/'compatibility.json',report);return report
    finally:
        if lock is not None:lock.close()
