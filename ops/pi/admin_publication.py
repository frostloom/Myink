"""Fixed human-approved publication of a sealed Python-only candidate.

Git objects establish source identity locally; this adapter never pushes a ref.
Model-supplied Dockerfiles, shell commands, tags and configuration are not used.
"""
from hashlib import sha256
from pathlib import Path
import io
import os
import re
import subprocess
import tarfile

from .audit import _path, digest, require, hash_value
from .nightly_image import source_files


def _git(repository, args, *, data=None, index=None):
    repository = _path(repository)
    require(repository.is_dir() and not repository.is_symlink(), 'trusted source repository required')
    env=dict(PATH='/usr/bin:/bin',HOME='/nonexistent',LANG='C.UTF-8',GIT_CONFIG_NOSYSTEM='1')
    if index is not None: env['GIT_INDEX_FILE']=str(_path(index))
    result=subprocess.run(['/usr/bin/git','--git-dir',str(repository),*args],input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=60,check=False)
    require(result.returncode==0 and len(result.stdout)<=80*1024**2, 'trusted source command failed')
    return result.stdout


def live_config(commands, compose, config, image, rows):
    """Compare resolved service intent against the current physical cohort."""
    from .audit import strict_json
    from .nightly_deployment import _run
    def env(items):
        result={}
        for item in items:
            key,separator,value=item.partition('=');require(separator and key not in result,'unique live environment required');result[key]=value
        return result
    images=strict_json(_run(commands,['image','inspect',image]));require(len(images)==1 and images[0]['Id']==image,'original immutable image required')
    defaults=images[0]['Config']
    for role in ('myink-api','myink-worker'):
        service=config['services'][role]
        hashes=_run(commands,compose+['config','--hash',role]).decode().split()
        require(len(hashes)==2 and hashes[0]==role and hash_value(hashes[1]),'resolved Compose service identity required')
        expected_env=dict(env(defaults.get('Env',[])),**{k:str(v) for k,v in service.get('environment',{}).items() if v is not None})
        expected_mounts=[]
        for v in service.get('volumes',[]):
            source=v['source']
            if v['type']=='volume':source=config.get('volumes',{}).get(source,{}).get('name',source)
            expected_mounts.append((v['type'],source,v['target'],not v.get('read_only',False)))
        selected=[r for r in rows if r['Config'].get('Labels',{}).get('com.docker.compose.service')==role]
        require(len(selected)==(1 if role=='myink-api' else 2),'complete live application role required')
        for row in selected:
            c=row['Config'];mounts=[(v['Type'],v.get('Name') if v['Type']=='volume' else v['Source'],v['Destination'],v['RW']) for v in row.get('Mounts',[])]
            require(c['Labels'].get('com.docker.compose.config-hash')==hashes[1] and env(c.get('Env',[]))==expected_env and c.get('Cmd')==service.get('command',defaults.get('Cmd')) and sorted(mounts)==sorted(expected_mounts),'current Compose differs from live application configuration')


def package_files(repository, commit):
    require(hash_value(commit,40), 'exact source commit required')
    raw=_git(repository,['archive','--format=tar',commit,'src/myink']);files={};total=0
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for item in archive.getmembers():
            if item.isdir(): continue
            require(item.isfile() and not item.issym() and not item.islnk(), 'regular committed source required')
            if not item.name.endswith('.py'): continue
            require(re.fullmatch(r'src/myink/[A-Za-z0-9_./-]+\.py',item.name) and '..' not in Path(item.name).parts and item.size<=4194304, 'bounded committed Python source required')
            total+=item.size;require(total<=67108864 and len(files)<10000 and item.name not in files,'bounded full source package required')
            stream=archive.extractfile(item);require(stream is not None,'committed source missing');files[item.name]=sha256(stream.read()).hexdigest()
    require(bool(files),'committed package absent')
    return files


