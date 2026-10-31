"""Readonly reauthentication of a completed proposal; no execution permission."""
from pathlib import Path
from .audit import digest,hash_value,require,strict_json
from .development_inputs import file_hash,ledger_snapshot
from .review_lease import _read,_directory,ARTIFACTS
from .review_issuer import _snapshot
from .selection_launcher import verify_selection
from .diagnosis_launcher import _unknown
from . import investigation_launcher as role


def inspect(config_path,config_sha256,*,clock=None):
    c,pin=_read(config_path,65536);require(pin==config_sha256,'research config pin drift')
    fee=ledger_snapshot(c['ledger_path']);c,policy,material,permit,current,provenance=role.prepare(config_path,clock=clock,fresh=False,expected_fee_sha256=fee['sha256'])
    require(current==fee);root=_directory(c['root']);values={};pins={}
    for name in ARTIFACTS:values[name],pins[name]=_read(root/name)
    require(values['intent.json']==dict(role=c['role'],config_sha256=config_sha256,input_sha256=role.input_hash(c,material)),'research intent drift')
    require(digest(values['manifest-private.json'])==digest(dict(config=c,permit=permit,provenance=provenance)),'research manifest drift')
    initial=values['initial-private.json'];require(initial['system']==role.SYSTEM and initial['prompt']==role.prompt(c,material) and initial['context_hash']==role.input_hash(c,material) and initial['config_hash']==digest(c) and initial['model']==policy.model and initial['max_tokens']==policy.max_tokens,'research initial input drift')
    proof=verify_selection(values['worker-frame-private.json'],initial,values['request-private.json']);require(proof==values['verification.json'],'research verification drift')
    proposal=role.validate_output(strict_json(proof['text']),c,material);result=values['result.json']
    require(result.get('schema')=='pi-no-tool-result-v1' and result.get('executable_approval') is False and all(result.get(k) is True for k in ('verified','execution_verified','contract_valid','closed_verified','policy_restored','credential_unchanged','original_history_unchanged')) and not any(k.endswith('failure_class') for k in result),'closed verified research required')
    require(result['role']==c['role'] and result['mode']==c['mode'] and result['run_id']==c['run_id'] and result['input_sha256']==role.input_hash(c,material) and digest(result['report'])==digest(proposal) and type(result['new_attempts']) is int and result['new_attempts']==1 and type(result['new_unknown']) is int and result['new_unknown']==0,'research result identity drift')
    require(isinstance(result['cleanup'],list) and bool(result['cleanup']) and all(isinstance(r,dict) and r.get('removed') is True and hash_value(r.get('container_id')) for r in result['cleanup']),'research cleanup uncertain')
    before=values['ledger-before-private.json'];after=values['ledger-after-private.json'];old=_snapshot(before);new=_snapshot(after)
    require(before['sha256']==c['ledger_sha256'] and after==fee and before['limits']==after['limits'] and after['events'][:len(before['events'])]==before['events'] and all(new.get(k)==v for k,v in old.items()) and _unknown(before)==_unknown(after)==set(permit['legacy_unknown_ids']),'original research fee history drift')
    added={k:r for k,r in new.items() if k not in old};posts=result['model_posts'];require(isinstance(posts,list) and len(posts)==1 and posts[0]['status']==200 and len(added)==1 and posts[0]['attempt_id'] in added,'research paid request binding drift')
    row=added[posts[0]['attempt_id']];e=strict_json(row['evidence'] or '{}');require(row['kind']=='model-attempt' and row['status']=='done' and e.get('usage_known') is True and type(e.get('charged_microyuan')) is int and e['charged_microyuan']>=0 and type(result['known_cost_microyuan']) is int and result['known_cost_microyuan']==e['charged_microyuan'],'known research fee required')
    require(file_hash(config_path)==config_sha256 and ledger_snapshot(c['ledger_path'])==fee and all(file_hash(root/name)==h for name,h in pins.items()),'research changed during inspection')
    return dict(authority='untrusted_proposal',config=c,material=material,proposal=proposal,fee=fee,artifact_pins=pins)
