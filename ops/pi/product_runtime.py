"""Canonical Linux product host. It is never registered as a model tool."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import stat
import sys
import tarfile
import time

from .audit import _path, _plain, digest, encoded, hash_value, require, strict_json, utc, SHANGHAI
from .audit_export import _publish
from .ledger import Ledger
from .product_bootstrap import _plan, STEPS
from .product_commands import DockerCommands

BASE=Path('/home/ubuntu/myink-pi-managed')
FIELDS=set('schema mode target docker endpoint daemon_id root lock_path project plan_path plan_sha256 approval_path approval_sha256 legacy_manifest_path legacy_manifest_sha256 candidate_manifest_path candidate_manifest_sha256 backup_path backup_sha256 compose_dir drain_seconds queue_prefix'.split())
SERVICES={'myink-api':'api','myink-worker':'worker','myink-caddy':'frontend','myink-pg':'postgres','myink-redis':'redis','myink-rabbitmq':'rabbitmq'}
INSPECT_FORMAT='{"id":{{json .Id}},"image_id":{{json .Image}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"running":{{json .State.Running}},"exit_code":{{json .State.ExitCode}},"oom":{{json .State.OOMKilled}},"ports":{{json .NetworkSettings.Ports}}}'
DRAIN_SQL="""BEGIN READ ONLY; SET LOCAL statement_timeout='3s';
SELECT json_build_object('active_tasks',(SELECT count(*) FROM tasks WHERE status IN ('queued','running')),
'unknown',(SELECT count(*) FROM tasks WHERE status NOT IN ('queued','running','done','failed','cancelled','paused','awaiting_review','awaiting_plan')) +
(SELECT count(*) FROM pg_stat_activity WHERE usename='myink_app' AND backend_type='client backend' AND state NOT IN ('idle','disabled'))); ROLLBACK;"""
DRAIN_REDIS="""local result={}; for _,pair in ipairs({{'task_locks','lock:task:*'},{'book_locks','lock:book:*'}}) do
local cursor='0';local count=0;local scans=0;repeat local page=redis.call('SCAN',cursor,'MATCH',pair[2],'COUNT',100);cursor=page[1];count=count+#page[2];scans=scans+1;if count>10000 or scans>1000 then return redis.error_reply('bounded_lock_census') end until cursor=='0';result[pair[1]]=count;end;return cjson.encode(result)"""


def _save(path,value):_publish(path,encoded(value),immutable=True)


def _pinned(path,pin,actual=False):
    path=_path(path);_plain(path);info=path.stat()
    require(info.st_size<=1048576 and sha256(path.read_bytes()).hexdigest()==pin,'sealed product input drift')
    require(stat.S_IMODE(info.st_mode)==(0o640 if actual else 0o600),'private sealed product input required')
    if actual:require(info.st_uid==0 and path.parent==BASE/'config' and path.parent.stat().st_uid==0 and stat.S_IMODE(path.parent.stat().st_mode)==0o750,'root-issued product input required')
    return strict_json(path.read_bytes())