def candidate_commit(repository, base_commit, candidate, expected_package_sha256, work):
    """Create and retain a full-package-verified commit; leave main untouched."""
    require(hash_value(expected_package_sha256), 'candidate package digest required')
    files=package_files(repository,base_commit);candidate,source_pin,changes=source_files(candidate)
    require(set(changes)<=set(files),'candidate adds unapproved package files')
    expected=dict(files,**changes);require(digest(expected)==expected_package_sha256,'candidate differs from full image package')
    work=_path(work);require(work.is_dir(),'private publication source workspace required');index=work/'git-index';require(not index.exists(),'source preparation cannot replay')
    _git(repository,['read-tree',base_commit],index=index)
    for relative,pin in sorted(changes.items()):
        raw=(candidate/relative).read_bytes();require(sha256(raw).hexdigest()==pin,'candidate source changed')
        blob=_git(repository,['hash-object','-w','--stdin'],data=raw).decode().strip();require(hash_value(blob,40),'source object absent')
        _git(repository,['update-index','--add','--cacheinfo','100644',blob,relative],index=index)
    tree=_git(repository,['write-tree'],index=index).decode().strip();require(hash_value(tree,40),'source tree absent')
    commit=_git(repository,['-c','user.name=Myink Pi','-c','user.email=pi@myink.local','-c','commit.gpgsign=false','commit-tree',tree,'-p',base_commit],data=b'Pi human-approved image candidate\n').decode().strip()
    require(package_files(repository,commit)==expected,'candidate Git object differs from frozen image')
    # Recheck the original frozen bytes after all subprocess work.
    require(source_files(candidate)[1]==source_pin,'candidate source changed during commit preparation')
    _git(repository,['update-ref','refs/pi-candidates/'+commit,commit])
    return commit


