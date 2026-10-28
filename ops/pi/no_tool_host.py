"""Shared single-request SDK lifecycle for fixed host-selected no-tool roles."""
from dataclasses import asdict,replace
from datetime import datetime,timezone
from pathlib import Path
from threading import Timer
import fcntl,json,os,time,uuid
from hashlib import sha256
from .audit import encoded,digest,require,strict_json,utc
from .development_inputs import path,file_hash,ledger_snapshot
from .development_launcher import Limits,OwnedHosts,PolicyLease,_exchange,_host,_provider,atomic_write
from .selection_launcher import NoToolBridge,PhaseCancel,verify_selection
from .ledger import Ledger
from .provider_config import load_credentials
from .diagnosis_launcher import _unknown


def _contract(role):
    require(role=='independent_review','fixed no-tool role required')
    from . import sdk_review_launcher
    return sdk_review_launcher


def execute(config_path,*,transport=None,clock=None,expected_config_sha256=None):
    raw=path(config_path,private=True).read_bytes();c=strict_json(raw)
    require(c.get('mode') in ('ACTUAL','SIMULATED'),'explicit no-tool mode required')
    require(c['mode']!='ACTUAL' or transport is None and clock is None and expected_config_sha256 is not None,'ACTUAL forbids injected transport/clock and requires config pin')
    require(c['mode']!='SIMULATED' or callable(transport),'SIMULATED requires explicit transport')
    config_sha=sha256(raw).hexdigest();require(expected_config_sha256 is None or expected_config_sha256==config_sha,'no-tool config pin drift')
    contract=_contract(c.get('role'));prepared=contract.prepare(config_path,clock=clock);frozen=digest(prepared[0]);c=prepared[0]
    lock_path=Path(c['ledger_path']).with_suffix('.tools.lock');require(not lock_path.is_symlink())
    with lock_path.open('a+b') as lock:
        os.chmod(lock_path,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        c,policy,material,permit,before,provenance=contract.prepare(config_path,clock=clock)
        require(digest(c)==frozen and file_hash(config_path)==config_sha,'no-tool config changed while locking')
        root=Path(c['root']);root.mkdir(mode=0o700);fd=os.open(root.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        def write(name,value):
            p=root/name;require(not p.exists(),'no-tool evidence reused');atomic_write(p,encoded(value)+b'\n')
            directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:os.fsync(directory)
            finally:os.close(directory)
        write('intent.json',dict(role=c['role'],config_sha256=config_sha,input_sha256=contract.input_hash(c,material)))
        cancel=PhaseCancel();limits=Limits(1,0,c['deadline_seconds'],cancel);owners=OwnedHosts(cancel,write);timer=Timer(c['deadline_seconds'],cancel.set);timer.daemon=True;timer.start()
        original=Path(c['policy_path']).read_bytes();bridge=None;after=None
        result=dict(schema='pi-no-tool-result-v1',role=c['role'],mode=c['mode'],run_id=c['run_id'],input_sha256=contract.input_hash(c,material),executable_approval=False,verified=False,execution_verified=False,contract_valid=False,closed_verified=False,cleanup=[],policy_restored=False,credential_unchanged=False,original_history_unchanged=False,new_attempts=0,new_unknown=0,known_cost_microyuan=0)
        try:
            host=owners.add(_host(c,'image_id',provenance['machine']));write('manifest-private.json',dict(config=c,permit=permit,provenance=provenance));write('ledger-before-private.json',before)
            initial=dict(model_token=uuid.uuid4().hex,model=policy.model,max_tokens=policy.max_tokens,system=contract.SYSTEM,prompt=contract.prompt(c,material),context_hash=contract.input_hash(c,material),config_hash=frozen,deadline=time.time()+max(0,limits.deadline-time.monotonic()))
            write('initial-private.json',initial)
            ledger=Ledger(Path(c['ledger_path']),existing=True);live=replace(policy,live_enabled=True);enabled=json.dumps(asdict(live),indent=2).encode()+b'\n'
            def guard():
                require(file_hash(config_path)==config_sha,'no-tool config revoked')
                require(Path(c['policy_path']).read_bytes()==enabled,'owned no-tool policy revoked')
                require(ledger_snapshot(c['ledger_path'])['sha256']==before['sha256'],'no-tool billing changed before request')
                contract.check_live(c,material,permit,clock=clock)
            bridge=NoToolBridge(live,ledger,limits,initial['model_token'],initial,write,before_forward=guard)
            credentials=load_credentials(c['credential_path'],policy)
            with PolicyLease(Path(c['policy_path']),original,enabled):
                if transport is None:
                    with _provider(live,credentials) as send:frame=_exchange(host,c,initial,bridge,send,limits,write,worker='selection.py')
                else:frame=_exchange(host,c,initial,bridge,transport,limits,write,worker='selection.py')
            proof=verify_selection(frame,initial,bridge.request);write('verification.json',proof);result['execution_verified']=True
            try:result['report']=contract.validate_output(strict_json(proof['text']),c,material);result['contract_valid']=True
            except (ValueError,TypeError):result['output_failure']='invalid_no_tool_role_contract'
        except Exception as error:result['failure_class']=type(error).__name__
        finally:
            cancel.set();timer.cancel()
            try:result['cleanup']=owners.finish()
            except Exception as error:result['cleanup_failure_class']=type(error).__name__
            for key,operation in (('policy_restored',lambda:Path(c['policy_path']).read_bytes()==original),('credential_unchanged',lambda:file_hash(c['credential_path'])==c['credential_sha256'])):
                try:result[key]=operation()
                except Exception as error:result[key]=False;result[key+'_failure_class']=type(error).__name__
            try:
                after=ledger_snapshot(c['ledger_path']);write('ledger-after-private.json',after);old={r['operation_id']:r for r in before['operations']};current={r['operation_id']:r for r in after['operations']};new=[r for k,r in current.items() if k not in old]
                result['original_history_unchanged']=all(current.get(k)==v for k,v in old.items()) and after['events'][:len(before['events'])]==before['events'] and after['limits']==before['limits'] and all(r['kind']=='model-attempt' for r in new)
                result['new_attempts']=len([r for r in new if r['kind']=='model-attempt']);result['new_unknown']=len(_unknown(after)-_unknown(before));result['known_cost_microyuan']=sum(strict_json(r['evidence'] or '{}').get('charged_microyuan',0) for r in new if r['kind']=='model-attempt' and r['status']=='done')
            except Exception as error:result['billing_audit_failure_class']=type(error).__name__
            try:
                require(file_hash(config_path)==config_sha,'no-tool config changed during execution')
                checked=contract.prepare(config_path,clock=clock,fresh=False,expected_fee_sha256=after['sha256'] if after else None)
                require(digest(checked[0])==frozen and contract.input_hash(c,checked[2])==result['input_sha256'],'no-tool input drift after execution')
            except Exception as error:result['input_audit_failure_class']=type(error).__name__
            result['closed_verified']=bool(result['execution_verified'] and result['policy_restored'] and result['credential_unchanged'] and result['original_history_unchanged'] and result['new_attempts']==1 and result['new_unknown']==0 and result['cleanup'] and all(r.get('removed') is True for r in result['cleanup']) and not owners.failed and time.monotonic()<limits.deadline and not any(k.endswith('failure_class') for k in result))
            result['verified']=result['closed_verified'] and result['contract_valid'];result['model_posts']=bridge.posts if bridge else []
            try:contract.publish_audit(c,material,result,utc((clock or (lambda:datetime.now(timezone.utc)))()))
            except Exception as error:result['audit_failure_class']=type(error).__name__;result['verified']=False
            write('result.json',result)
        return result
