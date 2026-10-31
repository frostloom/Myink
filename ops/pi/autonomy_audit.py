"""Fixed audit-only projection kernel, executed as the ordinary worker."""
from .audit import AuditStore,_path,_plain,require
from .development_inputs import file_hash,read_json
from .local_cycle import _disjoint

FIELDS={'schema','mode','audit_path','export_root','events'}


def emit(config_path,pin):
    cp=_path(config_path);_plain(cp);require(cp.stat().st_size<=65536 and file_hash(cp)==pin,'audit projection pin drift');c=read_json(cp)
    require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-autonomy-audit-v1' and c['mode'] in ('ACTUAL','SIMULATED'),'fixed audit projection required')
    if c['mode']=='ACTUAL':
        from .autonomy_worker import _identity
        _identity()
    require(isinstance(c['events'],list) and 1<=len(c['events'])<=2,'bounded coordinator projection required')
    _disjoint(_path(c['audit_path']),cp);_disjoint(_path(c['export_root']),cp)
    for item in c['events']:require(isinstance(item,dict) and set(item)=={'record_key','event'} and isinstance(item['event'],dict) and item['event'].get('mode')==c['mode'],'projection mode/record drift')
    audit=AuditStore(c['audit_path'])
    for item in c['events']:audit.append(item['record_key'],item['event'])
    audit.export(c['export_root']);return dict(model_requests=0,records=len(c['events']))
