"""Trusted local Python-only image preparation, with no registry or deployment.

The caller authenticates original-manager completion and independent review.
This adapter checks the deployed base's actual Python files, copies only scoped
Python changes into its installed package, and verifies every package file in
the resulting image. Candidate code/Dockerfiles/build scripts never execute.
Interrupted work retains its exclusive intent and cannot be replayed.
"""
from hashlib import sha256
from pathlib import Path
import json,os,re,shutil,sys,uuid
from .audit import _path,_plain,require,hash_value,strict_json,encoded
from .development_inputs import tree_hash,file_hash
from .nightly_gate import BASE
from .product_commands import DockerCommands,_write

LABEL='myink.pi.nightly.cycle'
PROBE=r'''
import sys,sysconfig,json,hashlib,stat
from pathlib import Path
p=Path(sysconfig.get_path('purelib'))/'myink'
if not p.is_dir() or p.is_symlink():raise ValueError('installed package absent')
files={};total=0
for f in sorted(p.rglob('*.py')):
 if '__pycache__' in f.parts:continue
 if f.is_symlink() or not stat.S_ISREG(f.lstat().st_mode):raise ValueError('nonregular package file')
 total+=f.stat().st_size
 if len(files)>=10000 or total>67108864:raise ValueError('package size exceeded')
 files['src/myink/'+f.relative_to(p).as_posix()]=hashlib.sha256(f.read_bytes()).hexdigest()
if not files:raise ValueError('empty package')
print(json.dumps(dict(package=str(p),files=files),sort_keys=True))
'''


def image_id(value):
    require(isinstance(value,str) and value.startswith('sha256:') and hash_value(value[7:]),'immutable image ID required');return value


def source_files(root):
    root=_path(root);pin=tree_hash(root);files={}
    for p in root.rglob('*'):
        if p.is_file():
            relative=p.relative_to(root).as_posix()
            require(re.fullmatch(r'src/myink/[A-Za-z0-9_/-]+\.py',relative) and '..' not in p.parts,'Python-only existing package scope required')
            files[relative]=file_hash(p)
    require(0<len(files)<=3,'bounded Python scope required');return root,pin,files


