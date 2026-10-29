"""Fixed native release/return sequencing. Never a model or HTTP tool.

This layer proves native admission only. Business execution, long observation,
checkpoint adoption and effective-configuration recovery have separate gates.
"""
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
import time
import os,stat

from . import backup
from .audit import _plain,digest,encoded,hash_value,require,strict_json,utc
from .contracts import Receipt
from .product_activation import NativeActivation
from .product_backup import LinuxProductBackup
from .product_bootstrap import _facts
from .product_restore import OwnedPostgresRestore
from .product_runtime import _pinned,_save

ACTIONS=('activate','rollback')
FIELDS=set('schema mode target plan_sha256 context_path context_sha256 activation_approval_path activation_approval_sha256 ingress_before_sha256 maximum_stopped_seconds expires_at'.split())
STEPS={'candidate','references-pre','installed','post','references-post','start','business','stop-validation','start-admission','open','close','drain','stop','return','start-return','open-return'}


def _literal(value):return "'"+str(value).replace("'","''")+"'"


def _preflight_recovery(ledger,pair_id,context,now):
    # A fresh operation cannot hide an older published POST debt. No recovery
    # waiver is used, and no incomplete collection is dropped from inventory.
    rows=[*backup._records(ledger,'release'),*backup._records(ledger,'backup')]
    require(len(rows)<=10000,'bounded historical recovery census required')
    if rows:require(backup.release_allowed(ledger,pair_id,context=context,now=now),'historical recovery debt or qualification blocks maintenance')


