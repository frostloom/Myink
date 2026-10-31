"""Finite external review tick. No model calls and no maintenance lock acquisition."""
from pathlib import Path
from .audit import _path,require,digest
from .development_inputs import file_hash,read_json
from .manager_handoff import FIELDS
from .review_lease import _read,_directory,load_policy,policy_record
from . import selection_binding,review_publisher

RECEIPT=set('schema status model_requests request_sha256 manifest_sha256 manifest_path cycle_sha256 cycle_path bundle_path template_path lease_path lease_sha256'.split())


def _completed(request_path,pin,clock,*,historical=False):
    q,h=_read(request_path,65536)
    require(h==pin and isinstance(q,dict) and set(q)==FIELDS and q['schema']=='pi-reviewed-manager-handoff-v1','pinned original handoff request required')
    root=_directory(q['root']);r,_=_read(root/'receipt.json',65536)
    require(isinstance(r,dict) and set(r)==RECEIPT and r['schema']=='pi-reviewed-manager-handoff-result-v1' and r['status']=='published' and type(r['model_requests']) is int and r['model_requests']==0 and r['request_sha256']==pin,'completed handoff required; never replay partial publication')
    expected=dict(manifest_path=_path(q['inbox'])/(q['task_id']+'.task.json'),cycle_path=root/'bundle/cycle.json',bundle_path=root/'bundle/bundle.json',template_path=root/'development-template.json')
    require(all(_path(r[k])==v for k,v in expected.items()),'handoff output custody drift')
    manifest,mh=_read(r['manifest_path']);cycle,ch=_read(r['cycle_path'])
    require(mh==r['manifest_sha256'] and ch==r['cycle_sha256'] and manifest==dict(schema='pi-manager-admission-v1',task_id=q['task_id'],request_path=r['cycle_path'],request_sha256=ch,priority=q['priority'],mode=q['mode']),'handoff manifest/cycle drift')
    require(cycle['cycle_id']==q['cycle_id'] and _path(cycle['selection_config_path'])==root/'bundle/selection-reviewed.json','selection outside sealed handoff')
    sp=_path(cycle['selection_config_path']);sc,sh=_read(sp)
    require(sh==cycle['selection_config_sha256'] and sc['run_id']==q['selection_run_id'] and _path(sc['root'])==root/'bundle/selection-output','sealed selection drift')
    require(file_hash(sc['catalog_path'])==sc['catalog_sha256'],'sealed catalog drift')
    parent,lh=_read(r['lease_path']);require(lh==r['lease_sha256'] and parent['schema']=='pi-review-lease-record-v1' and parent['policy_path']==q['issuer_policy_path'] and parent['policy_sha256']==q['issuer_policy_sha256'] and parent['review_config_path']==q['review_config_path'] and parent['review_config_sha256']==q['review_config_sha256'],'original handoff lease drift')
    p=policy_record(q['issuer_policy_path'],q['issuer_policy_sha256']) if historical else load_policy(q['issuer_policy_path'],q['issuer_policy_sha256'],clock)[0]
    require(p['mode']==q['mode'] and _path(p['prepared_parent'])==root/'bundle/cycle-output/prepared','handoff policy/mode drift')
    if q['mode']=='ACTUAL':
        from .manager_handoff import BASE
        require(clock is None and _path(q['manager_state'])==BASE/'state/actual-manager.sqlite' and _path(q['inbox'])==BASE/'inbox','original actual manager required')
    return q,r,p,sp,sh,sc


