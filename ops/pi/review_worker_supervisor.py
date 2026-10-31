"""Finite external review registry. Never uses the original maintenance lock."""
from hashlib import sha256
from pathlib import Path
import stat
from .audit import _path,_plain,hash_value,require,strict_json
from .development_inputs import file_hash
from .manager_handoff import BASE
from .manager_review_worker import tick

FIELDS={'schema','mode','entries'}
ENTRY={'request_path','request_sha256'}


def run(registry_path,expected_registry_sha256,*,clock=None):
    path=_path(registry_path);_plain(path);require(path.stat().st_size<=65536)
    raw=path.read_bytes();require(hash_value(expected_registry_sha256) and sha256(raw).hexdigest()==expected_registry_sha256,'review worker registry drift')
    c=strict_json(raw);require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-review-worker-registry-v1' and c['mode'] in ('ACTUAL','SIMULATED'),'strict finite review worker registry required')
    if c['mode']=='ACTUAL':
        require(clock is None and path.stat().st_uid==0 and stat.S_IMODE(path.stat().st_mode)==0o640 and path.parent.stat().st_uid==0 and stat.S_IMODE(path.parent.stat().st_mode)==0o750,'ACTUAL root registry and real clock required')
    else:require(stat.S_IMODE(path.stat().st_mode)==0o600,'private simulated registry required')
    require(isinstance(c['entries'],list) and len(c['entries'])<=16,'finite review worker queue required');seen=set()
    for e in c['entries']:
        require(isinstance(e,dict) and set(e)==ENTRY and hash_value(e['request_sha256']),'pinned reviewed handoff entry required')
        request=_path(e['request_path']);_plain(request);require(request.stat().st_size<=65536 and str(request) not in seen and file_hash(request)==e['request_sha256'],'duplicate or changed handoff');seen.add(str(request))
        q=strict_json(request.read_bytes());require(q['mode']==c['mode'],'mixed worker modes forbidden')
        if c['mode']=='ACTUAL':require(_path(q['root']).parent==BASE/'handoffs' and request.is_relative_to(BASE/'handoffs'),'original finite handoff custody required')
    result=dict(schema='pi-review-worker-tick-v1',mode=c['mode'],status='idle',model_requests=0,results=[])
    for e in c['entries']:
        require(file_hash(path)==expected_registry_sha256,'worker registry revoked')
        r=tick(e['request_path'],e['request_sha256'],clock=clock);require(r['model_requests']==0,'external review worker must not call models')
        result['results'].append(r)
        if r['status'] in ('uncertain','blocked','failed'):result['status']=r['status'];break
        result['status']='waiting' if any(v['status'].startswith('waiting_') for v in result['results']) else 'done'
    return result