class LinuxProductHost:
    def __init__(self, config_path, config_sha256, *, clock=None):
        self.config_path=_path(config_path);self.pin=config_sha256
        _plain(self.config_path);require(self.config_path.stat().st_size<=65536 and sha256(self.config_path.read_bytes()).hexdigest()==self.pin,'product host config drift')
        self.config=strict_json(self.config_path.read_bytes());c=self.config
        require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-linux-product-host-v1' and c['mode'] in ('ACTUAL','SIMULATED') and c['target'] in ('production','rehearsal'),'closed Linux host config required')
        actual=c['mode']=='ACTUAL'
        require(not actual or clock is None,'ACTUAL forbids an injected clock');self.clock=clock or (lambda:datetime.now(timezone.utc))
        if actual:
            require(sys.platform=='linux' and os.geteuid()==pwd.getpwnam('ubuntu').pw_uid and os.geteuid()!=0,'ordinary canonical Linux host required')
            expected=BASE/'config'/('product-release.json' if c['target']=='production' else 'product-rehearsal.json')
            require(self.config_path==expected,'canonical product config required');_pinned(self.config_path,self.pin,True)
            require(c['docker']=='/usr/bin/docker' and c['endpoint']=='unix:///var/run/docker.sock','fixed native Docker required')
            _plain(Path(c['docker']));require(Path(c['docker']).stat().st_uid==0 and not Path(c['docker']).stat().st_mode&0o022,'trusted root Docker required')
            require(c['lock_path']==str(BASE/'control/maintenance.lock'),'shared original maintenance lock required')
            # No ACTUAL bootstrap can start with an absent recovery implementation.
            from .product_backup import LinuxProductBackup
            from .product_restore import OwnedPostgresRestore
            require(callable(getattr(type(self),'apply_schema',None)) and callable(getattr(type(self),'bind_identity',None)) and callable(getattr(OwnedPostgresRestore,'restore',None)) and callable(getattr(type(self),'activate',None)) and callable(getattr(type(self),'rollback',None)),'complete native release capabilities required before product access')
        else:
            require(clock is None or callable(clock));_pinned(self.config_path,self.pin)
            require(stat.S_IMODE(self.config_path.parent.stat().st_mode)==0o700,'private simulated config parent required')
            require(not _path(c['root']).is_relative_to(BASE) and not self.config_path.is_relative_to(BASE),'simulation cannot target original server paths')
        self.root=_path(c['root']);require(self.root.is_dir() and stat.S_IMODE(self.root.stat().st_mode)==0o700 and self.root.stat().st_uid==os.geteuid(),'owned private product output required')
        self.lock_path=_path(c['lock_path']);_plain(self.lock_path);require(stat.S_IMODE(self.lock_path.stat().st_mode)==0o600 and self.lock_path.stat().st_uid==os.geteuid(),'existing owned shared lock required')
        self.plan=_plan(_pinned(c['plan_path'],c['plan_sha256'],actual));require(self.plan['mode']==c['mode'],'product mode drift')
        if actual:
            required_root=BASE/('product-release-runs' if c['target']=='production' else 'product-rehearsals')/self.plan['operation_id']
            require(self.root==required_root,'canonical operation output root required')
        expected_project='myink' if c['target']=='production' else 'myink-pi-rehearsal-'+self.plan['operation_id']
        require(c['project']==expected_project,'fixed product/rehearsal project required')
        require(type(c['drain_seconds']) in (int,float) and 0<c['drain_seconds']<=600 and (not actual or c['drain_seconds']>=30),'bounded natural drain required')
        require(isinstance(c['queue_prefix'],str) and len(c['queue_prefix'])<=80 and all(ch.isalnum() or ch in '-_' for ch in c['queue_prefix']),'fixed queue namespace required')
        require(c['target']!='production' or c['queue_prefix']=='','original product queue namespace required')
        require(_path(c['compose_dir']).is_dir() and (not actual or c['target']!='production' or c['compose_dir']=='/home/ubuntu/myink'),'fixed compose directory required')
        for key in ('legacy_manifest','candidate_manifest','backup'):_pinned(c[key+'_path'],c[key+'_sha256'],actual)
        self._authority(self.plan)
        commands=self.root/'commands';commands.mkdir(mode=0o700,exist_ok=True);self.commands=DockerCommands(c['docker'],c['endpoint'],commands)
        actions=self.root/'actions';actions.mkdir(mode=0o700,exist_ok=True)
        control=(BASE/'control/product-release.sqlite' if actual else self.lock_path.parent/'product-release.sqlite') if c['target']=='production' else self.root/'control.sqlite'
        if not control.exists():
            fd=os.open(control,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
        _plain(control);require(stat.S_IMODE(control.stat().st_mode)==0o600,'private product control ledger required')
        self.ledger=Ledger(control);self._held=ContextVar('product-lock-'+self.plan['operation_id'],default=None)

    def _authority(self, plan):
        c=self.config;actual=c['mode']=='ACTUAL'
        _pinned(self.config_path,self.pin,actual)
        sealed=_plan(_pinned(c['plan_path'],c['plan_sha256'],actual));require(plan==sealed==self.plan,'exact original product plan required')
        approval=_pinned(c['approval_path'],c['approval_sha256'],actual)
        require(isinstance(approval,dict) and set(approval)=={'schema','mode','target','authority','plan_sha256','approved_actions','expires_at'} and approval['schema']=='pi-product-release-approval-v1','independent product approval required')
        authority='human_product_release' if c['target']=='production' else 'owned_rehearsal'
        require(approval['mode']==c['mode'] and approval['target']==c['target'] and approval['authority']==authority and approval['plan_sha256']==digest(plan),'exact external product approval required')
        require(isinstance(approval['approved_actions'],list) and set(approval['approved_actions'])==set(STEPS) and len(approval['approved_actions'])==len(STEPS),'fixed approved bootstrap actions required')
        now=utc(self.clock());require(now<min(utc(plan['expires_at']),utc(approval['expires_at'])),'product approval expired')
        if actual and c['target']=='production':
            local=now.astimezone(SHANGHAI);require(2<=local.hour<6 and utc(plan['expires_at'])<=local.replace(hour=6,minute=0,second=0,microsecond=0),'outside approved maintenance window')
        for key in ('legacy_manifest','candidate_manifest','backup'):_pinned(c[key+'_path'],c[key+'_sha256'],actual)

    @contextmanager
    def lock(self,plan):
        self._authority(plan);require(self._held.get() is None,'nested product lock rejected')
        with self.lock_path.open('rb') as locked:
            require((os.fstat(locked.fileno()).st_dev,os.fstat(locked.fileno()).st_ino)==(self.lock_path.stat().st_dev,self.lock_path.stat().st_ino),'shared lock replaced')
            fcntl.flock(locked,fcntl.LOCK_EX|fcntl.LOCK_NB);token=self._held.set(locked)
            try:yield
            finally:self._held.reset(token);fcntl.flock(locked,fcntl.LOCK_UN)

    def authorize(self,plan):
        self._authority(plan);locked=self._held.get();require(locked is not None,'shared product lock required')
        require(_path(self.lock_path)==self.lock_path and (os.fstat(locked.fileno()).st_dev,os.fstat(locked.fileno()).st_ino)==(self.lock_path.stat().st_dev,self.lock_path.stat().st_ino),'canonical shared lock drift')

    def preflight(self):
        self.authorize(self.plan)
        require(callable(getattr(self,'apply_schema',None)) and callable(getattr(self,'bind_identity',None)),'complete migration capabilities required before ingress effects')
        from .product_backup import LinuxProductBackup
        recovery=LinuxProductBackup(self);recovery.preflight()
        from .product_release import _preflight_recovery
        _preflight_recovery(self.ledger,self.plan['operation_id'],recovery.context,self.clock())

    def _run(self,args,*,limit=1048576,seconds=30,stdin_path=None):
        self.authorize(self.plan)
        remaining=(utc(self.plan['expires_at'])-utc(self.clock())).total_seconds();require(remaining>0,'product command deadline expired')
        return self.commands.run(args,timeout=min(seconds,remaining),output_limit=limit,stdin_path=stdin_path)

    def _bytes(self,result):
        path=self.commands.root/result['command_id']/'stdout.bin';_plain(path)
        require(path.stat().st_size==result['stdout']['bytes'] and sha256(path.read_bytes()).hexdigest()==result['stdout']['sha256'],'native command output drift')
        return path.read_bytes()

    def _json(self,args):return strict_json(self._bytes(self._run(args)))

    def _rows(self):
        info=self._json(['info','--format','{{json .}}']);require(isinstance(info,dict) and info.get('ID')==self.config['daemon_id'],'Docker daemon drift')
        raw=self._bytes(self._run(['ps','--all','--no-trunc','--filter','label=com.docker.compose.project='+self.config['project'],'--format','{{.ID}}']))
        ids=raw.decode().splitlines();require(len(ids)<=16 and len(set(ids))==len(ids) and all(hash_value(v) for v in ids),'complete fixed product census required')
        raw=self._bytes(self._run(['inspect','--format',INSPECT_FORMAT,*ids]));rows=[strict_json(line) for line in raw.splitlines() if line]
        require({r.get('id') for r in rows}==set(ids) and len(rows)==len(ids),'incomplete product inspect')
        selected=[]
        for row in rows:
            require(set(row)=={'id','image_id','project','service','running','exit_code','oom','ports'} and row['project']==self.config['project'] and type(row['running']) is bool and type(row['exit_code']) is int and type(row['oom']) is bool,'typed product container required')
            if row['service']=='myink-migrate' and not row['running']:continue
            require(row['service'] in SERVICES and not row['oom'],'unreviewed product service')
            if SERVICES[row['service']] not in ('api','worker'):require(row['running'],'product infrastructure stopped')
            if row['service']=='myink-api':
                require(isinstance(row['ports'],(dict,type(None))),'typed API port bindings required')
                for bindings in (row['ports'] or {}).values():
                    require(bindings is None or isinstance(bindings,list),'typed API port bindings required')
                    for binding in bindings or []:require(binding.get('HostIp') in ('127.0.0.1','::1'),'direct public API bypasses maintenance fence')
            selected.append(row)
        actual=sorted([dict(id=r['id'],service=SERVICES[r['service']],image_id=r['image_id']) for r in selected],key=lambda r:r['id'])
        require(actual==sorted(self.plan['legacy']['containers'],key=lambda r:r['id']),'product cohort drift')
        return selected

    def _source_files(self,cid):
        result=self._run(['cp',cid+':/app/src','-'],limit=67108864)
        archive=self.commands.root/result['command_id']/'stdout.bin';files={};total=0
        with tarfile.open(archive,mode='r:') as stream:
            for member in stream:
                path=PurePosixPath(member.name);require(not path.is_absolute() and '..' not in path.parts and path.parts[0]=='src' and (member.isdir() or member.isfile()),'unsafe product source archive')
                if member.isdir() or '__pycache__' in path.parts or path.suffix in ('.pyc','.pyo'):continue
                require(len(files)<10000 and member.size<=4194304 and str(path) not in files,'bounded source archive required');total+=member.size;require(total<=67108864)
                raw=stream.extractfile(member).read();require(len(raw)==member.size);files[str(path)]=sha256(raw).hexdigest()
        return files

    def inspect(self,plan):
        self.authorize(plan);rows=self._rows();manifest=_pinned(self.config['legacy_manifest_path'],self.config['legacy_manifest_sha256'],self.config['mode']=='ACTUAL')
        require(isinstance(manifest,dict) and set(manifest)=={'source_commit','files'} and manifest['source_commit']==plan['legacy']['source_commit'] and digest(manifest['files'])==plan['legacy']['source_sha256'],'frozen legacy source manifest required')
        for row in rows:
            if row['service'] in ('myink-api','myink-worker'):require(self._source_files(row['id'])==manifest['files'],'physical product source drift')
        require(sorted([dict(id=r['id'],service=SERVICES[r['service']],image_id=r['image_id']) for r in self._rows()],key=lambda r:r['id'])==sorted(plan['legacy']['containers'],key=lambda r:r['id']),'product changed during source inspection')
        return deepcopy(plan['legacy'])

    def _candidate_cohort(self):
        self.authorize(self.plan);op=self.plan['operation_id'];pin=digest(self.plan)
        parent=self.ledger.get(op);row=self.ledger.get('candidate:'+op)
        require(parent and parent['kind']=='product_bootstrap' and parent['status']=='done' and parent['payload']==dict(plan_sha256=pin),'original prepared bootstrap required')
        require(row and row['kind']=='product_candidate' and row['status']=='done' and row['payload']==dict(plan_sha256=pin),'durable adopted cohort required')
        path=self.root/'candidate-cohort.json';_plain(path);require(path.stat().st_size<=65536,'bounded adopted cohort required');cohort=strict_json(path.read_bytes())
        require(row['evidence'].get('cohort_sha256')==digest(cohort) and set(cohort)=={'schema','plan_sha256','containers'} and cohort['schema']=='pi-product-candidate-cohort-v1' and cohort['plan_sha256']==pin,'adopted cohort registry drift')
        rows=cohort['containers'];require(isinstance(rows,list) and len(rows)==3,'complete adopted application cohort required');seen=set();roles=[]
        for r in rows:
            require(isinstance(r,dict) and set(r)=={'id','service','image_id'} and hash_value(r['id']) and r['id'] not in seen and r['id'] not in {v['id'] for v in self.plan['legacy']['containers']} and r['image_id']==self.plan['candidate']['image_ids']['python'],'foreign adopted cohort')
            seen.add(r['id']);roles.append(r['service'])
        require(sorted(roles)==['api','worker','worker'],'fixed adopted roles required');return rows

    def _candidate_state(self):
        value=self._json(['exec',self._cid('postgres'),'psql','-X','-q','-A','-t','-w','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c','BEGIN READ ONLY;SET LOCAL statement_timeout=3000;SELECT row_to_json(m) FROM public.maintenance_control m WHERE id=1;ROLLBACK;'])
        c=self.plan['candidate']
        require(isinstance(value,dict) and set(value)=={'id','epoch','deployment_id','generation','owner','image_ids','deadline','admission_closed','consumer_blocked'} and type(value['id']) is int and value['id']==1 and type(value['generation']) is int,'complete current ownership required')
        require(value['epoch']==self.plan['operation_id'] and value['deployment_id']==c['deployment_id'] and value['generation']==c['generation'] and value['owner']==c['owner'] and value['image_ids']==c['image_ids'] and value['admission_closed'] is True and value['consumer_blocked'] is True and utc(value['deadline'])==utc(self.plan['expires_at']) and utc(self.clock())<utc(value['deadline']),'current deployment no longer held behind original barrier')
        return value

    def _candidate_rows(self):
        cohort=self._candidate_cohort();info=self._json(['info','--format','{{json .}}']);require(isinstance(info,dict) and info.get('ID')==self.config['daemon_id'],'Docker daemon drift')
        raw=self._bytes(self._run(['ps','--all','--no-trunc','--filter','label=com.docker.compose.project='+self.config['project'],'--format','{{.ID}}']));ids=raw.decode().splitlines()
        require(len(ids)<=16 and len(ids)==len(set(ids)) and all(hash_value(v) for v in ids),'bounded complete release census required')
        fmt=INSPECT_FORMAT[:-1]+',"release_operation":{{json (index .Config.Labels "myink.pi.release.operation")}}}'
        raw=self._bytes(self._run(['inspect','--format',fmt,*ids]));rows=[strict_json(v) for v in raw.splitlines() if v]
        require(len(rows)==len(ids) and {r.get('id') for r in rows}==set(ids),'incomplete adopted Docker inspect')
        expected={r['id']:r for r in [*self.plan['legacy']['containers'],*cohort]};result=[];new={r['id'] for r in cohort}
        for r in rows:
            require(set(r)=={'id','image_id','project','service','running','exit_code','oom','ports','release_operation'} and r['project']==self.config['project'] and type(r['running']) is bool and type(r['exit_code']) is int and r['oom'] is False,'typed complete adopted container required')
            if r['service']=='myink-migrate' and not r['running'] and r['exit_code']==0:continue
            require(r['id'] in expected and r['service'] in SERVICES and SERVICES[r['service']]==expected[r['id']]['service'] and r['image_id']==expected[r['id']]['image_id'],'adopted cohort superseded')
            if r['id'] in new:require(r['release_operation']==self.plan['operation_id'],'adopted container owner drift')
            elif SERVICES[r['service']] in ('api','worker'):require(not r['running'] and r['exit_code']==0,'retained legacy process restarted')
            else:require(r['running'],'product infrastructure stopped')
            if r['service']=='myink-api':
                require(isinstance(r['ports'],(dict,type(None))),'typed API ports required')
                for bindings in (r['ports'] or {}).values():
                    require(bindings is None or isinstance(bindings,list),'typed API bindings required')
                    for b in bindings or []:require(b.get('HostIp') in ('127.0.0.1','::1'),'public API bypasses fence')
            result.append(r)
        require({r['id'] for r in result}==set(expected),'adopted cohort incomplete');return result

    def inspect_candidate(self,plan):
        self.authorize(plan);require(plan==self.plan,'candidate plan drift');rows=self._candidate_rows();self._candidate_state()
        manifest=_pinned(self.config['candidate_manifest_path'],self.config['candidate_manifest_sha256'],self.config['mode']=='ACTUAL')
        require(isinstance(manifest,dict) and set(manifest)=={'source_commit','files'} and manifest['source_commit']==plan['candidate']['commit_sha'],'frozen adopted source required');new={r['id'] for r in self._candidate_cohort()}
        for row in rows:
            if row['id'] in new:require(self._source_files(row['id'])==manifest['files'],'adopted physical source drift')
        self._candidate_rows();self._candidate_state();return deepcopy(plan['candidate'])

    def backup_container_id(self,phase,role):
        require(phase in ('PRE','POST') and role in ('api','postgres','frontend'),'fixed recovery role required')
        if phase=='POST' and role=='api':return next(r['id'] for r in self._candidate_cohort() if r['service']=='api')
        return self._cid(role)

    def measure_candidate_quiet(self,plan,proofs):return self.measure_quiet(plan,proofs,candidate=True)

    def _cid(self,role):return next(r['id'] for r in self.plan['legacy']['containers'] if r['service']==role)

    def _caddy(self):return self._json(['exec',self._cid('frontend'),'/usr/bin/curl','-fsS','http://127.0.0.1:2019/config/'])

    def _close_ingress(self,plan):
        rows=self._rows();require(all(r['running'] for r in rows),'legacy services already interrupted')
        baseline=self._caddy();closed=deepcopy(baseline)
        servers=closed.get('apps',{}).get('http',{}).get('servers');require(isinstance(servers,dict) and servers,'HTTP ingress unavailable')
        for server in servers.values():
            require(isinstance(server,dict) and isinstance(server.get('routes'),list),'unreviewed HTTP route structure')
            server['routes'].insert(0,dict(match=[dict(path=['/api','/api/*'])],handle=[dict(handler='static_response',status_code=503,headers={'Retry-After':['60']},body='Maintenance in progress')],terminal=True))
        _save(self.root/'maintenance-start.json',dict(plan_sha256=digest(plan),started_at=self.clock().isoformat()))
        _save(self.root/'ingress-before.json',baseline);_save(self.root/'ingress-closed.json',closed)
        target='/tmp/myink-pi-maintenance-'+plan['operation_id']+'.json'
        self._run(['cp',str(self.root/'ingress-closed.json'),self._cid('frontend')+':'+target])
        self._run(['exec','--user','0',self._cid('frontend'),'chown','10001:10001',target])
        self._run(['exec',self._cid('frontend'),'caddy','validate','--config',target])
        self._run(['exec',self._cid('frontend'),'caddy','reload','--config',target])
        observed=self._caddy();require(digest(observed)==digest(closed),'ingress reload unconfirmed')
        result=dict(verified=True,plan_sha256=digest(plan),fence_sha256=digest(observed));_save(self.root/'ingress-fence.json',result);return result

    def _drain_legacy(self,plan,proofs):
        fence=strict_json((self.root/'ingress-fence.json').read_bytes());require(proofs.get('close_ingress')==fence and digest(self._caddy())==fence['fence_sha256'],'current ingress fence required')
        api=self._cid('api');workers=[r['id'] for r in plan['legacy']['containers'] if r['service']=='worker']
        # Stop admission first, retaining consumers until existing work settles.
        # Docker --timeout -1 never escalates to SIGKILL; a CLI timeout is uncertain.
        def stop(cid):
            self._run(['stop','--signal','SIGTERM','--timeout','-1',cid],seconds=self.config['drain_seconds'])
            row=next(r for r in self._rows() if r['id']==cid)
            require(not row['running'] and row['exit_code']==0 and not row['oom'],'legacy process did not exit naturally')
        stop(api)
        deadline=time.monotonic()+self.config['drain_seconds']
        while True:
            self.authorize(plan);rows={r['id']:r for r in self._rows()}
            require(all(rows[cid]['running'] and not rows[cid]['oom'] for cid in workers),'legacy consumers stopped before drain')
            require(digest(self._caddy())==fence['fence_sha256'],'ingress fence changed during drain')
            counts=self._drain_counts()
            require(digest(self._caddy())==fence['fence_sha256'],'ingress fence changed during drain')
            if not any(counts[k] for k in ('active_tasks','ready_messages','unacked_messages','unknown','task_locks','book_locks')):break
            require(time.monotonic()<deadline,'legacy backlog did not settle; consumers retained')
            time.sleep(min(.25,max(0,deadline-time.monotonic())))
        for cid in workers:stop(cid)
        return self.measure_quiet(plan,proofs)

    def read_redis_locks(self):
        # The fixed script reads the container's existing secret. No credential
        # enters the host argv, command intent, public audit or model context.
        script='test -n "$REDIS_PASSWORD" || exit 64; REDISCLI_AUTH="$REDIS_PASSWORD" exec redis-cli --no-auth-warning --raw EVAL_RO "$1" 0'
        value=self._json(['exec',self._cid('redis'),'/bin/sh','-c',script,'--',DRAIN_REDIS])
        require(isinstance(value,dict) and set(value)=={'task_locks','book_locks'} and all(type(v) is int and v>=0 for v in value.values()),'complete authenticated lock census required')
        return value

    def measure_quiet(self,plan,proofs,*,candidate=False):
        self.authorize(plan)
        fence=strict_json((self.root/'ingress-fence.json').read_bytes())
        require(proofs.get('close_ingress')==fence and digest(self._caddy())==fence['fence_sha256'],'current ingress fence required')
        rows={r['id']:r for r in (self._candidate_rows() if candidate else self._rows())}
        cohort=self._candidate_cohort() if candidate else plan['legacy']['containers']
        ids=[next(r['id'] for r in cohort if r['service']=='api'),*[r['id'] for r in cohort if r['service']=='worker']]
        if candidate:self._candidate_state()
        require(all(not rows[cid]['running'] and rows[cid]['exit_code']==0 and not rows[cid]['oom'] for cid in ids),'legacy processes not quiet')
        exits=[rows[cid]['exit_code'] for cid in ids]
        counts=self._drain_counts()
        require(digest(self._caddy())==fence['fence_sha256'],'ingress fence changed during drain')
        if candidate:self._candidate_rows();self._candidate_state()
        return dict(verified=True,plan_sha256=digest(plan),fence_sha256=fence['fence_sha256'],api_exit_code=exits[0],worker_exit_codes=exits[1:],**counts)

    def _drain_counts(self):
        pg=self._json(['exec',self._cid('postgres'),'psql','-X','-q','-A','-t','-w','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',DRAIN_SQL])
        require(isinstance(pg,dict) and set(pg)=={'active_tasks','unknown'} and all(type(v) is int and v>=0 for v in pg.values()),'complete legacy database census required')
        redis=self.read_redis_locks()
        require(isinstance(redis,dict) and set(redis)=={'task_locks','book_locks'} and all(type(v) is int and v>=0 for v in redis.values()),'complete legacy lock census required')
        queues=self._json(['exec',self._cid('rabbitmq'),'rabbitmqctl','list_queues','name','messages_ready','messages_unacknowledged','consumers','--formatter','json','--quiet'])
        expected={name+self.config['queue_prefix'] for name in ('queue:tasks','queue:tasks:vip','queue:delay','queue:delay:vip','queue:dlq')}
        require(isinstance(queues,list) and len(queues)<=10000,'bounded complete broker census required');names=set();ready=unacked=consumers=unknown=0
        for row in queues:
            require(isinstance(row,dict) and set(row)=={'name','messages_ready','messages_unacknowledged','consumers'} and isinstance(row['name'],str) and len(row['name'])<=256 and row['name'] not in names and all(type(row[k]) is int and row[k]>=0 for k in ('messages_ready','messages_unacknowledged','consumers')),'typed broker queue required');names.add(row['name'])
            if row['name'] in expected:ready+=row['messages_ready'];unacked+=row['messages_unacknowledged'];consumers+=row['consumers']
            elif any(row[k] for k in ('messages_ready','messages_unacknowledged','consumers')):unknown+=1
        require(expected<=names,'original broker queue missing')
        return dict(active_tasks=pg['active_tasks'],ready_messages=ready,unacked_messages=unacked,consumers=consumers,unknown=pg['unknown']+unknown,**redis)

    def perform(self,action,plan,proofs):
        require(action in STEPS,'unknown product action');self.authorize(plan)
        parent=self.ledger.get(plan['operation_id']);step=self.ledger.get(plan['operation_id']+':'+action)
        require(parent and parent['kind']=='product_bootstrap' and parent['status']=='pending' and parent['payload']==dict(plan_sha256=digest(plan)) and step and step['kind']=='product_bootstrap_step' and step['status']=='pending' and step['payload']==dict(plan_sha256=digest(plan),action=action),'original durable bootstrap step required')
        if action=='close_ingress' and self.config['mode']=='ACTUAL':self.preflight()
        self.inspect(plan)
        claim=self.root/'actions'/action;claim.mkdir(mode=0o700);_save(claim/'intent.json',dict(action=action,plan_sha256=digest(plan)))
        if action=='close_ingress':result=self._close_ingress(plan)
        elif action=='drain_legacy':result=self._drain_legacy(plan,proofs)
        else:
            from .product_backup import LinuxProductBackup
            backend=LinuxProductBackup(self)
            result=backend.perform(action,plan,proofs)
        _save(claim/'receipt.json',result);return result

    def apply_schema(self,plan,proofs):
        from .product_migration import NativeProductMigration
        return NativeProductMigration(self).install(plan,proofs)

    def bind_identity(self,plan,proofs):
        from .product_migration import NativeProductMigration
        return NativeProductMigration(self).bind(plan,proofs)
