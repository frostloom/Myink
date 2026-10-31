"""Read selected installed Python text without importing application code."""
from pathlib import Path,PurePosixPath
from hashlib import sha256
import json,os,re,uuid
from .audit import _path,require,strict_json,digest,hash_value
from .nightly_gate import BASE
from .nightly_image import PROBE
from .nightly_deployment import _run,PRODUCTION
from .product_commands import DockerCommands,_write

READ=r'''
import sys,sysconfig,json,stat
from pathlib import Path,PurePosixPath
p=Path(sysconfig.get_path('purelib'))/'myink';out={}
for name in json.loads(sys.argv[1]):
 if not name.startswith('src/myink/') or PurePosixPath(name).as_posix()!=name or '..' in PurePosixPath(name).parts:raise ValueError('invalid source path')
 f=p/name.removeprefix('src/myink/')
 if f.resolve()!=f or not stat.S_ISREG(f.lstat().st_mode) or f.stat().st_nlink!=1 or f.stat().st_size>24000:raise ValueError('invalid source file')
 out[name]=f.read_bytes().decode('utf-8')
print(json.dumps(out,sort_keys=True))
'''


def scope(files,mode):
    require(isinstance(files,list) and 0<len(files)<=3 and all(isinstance(f,str) and re.fullmatch(r'src/[A-Za-z0-9_/-]+\.py',f) and PurePosixPath(f).as_posix()==f for f in files) and len(set(files))==len(files),'bounded canonical Python source scope required')
    if mode=='ACTUAL':require(all(f.startswith('src/myink/') for f in files),'installed application source scope required')
    return files


def read(mode,packet,rows,files,root,*,transport=None):
    require(mode in ('ACTUAL','SIMULATED'),'explicit source read mode required');scope(files,mode);root=_path(root)
    if mode=='ACTUAL':require(os.geteuid()==0 and transport is None and root.name=='source-read' and root.parent.parent==BASE/'nightly' and str(uuid.UUID(root.parent.name))==root.parent.name,'fixed root source reader required')
    else:require(transport is not None and not root.is_relative_to(BASE),'explicit isolated source transport required')
    selected=[r for r in rows if r['role']=='myink-api'];require(len(selected)==1 and hash_value(selected[0]['container_id']) and selected[0]['image_id']==packet['manifest']['image_id'],'one verified API source container required')
    require(not root.exists() and root.parent.is_dir(),'new source read intent required');root.mkdir(mode=0o700);(root/'commands').mkdir(mode=0o700)
    _write(root/'intent.json',dict(image_id=packet['manifest']['image_id'],package_sha256=packet['image']['package_sha256'],files=files))
    commands=transport or DockerCommands(Path('/usr/bin/docker'),'unix:///var/run/docker.sock',root/'commands')
    require(_run(commands,['info','--format','{{.ID}}']).decode().strip()==(PRODUCTION if mode=='ACTUAL' else 'fixture-daemon'),'source Docker daemon changed')
    prefix=['exec','--user','10001:10001',selected[0]['container_id'],'python','-I','-S','-B','-c']
    package=strict_json(_run(commands,prefix+[PROBE]));require(set(package)=={'package','files'} and isinstance(package['files'],dict) and digest(package['files'])==packet['image']['package_sha256'],'approved full package differs')
    require(all(f in package['files'] for f in files),'selected file absent from approved package')
    values=strict_json(_run(commands,prefix+[READ,json.dumps(files)]))
    require(isinstance(values,dict) and set(values)==set(files) and all(isinstance(v,str) and len(v.encode())<=24000 and sha256(v.encode()).hexdigest()==package['files'][k] for k,v in values.items()),'selected source body differs from approved package')
    _write(root/'receipt.json',dict(package_sha256=packet['image']['package_sha256'],files={f:package['files'][f] for f in files},source_sha256=digest({f:package['files'][f] for f in files})))
    return values
