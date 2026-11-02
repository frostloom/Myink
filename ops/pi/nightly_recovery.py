"""Settle only a proved unadmitted no-data preparation, retaining its failure."""
from pathlib import Path
import os,stat,fcntl
from .audit import _path,_plain,require,digest,strict_json
from .development_inputs import ledger_snapshot,file_hash
from .nightly_gate import BASE
from .nightly_source import writing_count
from .preexec_reconciliation import verified,_json
from .product_commands import _write

ROOT_FILES=('start.json','admission-intent.json','admission.json','failure.json','source-stage.json','source-metrics.json')


def inspect(gate,cycle,root,claim):
    root=_path(root);claim=_path(claim)
    require(root.name==cycle and root.is_dir() and stat.S_IMODE(root.stat().st_mode)==0o700,'original private nightly round required')
    if gate.mode=='ACTUAL':require(os.geteuid()==0 and root==BASE/'nightly'/cycle and claim.parent==BASE/'autonomy','fixed root recovery scope required')
    else:require(not root.is_relative_to(BASE),'isolated recovery required')
    require(gate.status()['cycle_id']==cycle and gate.status()['phase']=='blocked','current blocked preparation required')
    with gate._connection() as db:
        row=gate._row(db,cycle);require(row['phase']=='blocked' and all(row[k] is None for k in ('task_id','package','approval','deployment')),'no task or candidate may be recovered as empty')
    require(not any((root/n).exists() for n in ('selected.json','manager-intent.json','manager-start.json','bundle')),'possible original work retained')
    require(verified(claim,gate.mode),'verified historical preexec reconciliation required')
    cert=_json(claim/'preexec-reconciliation.json');fee=ledger_snapshot(gate.billing);manager=ledger_snapshot(gate.state)
    require(fee['sha256']==cert['proof']['before_fee_sha256'] and manager['sha256']==cert['proof']['manager_sha256'],'accounting changed since no-effect proof')
    failure=_json(root/'failure.json');admission=_json(root/'admission.json');stage=_json(root/'source-stage.json');metrics=_json(root/'source-metrics.json')
    require(failure==dict(status='blocked',failure_class='ValueError',model_replay=False) and admission==dict(schema='pi-autonomy-coordinator-tick-v1',mode=gate.mode,status='uncertain',model_requests=0),'known unadmitted coordinator stop required')
    require(stage['schema']=='pi-nightly-source-stage-v1' and stage['cycle_id']==cycle and stage['fee_sha256']==fee['sha256'] and stage['metrics_sha256']==digest(metrics),'original frozen source stage required')
    require(metrics['schema']=='pi-live-observer-result-v1' and metrics['mode']==gate.mode and metrics['status']=='insufficient_evidence' and type(metrics['observed_samples']) is int and metrics['observed_samples']==0,'verified empty metric result required')
    profile_path=_path(stage['profile']['path']);require(file_hash(profile_path)==stage['profile']['sha256'],'original finite profile changed');profile=_json(profile_path)
    observer_path=_path(profile['observer']['observer_config_path']);require(file_hash(observer_path)==profile['observer']['observer_config_sha256'],'original observer changed');observer=_json(observer_path)
    if gate.mode=='ACTUAL':require(profile_path==BASE/'config/nightly-source-profiles'/(cycle+'.json') and profile_path.stat().st_uid==0,'root-issued finite profile required')
    require(writing_count(metrics,observer,gate.mode)==0,'writing tasks exist or workload is unknown')
    files=[root/n for n in ROOT_FILES]+[profile_path,observer_path,claim/'preexec-reconciliation.json']
    if gate.mode=='ACTUAL':files.append(_path(observer['root'])/metrics['run_id']/'metrics.json')
    return dict(classification='unadmitted_empty_writing_preparation',root=str(root),claim=str(claim),fee_sha256=fee['sha256'],manager_sha256=manager['sha256'],inputs={str(p):file_hash(p) for p in files})


def validated(gate,cycle,path,pin,*,current=True):
    path=_path(path);root=path.parent.parent;_plain(path)
    require(path==root/'recovery/verified.json' and root.name==cycle and file_hash(path)==pin and path.stat().st_uid==(0 if gate.mode=='ACTUAL' else os.geteuid()) and stat.S_IMODE(path.stat().st_mode)==0o600,'root verified recovery receipt required')
    if gate.mode=='ACTUAL':require(os.geteuid()==0 and root==BASE/'nightly'/cycle and path.parent.stat().st_uid==0 and stat.S_IMODE(path.parent.stat().st_mode)==0o700,'fixed root recovery output required')
    v=_json(path);require(set(v)=={'schema','mode','cycle_id','proof','proof_sha256'} and v['schema']=='pi-nightly-preparation-recovery-v1' and v['mode']==gate.mode and v['cycle_id']==cycle and digest(v['proof'])==v['proof_sha256'] and v['proof']['root']==str(root),'closed verified recovery required')
    require(all(file_hash(_path(p))==h for p,h in v['proof']['inputs'].items()),'original recovery inputs changed')
    if current:require(inspect(gate,cycle,root,Path(v['proof']['claim']))==v['proof'],'recovery proof drift')
    return v


def recover(gate,cycle,root,claim):
    # The canonical two locks exclude the nightly caller and root admission.
    root=_path(root)
    if gate.mode=='ACTUAL':locks=[BASE/'control/nightly.lock',BASE/'control/maintenance.lock']
    else:
        locks=[root.parent/'nightly.lock',root.parent/'maintenance.lock']
        for p in locks:
            if not p.exists():p.touch(mode=0o600)
    with locks[0].open('rb') as nightly,locks[1].open('rb') as maintenance:
        for stream in (nightly,maintenance):fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        folder=root/'recovery';receipt=folder/'verified.json'
        if folder.exists():
            require(receipt.exists(),'unfinished recovery retained; no replay')
            gate.reconcile_no_release(cycle,receipt,file_hash(receipt));return dict(status='no_release',cycle_id=cycle,model_requests=0)
        proof=inspect(gate,cycle,root,claim);folder.mkdir(mode=0o700);_write(folder/'intent.json',dict(proof_sha256=digest(proof)))
        from .nightly_outcome import publish
        publish(gate,cycle,root,'no_writing_data',recovered=True)
        require(inspect(gate,cycle,root,claim)==proof,'recovery inputs changed during audit')
        v=dict(schema='pi-nightly-preparation-recovery-v1',mode=gate.mode,cycle_id=cycle,proof=proof,proof_sha256=digest(proof));_write(receipt,v)
        gate.reconcile_no_release(cycle,receipt,digest(v));return dict(status='no_release',cycle_id=cycle,model_requests=0)