def _terminal(q,r,p,sp,sh,sc):
    base=_path(r['lease_path']).parent;binding=base/'binding';abstention=base/'abstention'
    def status(value,**extra):return dict(status=value,model_requests=0,**extra)
    # Completed host receipts are immutable observations, not authority to rerun a
    # phase. In particular, do not fresh-prepare a candidate which already started.
    if (binding/'publication').exists():
        claim=binding/'publication'
        if not (claim/'receipt.json').exists():return status('uncertain',phase='publication')
        receipt=_read(claim/'receipt.json')[0];intent=_read(claim/'intent.json')[0]
        bound,bh=_read(binding/'lease.json');cp=_path(p['prepared_parent'])/read_json(Path(sc['catalog_path']))[0]['task_id']/'config.json'
        config,config_sha=_read(cp);review=cp.parent/'review-request.json';original=_read(claim/'config-private.json')[0]
        require(digest(original)==intent['config_data_sha256'] and digest(dict(config,review_sha256=original['review_sha256']))==digest(original) and config['review_sha256'] in (original['review_sha256'],receipt['approval_sha256']),'completed prepared scope drift')
        require(receipt['schema']=='pi-review-publication-result-v1' and receipt['status']=='published' and receipt['lease_sha256']==bh==intent['lease_sha256'] and file_hash(review)==intent['request_sha256'] and file_hash(config['review_path'])==receipt['approval_sha256'],'completed review publication drift')
        return status('published',cached=True,approval_sha256=receipt['approval_sha256'])
    if abstention.exists():
        if not (abstention/'receipt.json').exists():return status('uncertain',phase='abstention')
        receipt=_read(abstention/'receipt.json')[0]
        require(receipt['schema']=='pi-selection-abstention-result-v1' and receipt['status']=='no_action' and receipt['parent_sha256']==r['lease_sha256'] and receipt['selection_config_sha256']==sh,'abstention receipt drift')
        for name,pin in receipt['artifact_pins'].items():require(file_hash(Path(sc['root'])/name)==pin,'abstention artifacts drift')
        return status('no_action',cached=True)
    if binding.exists() and not (binding/'receipt.json').exists():return status('uncertain',phase='binding')
    return None


def inspect_terminal(request_path,request_sha256,*,clock=None):
    """Authenticate immutable terminal facts only; never bind or publish permission."""
    return _terminal(*_completed(request_path,request_sha256,clock,historical=True))


def tick(request_path,request_sha256,*,clock=None):
    q,r,p,sp,sh,sc=_completed(request_path,request_sha256,clock,historical=True)
    terminal=_terminal(q,r,p,sp,sh,sc)
    if terminal is not None:return terminal
    load_policy(q['issuer_policy_path'],q['issuer_policy_sha256'],clock)
    base=_path(r['lease_path']).parent;binding=base/'binding'
    def status(value,**extra):return dict(status=value,model_requests=0,**extra)
    if not (Path(sc['root'])/'result.json').exists():return status('waiting_selection')
    try:
        if not binding.exists():
            selection_binding.inspect(r['lease_path'],r['lease_sha256'],sp,sh,clock=clock,require_task=False)
            result=_read(Path(sc['root'])/'result.json')[0]
            if result['proposal']['task_id'] is None:
                selection_binding.abstain(r['lease_path'],r['lease_sha256'],sp,sh,clock=clock)
                return status('no_action',cached=False)
            selection_binding.bind(r['lease_path'],r['lease_sha256'],sp,sh,clock=clock)
        bound,bh=_read(binding/'lease.json');receipt=_read(binding/'receipt.json')[0]
        require(receipt['schema']=='pi-selection-binding-result-v1' and receipt['status']=='bound' and receipt['lease_sha256']==bh and receipt['selection_config_sha256']==sh,'incomplete binding')
        task=read_json(Path(sc['root'])/'result.json')['proposal']['task_id'];catalog=read_json(sc['catalog_path'])
        require(task is not None and task in {t['task_id'] for t in catalog},'unknown selected task')
        cp=_path(p['prepared_parent'])/task/'config.json'
        if not cp.exists() or not (cp.parent/'review-request.json').exists():return status('waiting_prepared')
        result=review_publisher.publish(binding/'lease.json',bh,cp,clock=clock)
        return status('published',cached=False,approval_sha256=result['approval_sha256'])
    except BlockingIOError:
        return status('waiting_lock')