class NativePublication:
    """Deploy a sealed local image; preserve dependencies, data and accounting."""
    def __init__(self, gate, config_pin=None, *, config_path=None, transport_factory=None, bundle_verifier=None, deployment_verifier=None):
        from .nightly_gate import BASE
        import stat
        self.gate=gate;self.pin=config_pin;self.config=None
        self.transport_factory=transport_factory;self.bundle_verifier=bundle_verifier;self.deployment_verifier=deployment_verifier
        if gate.mode=='ACTUAL':
            require(os.geteuid()==0 and config_path is None and all(v is None for v in (transport_factory,bundle_verifier,deployment_verifier)),'fixed root publication dependencies required')
            config_path=BASE/'config/admin-publication.json'
        else:require(config_path is not None and transport_factory is not None,'explicit isolated publication required')
        self.config_path=_path(config_path)
        if config_pin is None:return
        require(hash_value(config_pin) and sha256(self.config_path.read_bytes()).hexdigest()==config_pin,'publication configuration changed')
        c=self._read(self.config_path,65536)
        require(set(c)=={'schema','mode','source_repository','compose_files'} and c['schema']=='pi-admin-publication-v1' and c['mode']==gate.mode,'closed publication configuration required')
        repo=_path(c['source_repository']);require(repo.is_dir(),'trusted source objects absent')
        require(isinstance(c['compose_files'],list) and 1<=len(c['compose_files'])<=2,'fixed Compose source files required')
        for name in c['compose_files']:
            from .audit import _plain
            _plain(_path(name))
        if gate.mode=='ACTUAL':
            files=['/home/ubuntu/myink/docker-compose.yml','/home/ubuntu/myink/docker-compose.pi-console.yml']
            require(c['compose_files'] in (files[:1],files) and repo==BASE/'control/source.git','fixed original publication roots required')
            require(self.config_path.stat().st_uid==0 and stat.S_IMODE(self.config_path.stat().st_mode)==0o640 and repo.stat().st_uid==0 and stat.S_IMODE(repo.stat().st_mode)==0o700,'root private publication inputs required')
        else:require(not repo.is_relative_to(BASE),'simulation cannot use original source objects')
        self.config=c

    @staticmethod
    def _read(path,bound=4194304):
        from .audit import _plain,strict_json
        path=_path(path);_plain(path);require(path.stat().st_size<=bound,'bounded publication input required');return strict_json(path.read_bytes())

    def available(self):return self.config is not None

    def _active(self):
        require(self.config is not None and sha256(self.config_path.read_bytes()).hexdigest()==self.pin,'publication channel unavailable or changed')

    def _packet(self,bundle):
        from .nightly_bundle import verify
        return (self.bundle_verifier or verify)(self.gate,bundle)

    def _commands(self,path):
        from .product_commands import DockerCommands
        path.mkdir(mode=0o700)
        return self.transport_factory(path) if self.transport_factory else DockerCommands(Path('/usr/bin/docker'),'unix:///var/run/docker.sock',path)

    def _daemon(self):
        from .nightly_deployment import PRODUCTION
        return PRODUCTION if self.gate.mode=='ACTUAL' else 'simulation-console-daemon'

    def _idle(self,commands):
        from .nightly_deployment import _run
        ids=_run(commands,['ps','-q','--filter','label=com.docker.compose.project=myink','--filter','label=com.docker.compose.service=myink-rabbitmq']).decode().split();require(len(ids)==1,'original queue source unavailable')
        rows=_run(commands,['exec',ids[0],'rabbitmqctl','list_queues','name','messages_ready','messages_unacknowledged'],timeout=90).decode().splitlines();queues={}
        for row in rows:
            fields=row.split('\t')
            if len(fields)==3 and fields[0] in ('queue:tasks','queue:tasks:vip'):queues[fields[0]]=(int(fields[1]),int(fields[2]))
        require(set(queues)=={'queue:tasks','queue:tasks:vip'} and all(v==(0,0) for v in queues.values()),'business tasks must be idle before publication')

    def _ledgers(self):
        from .development_inputs import ledger_snapshot
        return [ledger_snapshot(p)['sha256'] for p in (self.gate.state,self.gate.billing)]

    def prepare(self,cycle,bundle):
        from .audit import strict_json,utc
        from .nightly_gate import BASE
        from .nightly_deployment import _run,_cohort,_identity
        from .nightly_rebuild import _product
        from .nightly_image import probe_image
        from .product_commands import _write
        from .development_inputs import file_hash
        self._active();bundle=_path(bundle);state=self.gate.status()
        require(state['phase']=='awaiting_approval' and state['cycle_id']==cycle,'current human review required')
        if self.gate.mode=='ACTUAL':require(bundle==BASE/'nightly'/cycle/'bundle','fixed candidate publication root required')
        packet=self._packet(bundle);before=self._ledgers();root=bundle.parent/'console-publication'
        require(not root.exists(),'publication preparation already claimed; inspection required');root.mkdir(mode=0o700)
        _write(root/'prepare-intent.json',dict(cycle_id=cycle,package_sha256=digest(packet['manifest']),config_sha256=self.pin))
        commands=self._commands(root/'prepare-commands');require(_run(commands,['info','--format','{{.ID}}']).decode().strip()==self._daemon(),'original Docker daemon changed')
        base_image=packet['image']['base_image_id'];previous=_product(commands,base_image)
        ids=_run(commands,['ps','-q','--filter','label=com.docker.compose.project=myink']).decode().split();rows=strict_json(_run(commands,['container','inspect',*ids]))
        identities=[_identity(r['Config'].get('Env',[]),base_image) for r in rows if r['Config'].get('Labels',{}).get('com.docker.compose.service') in ('myink-api','myink-worker')]
        require(len(identities)==3 and all(v==identities[0] for v in identities),'complete base runtime identity required')
        repository=Path(self.config['source_repository']);base_files=package_files(repository,identities[0]['commit_sha'])
        cohort,reason=_cohort(commands,base_image,digest(base_files),utc(self.gate.clock()));require(cohort is not None and reason is None,'base product source is not verified')
        image=packet['manifest']['image_id'];probe=probe_image(commands,image,cycle)
        require(digest(probe['files'])==packet['image']['package_sha256'],'frozen candidate image changed')
        commit=candidate_commit(repository,identities[0]['commit_sha'],bundle/'candidate',packet['image']['package_sha256'],root)
        compose=['compose','--project-directory',str(Path(self.config['compose_files'][0]).parent),'--project-name','myink']
        for name in self.config['compose_files']:compose.extend(['-f',name])
        base=strict_json(_run(commands,compose+['config','--format','json']));live_config(commands,compose,base,base_image,rows);_write(root/'previous-compose-private.json',base)
        from .admin_maintenance import Maintenance
        maintenance=Maintenance(commands);base_maintenance=maintenance.opened(identities[0]);maintenance.quiet()
        services={key:dict(base['services'][key],image=image) for key in ('myink-api','myink-worker')}
        config_sha=digest(dict(schema='pi-effective-product-config-v1',image_id=image,services=services))
        import json
        env=dict(DEPLOYMENT_ID='pi-nightly-'+cycle,DEPLOYMENT_GENERATION=str(identities[0]['generation']+1),DEPLOYMENT_OWNER='human-gated-pi',DEPLOYMENT_IMAGE_IDS=json.dumps(dict(python=image),sort_keys=True,separators=(',',':')),DEPLOYMENT_COMMIT_SHA=commit,OBSERVATION_SCHEMA_ID='myink-run-provenance-v1',OBSERVATION_CONFIG_ID=config_sha)
        identity=_identity([k+'='+v for k,v in env.items()],image);alias='myink-api:pi-console-'+cycle
        require(not _run(commands,['image','ls','-q','--filter','reference='+alias]).strip(),'publication image alias already claimed')
        _run(commands,['image','tag',image,alias]);require(strict_json(_run(commands,['image','inspect',alias]))[0]['Id']==image,'publication image alias changed')
        override=dict(services={key:dict(image=alias,pull_policy='never',environment=env) for key in services});path=root/'compose.override.json';_write(path,override)
        effective=strict_json(_run(commands,compose+['-f',str(path),'config','--format','json']))
        for key in services:
            current=effective['services'][key];old=base['services'][key]
            require(current['image']==alias and current['command']==old['command'] and current.get('volumes',[])==old.get('volumes',[]),'publication changes service scope')
            require(all(current['environment'].get(k)==v for k,v in old['environment'].items() if k not in env) and all(current['environment'].get(k)==v for k,v in env.items()),'publication changes effective environment')
        self._idle(commands);require(_product(commands,base_image)==previous and self._ledgers()==before,'preparation changed original state')
        plan=dict(schema='pi-admin-publication-plan-v1',mode=self.gate.mode,cycle_id=cycle,package_sha256=digest(packet['manifest']),image_id=image,base_image_id=base_image,source_commit=commit,identity=identity,previous_product_sha256=previous,base_config_sha256=digest(base),override_sha256=file_hash(path),compose_arguments=compose+['-f',str(path)],alias=alias,ledger_sha256=before,base_maintenance=base_maintenance)
        _write(root/'plan.json',plan);return plan

    def publish(self,cycle,bundle,plan):
        from .audit import strict_json,utc
        from .nightly_deployment import _run,_cohort,confirm
        from .nightly_rebuild import _product
        from .product_commands import _write
        from .development_inputs import file_hash
        self._active();self.gate.require_action(cycle,'deploy');bundle=_path(bundle);packet=self._packet(bundle);root=bundle.parent/'console-publication'
        require(self._read(root/'plan.json')==plan and plan['cycle_id']==cycle and plan['mode']==self.gate.mode and plan['package_sha256']==digest(packet['manifest']) and plan['image_id']==packet['manifest']['image_id'],'publication plan changed')
        require(file_hash(root/'compose.override.json')==plan['override_sha256'] and digest(package_files(Path(self.config['source_repository']),plan['source_commit']))==packet['image']['package_sha256'],'publication source or configuration changed')
        commands=self._commands(root/'publish-commands');require(_run(commands,['info','--format','{{.ID}}']).decode().strip()==self._daemon(),'Docker daemon changed')
        require(_product(commands,plan['base_image_id'])==plan['previous_product_sha256'],'base product changed')
        compose=plan['compose_arguments'];require(digest(strict_json(_run(commands,compose[:-2]+['config','--format','json'])))==plan['base_config_sha256'],'base configuration changed')
        require(strict_json(_run(commands,['image','inspect',plan['alias']]))[0]['Id']==plan['image_id'],'candidate alias changed')
        from .admin_maintenance import Maintenance
        current_base=strict_json(_run(commands,compose[:-2]+['config','--format','json']))
        ids=_run(commands,['ps','-q','--filter','label=com.docker.compose.project=myink']).decode().split()
        live_config(commands,compose[:-2],current_base,plan['base_image_id'],strict_json(_run(commands,['container','inspect',*ids])))
        maintenance=Maintenance(commands);require(maintenance.read()==plan['base_maintenance'],'original maintenance owner changed')
        self._idle(commands);self.gate.require_action(cycle,'deploy')
        closed=maintenance.close(plan['base_maintenance'],cycle,self.gate.clock(),root)
        self._idle(commands);self.gate.require_action(cycle,'deploy')
        args=compose+['up','--detach','--no-deps','--no-build','--pull','never','--wait','--wait-timeout','180','--scale','myink-worker=2','myink-api','myink-worker']
        _write(root/'deploy-intent.json',dict(cycle_id=cycle,package_sha256=plan['package_sha256'],image_id=plan['image_id'],command=args))
        _run(commands,args,timeout=240);cohort,reason=_cohort(commands,plan['image_id'],packet['image']['package_sha256'],utc(self.gate.clock()))
        require(cohort is not None and reason is None and all(r['identity']==plan['identity'] for r in cohort),'deployed candidate identity unverified')
        require(self._ledgers()==plan['ledger_sha256'],'publication changed original accounting')
        maintenance.quiet();closed=maintenance.adopt(closed,plan['identity'],root)
        if self.deployment_verifier:result=self.deployment_verifier(self.gate,cycle,bundle)
        else:result=confirm(self.gate,cycle,bundle,Path('/usr/bin/docker'),'unix:///var/run/docker.sock',self._daemon(),**({'transport_factory':self.transport_factory} if self.transport_factory else {}))
        require(result.get('verified') is True and result['status']=='observing','actual deployment attestation incomplete')
        maintenance.reopen(closed,root)
        _write(root/'deploy-result.json',dict(status='verified',source_commit=plan['source_commit'],image_id=plan['image_id'],accounting_unchanged=True));return result
