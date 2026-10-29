"""Independent finite authority for returning an already adopted deployment."""
from copy import deepcopy
from datetime import timedelta
from .audit import digest,encoded,hash_value,require,strict_json,utc,_plain

FIELDS=set('schema mode target authority plan_sha256 control_sha256 candidate approved_action issued_at expires_at maximum_stopped_seconds'.split())


def validate(value,plan,target,now):
    require(isinstance(value,dict) and set(value)==FIELDS and value['schema']=='pi-product-rollback-lease-v1' and len(encoded(value))<=16384,'closed rollback lease required')
    require(value['mode']==plan['mode'] and value['target']==target and target in ('production','rehearsal') and value['authority']==('human_product_release' if target=='production' else 'owned_rehearsal') and value['approved_action']=='rollback','rollback-only external authority required')
    require(value['plan_sha256']==digest(plan) and value['candidate']==plan['candidate'] and hash_value(value['control_sha256']),'exact adopted rollback identity required')
    require(plan['mode']!='SIMULATED' or target=='rehearsal','simulation cannot authorize production rollback')
    issued=utc(value['issued_at']);expires=utc(value['expires_at']);clock=utc(now)
    require(issued<=clock<expires and issued<=utc(plan['expires_at']) and expires<=utc(plan['expires_at'])+timedelta(hours=72),'finite post-window rollback authority expired')
    require(type(value['maximum_stopped_seconds']) is int and 0<value['maximum_stopped_seconds']<=1800,'bounded rollback maintenance required');return deepcopy(value)


def adopted(host):
    lease=host.rollback_lease;op='product-control:'+host.plan['operation_id']+':activate';row=host.ledger.get(op)
    require(row and row['kind']=='product_control' and row['status']=='done' and row['payload']==dict(plan_sha256=digest(host.plan),config_sha256=lease['control_sha256'],action='activate') and row['evidence'].get('verified') is True and row['evidence'].get('phase')=='native_candidate_open' and row['evidence'].get('identity')==host.plan['candidate'],'completed original adoption required before rollback lease')


def start_packet(host):
    return dict(plan_sha256=digest(host.plan),control_sha256=host.rollback_lease['control_sha256'],lease_sha256=host.rollback_lease_pin,started_at=host.clock().isoformat())


def deadline(host):
    path=host.root/'native-control/rollback/start.json';require(path.exists(),'rollback start intent required');_plain(path);require(path.stat().st_size<=1024,'bounded rollback start required');value=strict_json(path.read_bytes())
    require(isinstance(value,dict) and set(value)=={'plan_sha256','control_sha256','lease_sha256','started_at'} and all(value[k]==start_packet(host)[k] for k in ('plan_sha256','control_sha256','lease_sha256')),'original rollback timer binding required')
    began=utc(value['started_at']);now=utc(host.clock());end=min(began+timedelta(seconds=host.rollback_lease['maximum_stopped_seconds']),utc(host.rollback_lease['expires_at']))
    require(began<=now<end,'rollback maintenance duration exceeded');return end


def native_action(host,action):
    lease=getattr(host,'rollback_lease',None)
    if lease is None:return
    steps={'stop_candidate_admission':'stop','create_rollback':'return','start_rollback':'start-return'}
    require(action in steps,'rollback lease cannot activate or renew native actions')
    root='product-control:'+host.plan['operation_id']+':rollback';parent=host.ledger.get(root);name=steps[action];child=host.ledger.get(root+':'+name)
    require(parent and parent['kind']=='product_control' and parent['status']=='pending' and parent['payload']==dict(plan_sha256=digest(host.plan),config_sha256=lease['control_sha256'],action='rollback'),'original rollback parent required')
    require(child and child['kind']=='product_control_step' and child['status']=='pending' and child['payload']==dict(plan_sha256=digest(host.plan),config_sha256=lease['control_sha256'],step=name),'original rollback stage required');deadline(host)