class LocalImage:
    def __init__(self,gate,cycle,root,docker,endpoint,daemon_id,*,transport=None):
        require(str(uuid.UUID(cycle))==cycle,'canonical cycle identity required')
        self.gate=gate;self.cycle=cycle;self.root=_path(root)
        require(not self.root.exists() and self.root.parent.is_dir(),'exclusive image preparation root required')
        require(isinstance(daemon_id,str) and 0<len(daemon_id)<=128,'fixed daemon identity required');self.daemon=daemon_id
        if gate.mode=='ACTUAL':
            require(sys.platform=='linux' and transport is None and self.root==BASE/'nightly'/cycle/'image' and _path(docker)==Path('/usr/bin/docker') and endpoint=='unix:///var/run/docker.sock','fixed ACTUAL local image host required')
        else:require(not self.root.is_relative_to(BASE),'isolated simulation required')
        self.docker=docker;self.endpoint=endpoint;self.transport=transport

    def _active(self):
        state=self.gate.status();require(state['phase']=='preparing' and state['cycle_id']==self.cycle,'active preparation required before local image work')

    def _run(self,args,*,timeout=120,output_limit=4194304):
        self._active();r=self.commands.run(args,timeout=timeout,output_limit=output_limit)
        require(r['status']=='done' and r['returncode']==0,'local image command unconfirmed')
        return (self.root/'commands'/r['command_id']/'stdout.bin').read_bytes()

    def _probe(self,image):
        name='myink-pi-image-'+uuid.uuid4().hex
        raw=self._run(['create','--name',name,'--label',LABEL+'='+self.cycle,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','256m','--cpus','1','--pids-limit','64','--user','10001:10001','--entrypoint','python',image,'-I','-S','-B','-c',PROBE])
        cid=raw.decode().strip();require(hash_value(cid),'owned probe container ID required')
        try:
            result=strict_json(self._run(['start','--attach',cid]))
            require(isinstance(result,dict) and set(result)=={'package','files'} and re.fullmatch(r'/usr/local/lib/python3\.[0-9]+/site-packages/myink',result['package']) and isinstance(result['files'],dict) and 0<len(result['files'])<=10000,'installed Python package proof required')
            require(all(re.fullmatch(r'src/myink/[A-Za-z0-9_./-]+\.py',p) and '..' not in Path(p).parts and hash_value(h) for p,h in result['files'].items()),'closed package hashes required')
            return result
        finally:
            rows=strict_json(self._run(['container','inspect',cid]));require(isinstance(rows,list) and len(rows)==1 and rows[0]['Id']==cid and rows[0]['Config']['Labels'].get(LABEL)==self.cycle and rows[0]['State']['Running'] is False,'owned stopped probe cleanup required')
            self._run(['container','rm',cid])

    def build(self,source,candidate,base_image):
        self._active();image_id(base_image);require(not self.root.exists(),'existing image intent cannot replay')
        source,source_pin,old=source_files(source);candidate,candidate_pin,new=source_files(candidate)
        require(set(old)==set(new) and old!=new,'existing-file candidate changes required')
        self.root.mkdir(mode=0o700);(self.root/'commands').mkdir(mode=0o700)
        self.commands=self.transport or DockerCommands(self.docker,self.endpoint,self.root/'commands')
        _write(self.root/'intent.json',dict(schema='pi-nightly-image-intent-v1',cycle_id=self.cycle,base_image_id=base_image,source_sha256=source_pin,candidate_sha256=candidate_pin,daemon_id=self.daemon))
        require(self._run(['info','--format','{{.ID}}']).decode().strip()==self.daemon,'original Docker daemon changed')
        rows=strict_json(self._run(['image','inspect',base_image]));require(isinstance(rows,list) and len(rows)==1 and rows[0]['Id']==base_image,'original local base image absent');base=rows[0]
        require(base.get('Os')=='linux' and base.get('Architecture') in ('amd64','arm64'),'fixed Linux image platform required')
        require(base['Config'].get('OnBuild') in (None,[]) and base['Config']['User']=='10001' and base['Config']['WorkingDir']=='/app','fixed nonroot application base required')
        require(type(base['Size']) is int and 0<base['Size']<=8*1024**3 and shutil.disk_usage(self.root).free>=base['Size']*2+1024**3,'bounded local image capacity required')
        before=self._probe(base_image);require(all(before['files'].get(p)==h for p,h in old.items()),'candidate baseline differs from installed image')
        alias='myink-pi-nightly-base:'+self.cycle
        require(not self._run(['image','ls','--quiet','--filter','reference='+alias]).strip(),'local base alias already exists')
        self._run(['image','tag',base_image,alias])
        alias_rows=strict_json(self._run(['image','inspect',alias]));require(len(alias_rows)==1 and alias_rows[0]['Id']==base_image,'local build base alias drift')
        # Keep the owned base alias: never prune the sole stable image.
        context=self.root/'context';context.mkdir(mode=0o700);lines=['FROM '+alias]
        for relative in sorted(new):
            target=context/'files'/relative;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);target.write_bytes((candidate/relative).read_bytes());target.chmod(0o644)
            destination=before['package']+'/'+relative.removeprefix('src/myink/')
            lines.append('COPY '+json.dumps(['files/'+relative,destination]))
        lines.append('LABEL '+LABEL+'='+self.cycle)
        (context/'Dockerfile').write_text('\n'.join(lines)+'\n');(context/'Dockerfile').chmod(0o600)
        require(tree_hash(source)==source_pin and tree_hash(candidate)==candidate_pin,'candidate source drift before build')
        plugin=None
        if self.transport is None:
            plugin_roots=[Path('/usr/libexec/docker/cli-plugins'),Path('/usr/lib/docker/cli-plugins')]
            if self.gate.mode=='SIMULATED':plugin_roots.append(_path(self.docker).parent.parent/'cli-plugins')
            plugin=next((p for p in plugin_roots if (p/'docker-buildx').is_file()),None)
            require(plugin is not None,'system Buildx plugin required; legacy builder cannot prepare images')
            executable=_path(plugin/'docker-buildx');_plain(executable)
            require(os.access(executable,os.X_OK) and not executable.stat().st_mode&0o022 and (self.gate.mode!='ACTUAL' or executable.stat().st_uid==0),'trusted system Buildx required')
        cli=self.root/'docker-config';cli.mkdir(mode=0o700);_write(cli/'config.json',dict(cliPluginsExtraDirs=[str(plugin)] if plugin else []))
        iid=self.root/'image-id';self._run(['--config',str(cli),'buildx','build','--network=none','--pull=false','--platform=linux/'+base['Architecture'],'--load','--iidfile',str(iid),str(context)],timeout=600)
        _plain(iid);iid.chmod(0o600);built=image_id(iid.read_text().strip());after=self._probe(built)
        require(after['package']==before['package'] and after['files']==dict(before['files'],**new),'built package differs outside candidate scope')
        archive=self.root/'image.tar';self._run(['image','save','--output',str(archive),built],timeout=600,output_limit=1048576);_plain(archive);archive.chmod(0o600)
        require(0<archive.stat().st_size<=8*1024**3,'bounded image archive required')
        with archive.open('rb') as stream:archive_pin=__import__('hashlib').file_digest(stream,'sha256').hexdigest()
        require(tree_hash(source)==source_pin and tree_hash(candidate)==candidate_pin,'candidate source changed while preparing image')
        self._active();result=dict(schema='pi-nightly-local-image-v1',status='ready',cycle_id=self.cycle,base_image_id=base_image,image_id=built,source_sha256=source_pin,candidate_sha256=candidate_pin,package_sha256=sha256(encoded(after['files'])).hexdigest(),archive_path=str(archive),archive_sha256=archive_pin,published=False,deployed=False)
        _write(self.root/'receipt.json',result);return result