class NativeProductRelease:
    def __init__(self,host,config_path,config_sha256,approval_path,approval_sha256):
        self.host=host;self.plan=host.plan;self.config_path=Path(config_path);self.pin=config_sha256
        self.approval_path=Path(approval_path);self.approval_pin=approval_sha256;self._active=None
        actual=host.config['mode']=='ACTUAL'
        if actual:
            from .product_runtime import LinuxProductHost
            require(type(host) is LinuxProductHost,'canonical release host required')
        else:require(host.config['target']=='rehearsal','simulation cannot release production')
        c=_pinned(config_path,config_sha256,actual);self.config=c
        business=isinstance(c,dict) and c.get('schema')=='pi-product-control-v2'
        require(isinstance(c,dict) and set(c)==(FIELDS|{'business_probe_path','business_probe_sha256'} if business else FIELDS) and c['schema'] in ('pi-product-control-v1','pi-product-control-v2') and c['mode']==host.config['mode'] and c['target']==host.config['target'] and c['plan_sha256']==digest(self.plan) and (not actual or business),'closed qualified native release settings required')
        self.business_mode=business
        require(type(c['maximum_stopped_seconds']) is int and 0<c['maximum_stopped_seconds']<=1800 and hash_value(c['ingress_before_sha256']),'bounded approved maintenance required')
        self.actor=NativeActivation(host,c['context_path'],c['context_sha256'],c['activation_approval_path'],c['activation_approval_sha256'])
        self.business_probe=None
        if business:
            from .product_business_probe import BusinessReadProbe
            require(self.actor.protocol_version==2,'separate phase authority required')
            self.business_probe=BusinessReadProbe(host,self.actor,c['business_probe_path'],c['business_probe_sha256'])
        self._authority()

    def _authority(self):
        h=self.host;h.authorize(self.plan);actual=h.config['mode']=='ACTUAL'
        require(_pinned(self.config_path,self.pin,actual)==self.config,'native release settings drift')
        a=_pinned(self.approval_path,self.approval_pin,actual)
        require(isinstance(a,dict) and set(a)=={'schema','mode','target','plan_sha256','config_sha256','approved_actions','expires_at'} and a['schema']=='pi-product-control-approval-v1' and a['mode']==h.config['mode'] and a['target']==h.config['target'] and a['plan_sha256']==digest(self.plan) and a['config_sha256']==self.pin,'independent native release approval required')
        require(isinstance(a['approved_actions'],list) and len(a['approved_actions'])==2 and set(a['approved_actions'])==set(ACTIONS),'exact release/return actions required')
        if self.business_mode:
            from .product_business_probe import validate
            require(validate(_pinned(self.config['business_probe_path'],self.config['business_probe_sha256'],actual),self.plan,self.actor.context_pin)==self.business_probe.packet,'business case approval drift')
        self.actor._authority();now=utc(h.clock())
        lease=getattr(h,'rollback_lease',None)
        if lease is not None:
            require(self.business_mode and self.actor.protocol_version==2,'qualified v2 rollback control required')
            from .product_rollback_lease import adopted,deadline
            require(lease['control_sha256']==self.pin and lease['maximum_stopped_seconds']<=self.config['maximum_stopped_seconds'],'independent rollback control binding required');adopted(h)
            if self._active is not None:deadline(h)
            return
        require(now<min(utc(a['expires_at']),utc(self.config['expires_at']),utc(self.plan['expires_at'])),'native release authority expired')
        start=h.root/'maintenance-start.json';_plain(start);require(start.stat().st_size<=1024,'bounded maintenance start required');v=strict_json(start.read_bytes())
        require(set(v)=={'plan_sha256','started_at'} and v['plan_sha256']==digest(self.plan),'original maintenance start required')
        began=utc(v['started_at']);require(began<=now<began+timedelta(seconds=self.config['maximum_stopped_seconds']),'approved maintenance duration exceeded')

    def _operation(self,action,body):
        require(action in ACTIONS and self._active is None,'fixed nonnested product operation required');require(getattr(self.host,'rollback_lease',None) is None or action=='rollback','rollback-only operation required');self._authority();h=self.host
        root=h.root/'native-control';root.mkdir(mode=0o700,exist_ok=True);require(root.is_dir() and not root.is_symlink() and stat.S_IMODE(root.stat().st_mode)==0o700 and root.stat().st_uid==os.geteuid(),'private native control root required');folder=root/action
        try:folder.mkdir(mode=0o700)
        except FileExistsError:raise ValueError('native control already claimed; no redispatch') from None
        op='product-control:'+self.plan['operation_id']+':'+action;payload=dict(plan_sha256=digest(self.plan),config_sha256=self.pin,action=action)
        require(h.ledger.get(op) is None,'original native control intent exists');h.ledger.intent(op,'product_control',payload);_save(folder/'intent.json',payload);self._active=(op,folder)
        try:
            if getattr(h,'rollback_lease',None) is not None:
                from .product_rollback_lease import start_packet
                _save(folder/'start.json',start_packet(h))
            result=body();require(isinstance(result,dict) and result.get('verified') is True,'native result unconfirmed');self._authority()
            _save(folder/'receipt.json',result);h.ledger.finish(Receipt(op,'done',result));return Receipt(op,'done',result)
        except Exception as error:
            h.ledger.finish(Receipt(op,'uncertain',dict(reason='native_control_unconfirmed',error_class=type(error).__name__)));raise
        finally:self._active=None  # Never reopen or redispatch as cleanup.

    def _effect(self,name,body):
        require(name in STEPS and self._active is not None,'fixed native stage required');self._authority();op,folder=self._active;h=self.host;child=op+':'+name
        require(h.ledger.get(op)['status']=='pending' and h.ledger.get(child) is None,'original stage intent required')
        stage=folder/name;stage.mkdir(mode=0o700);payload=dict(plan_sha256=digest(self.plan),config_sha256=self.pin,step=name)
        h.ledger.intent(child,'product_control_step',payload);_save(stage/'intent.json',payload)
        try:
            result=body();require(isinstance(result,dict),'structured native stage result required');self._authority()
            _save(stage/'receipt.json',result);h.ledger.finish(Receipt(child,'done',result));return result
        except Exception as error:
            h.ledger.finish(Receipt(child,'uncertain',dict(reason='native_stage_unconfirmed',error_class=type(error).__name__)));raise

    def _scope(self):
        self._authority();rows=self.actor._scope();net=self.actor._json(['network','inspect',self.actor.context['network']['id']])
        require(isinstance(net,list) and len(net)==1 and isinstance(net[0].get('Containers'),dict) and set(net[0]['Containers']).issubset(rows),'foreign network member supersedes release')
        return rows

    def _prepared(self):
        row=self.host.ledger.get(self.plan['operation_id'])
        require(row and row['kind']=='product_bootstrap' and row['status']=='done' and row['payload']==dict(plan_sha256=digest(self.plan)) and row['evidence'].get('phase')=='protocol_prepared','original prepared bootstrap required')
        proofs=row['evidence']['proofs'];require(set(proofs)=={'close_ingress','drain_legacy','backup_pre','install_schema','bind_identity'},'complete prepared proofs required')
        done={}
        for name in ('close_ingress','drain_legacy','backup_pre','install_schema','bind_identity'):_facts(name,proofs[name],self.plan,done);done[name]=proofs[name]
        self.proofs=proofs;self.backend=LinuxProductBackup(self.host,proofs)
        return proofs

    def _inventory(self,phase):
        rows=backup._records(self.host.ledger,'backup');old=backup._records(self.host.ledger,'recovery_reference_inventory')
        require(len(rows)<=10000 and len(old)<=10000 and all(r['status']=='done' for r in rows),'unknown recovery collection remains')
        ids={r['payload']['backup_id'] for r in rows};prior=set()
        for row in old:
            require(row['status']=='done','unconfirmed recovery inventory remains')
            prior.update(row['payload']['stable_ids']);prior.update(row['payload']['referenced_ids'])
        require(prior.issubset(ids),'historical recovery references lost')
        version=1+max((r['payload']['version'] for r in old),default=0)
        receipt=backup.record_recovery_references(self.host.ledger,'product-references:'+self.plan['operation_id']+':'+phase,version=version,context=self.backend.context,complete=True,stable_ids=sorted(ids),referenced_ids=sorted(prior))
        require(receipt.status=='done' and backup.release_allowed(self.host.ledger,self.plan['operation_id'],context=self.backend.context,now=self.host.clock()),'recovery debt or qualification blocks release')
        return dict(verified=True,inventory_sha256=receipt.evidence['inventory_sha256'])

    def _ingress(self,closed):
        baseline=self.host.root/'ingress-before.json';fence=self.host.root/'ingress-closed.json'
        for p in (baseline,fence):_plain(p);require(p.stat().st_size<=1048576,'bounded original ingress required')
        before=strict_json(baseline.read_bytes());after=strict_json(fence.read_bytes())
        require(digest(before)==self.config['ingress_before_sha256'],'unapproved original ingress configuration')
        require(digest(self.host._caddy())==digest(after if closed else before),'current ingress no longer owned')
        return after if closed else before

    def _reload(self,closed):
        self._scope();self._ingress(not closed);path=self.host.root/('ingress-closed.json' if closed else 'ingress-before.json')
        target='/tmp/myink-pi-control-'+self.plan['operation_id']+('-closed.json' if closed else '-open.json');h=self.host;cid=h._cid('frontend')
        h._run(['cp',str(path),cid+':'+target]);h._run(['exec','--user','0',cid,'chown','10001:10001',target])
        h._run(['exec',cid,'caddy','validate','--config',target]);self._scope();h._run(['exec',cid,'caddy','reload','--config',target]);self._ingress(closed)
        return dict(verified=True,closed=closed)

    def _state(self,role,barriers):
        value=self.actor._json(['exec',self.host._cid('postgres'),'psql','-X','-q','-A','-t','-w','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c','BEGIN READ ONLY;SET LOCAL statement_timeout=3000;SELECT row_to_json(m) FROM maintenance_control m WHERE id=1;ROLLBACK;'])
        identity=self.actor.identity(role);epoch=self.plan['operation_id'] if role=='candidate' else 'rollback-'+self.plan['operation_id']
        require(isinstance(value,dict) and type(value.get('generation')) is int and value.get('id')==1 and value.get('epoch')==epoch and all(value.get(k)==identity[k] for k in ('deployment_id','generation','owner','image_ids')) and utc(value['deadline'])==utc(self.plan['expires_at']) and value.get('admission_closed') is barriers[0] and value.get('consumer_blocked') is barriers[1],'current deployment or barrier superseded')
        return value

    def _transition(self,role,before,after,*,next_role=None):
        self._scope();self._state(role,before);old=self.actor.identity(role);new=self.actor.identity(next_role or role)
        epoch=self.plan['operation_id'] if role=='candidate' else 'rollback-'+self.plan['operation_id'];next_epoch=self.plan['operation_id'] if (next_role or role)=='candidate' else 'rollback-'+self.plan['operation_id']
        checks=['id=1','epoch='+_literal(epoch),'deployment_id='+_literal(old['deployment_id']),'generation='+str(old['generation']),'owner='+_literal(old['owner']),'image_ids::jsonb='+_literal(encoded(old['image_ids']).decode())+'::jsonb','deadline='+_literal(self.plan['expires_at'])+'::timestamptz','admission_closed='+str(before[0]).lower(),'consumer_blocked='+str(before[1]).lower()]
        changes=['epoch='+_literal(next_epoch),'deployment_id='+_literal(new['deployment_id']),'generation='+str(new['generation']),'owner='+_literal(new['owner']),'image_ids='+_literal(encoded(new['image_ids']).decode())+'::json','admission_closed='+str(after[0]).lower(),'consumer_blocked='+str(after[1]).lower()]
        command='BEGIN;SET LOCAL lock_timeout=3000;SET LOCAL statement_timeout=5000;UPDATE maintenance_control SET '+','.join(changes)+' WHERE '+' AND '.join(checks)+' RETURNING row_to_json(maintenance_control);COMMIT;'
        observed=self.actor._json(['exec',self.host._cid('postgres'),'psql','-X','-q','-A','-t','-w','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',command])
        require(isinstance(observed,dict) and observed.get('owner')==new['owner'] and type(observed.get('generation')) is int and observed['generation']==new['generation'],'atomic current-owner transition unconfirmed')
        self._state(next_role or role,after);return dict(verified=True,identity=new,admission_closed=after[0],consumer_blocked=after[1])

    def _installed(self):
        self._scope();self.host.inspect_candidate(self.plan)
        backup.mark_released(self.host.ledger,self.plan['operation_id'],asdict(self.backend.candidate),context=self.backend.context,now=self.host.clock())
        return dict(verified=True,phase='installed_behind_closed_ingress')

    def _post(self):
        self._scope();receipt=backup.create_backup(self.host.ledger,'POST',self.backend.candidate,self.backend,self.backend.collections,pair=self.backend.pair)
        require(receipt.status=='done','POST collection unconfirmed');result=OwnedPostgresRestore(self.backend).restore(receipt,qualification=self.backend.qualification)
        require(result.status=='done','POST application recovery unconfirmed')
        return dict(verified=True,manifest_sha256=receipt.evidence['manifest_sha256'],restore_operation_id=result.operation_id)

    def _open(self,role):
        self._scope();self._ingress(True);self._state(role,(True,True))
        require(backup.release_allowed(self.host.ledger,self.plan['operation_id'],context=self.backend.context,now=self.host.clock()),'paired recovery gate no longer valid')
        result=self._transition(role,(True,True),(False,False));self._reload(False);self._state(role,(False,False));self._scope()
        return dict(result,scope='native_admission_only',business_probe='pending_separate_qualification')

    def _business(self):return self.business_probe.check(self.backend)

    def activate(self):return self._operation('activate',self._activate)

    def _activate(self):
        self._prepared();self._scope();self._ingress(True);self._state('candidate',(True,True))
        self._effect('references-pre',lambda:self._inventory('PRE'))
        self._effect('candidate',lambda:dict(verified=True,containers=self.actor.create('candidate')))
        if self.business_mode:
            self._effect('start',lambda:self.actor.start('candidate'));self._effect('business',self._business)
            self._effect('stop-validation',lambda:self.actor.stop('candidate'))
        self._effect('installed',self._installed);self._effect('post',self._post)
        self._effect('references-post',lambda:self._inventory('POST'))
        if self.business_mode:self._effect('start-admission',self.actor.start_admission)
        else:self._effect('start',lambda:self.actor.start('candidate'))
        result=self._effect('open',lambda:self._open('candidate'))
        return dict(result,phase='native_candidate_open',identity=self.actor.identity('candidate'),business_probe='pending_separate_qualification')

    def _close(self):
        self._scope()
        state=self.actor._json(['exec',self.host._cid('postgres'),'psql','-X','-q','-A','-t','-w','-U','myink','-d','myink','-c','SELECT row_to_json(m) FROM maintenance_control m WHERE id=1'])
        before=(state['admission_closed'],state['consumer_blocked']);require(before in ((False,False),(True,True)),'unreviewed partial control state')
        self._state('candidate',before)  # Reject superseded ownership before touching ingress.
        current=self.host._caddy();closed=strict_json((self.host.root/'ingress-closed.json').read_bytes())
        if digest(current)!=digest(closed):self._reload(True)
        else:self._ingress(True)
        return self._transition('candidate',before,(True,False))

    def _drain(self):
        deadline=time.monotonic()+self.host.config['drain_seconds']
        while True:
            self._authority();self._scope();self._ingress(True);self._state('candidate',(True,False));counts=self.host._drain_counts()
            paused=self.actor._json(['exec',self.host._cid('postgres'),'psql','-X','-q','-A','-t','-w','-U','myink','-d','myink','-c',"BEGIN READ ONLY;SET LOCAL statement_timeout=3000;SELECT json_build_object('unsettled',(SELECT count(*) FROM maintenance_executions WHERE state IN ('paused','pause_requested','interruption_unconfirmed')));ROLLBACK;"])
            require(isinstance(paused,dict) and type(paused.get('unsettled')) is int and paused['unsettled']==0,'paused or uncertain executions require separate verified adoption')
            if not any(counts[k] for k in ('active_tasks','ready_messages','unacked_messages','unknown','task_locks','book_locks')):break
            require(time.monotonic()<deadline,'candidate backlog did not drain; consumers retained');time.sleep(.25)
        return self._transition('candidate',(True,False),(True,True))

    def rollback(self):return self._operation('rollback',self._rollback)

    def _rollback(self):
        self._prepared();self._scope()
        require(backup.release_allowed(self.host.ledger,self.plan['operation_id'],context=self.backend.context,now=self.host.clock()),'unresolved recovery debt blocks native return')
        self._effect('close',self._close);self._effect('drain',self._drain);self._effect('stop',self.actor.stop_admission if self.business_mode else lambda:self.actor.stop('candidate'))
        self._effect('return',lambda:dict(verified=True,containers=self.actor.create('rollback'),transition=self._transition('candidate',(True,True),(True,True),next_role='rollback')))
        self._effect('start-return',lambda:self.actor.start('rollback'));result=self._effect('open-return',lambda:self._open('rollback'))
        return dict(result,phase='native_legacy_return',identity=self.actor.identity('rollback'),original_control_state_restored=False,business_probe='pending_separate_qualification')
