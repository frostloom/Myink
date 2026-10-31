"""Issue one private observer config from a verified human-approved deployment.

Only identity and output location change. The operator's pinned database reader,
sample policy and audit destinations remain fixed. No query/model/release occurs.
"""
from pathlib import Path
import os,stat
from .audit import _path,_plain,require,strict_json,digest,hash_value
from .development_inputs import file_hash
from .nightly_gate import BASE
from .nightly_bundle import verify
from .product_commands import _write


def _read(path):
    path=_path(path);_plain(path);require(path.stat().st_size<=1048576 and stat.S_IMODE(path.stat().st_mode)==0o600,'bounded private binding input required');return strict_json(path.read_bytes())


def _ordinary(path,mode):
    if mode=='ACTUAL':
        import pwd
        owner=pwd.getpwnam('ubuntu');os.chown(path,owner.pw_uid,owner.pw_gid)


def context(gate,cycle,bundle,*,historical=False):
    if historical:
        with gate._connection() as c:require(gate._row(c,cycle)['phase']=='completed','completed comparison required')
    else:gate.require_action(cycle,'observe_metrics')
    bundle=_path(bundle);packet=verify(gate,bundle)
    if gate.mode=='ACTUAL':require(os.geteuid()==0 and bundle==BASE/'nightly'/cycle/'bundle','original root deployment binding required')
    with gate._connection() as c:deployment=strict_json(gate._row(c,cycle)['deployment'])
    path=bundle.parent/'deployment-context.json';value=_read(path)
    require(set(value)=={'schema','cycle_id','deployment_receipt_sha256','cohort_sha256','containers'} and value['schema']=='pi-nightly-deployed-context-v1' and value['cycle_id']==cycle and value['deployment_receipt_sha256']==deployment['sha256'],'verified deployment context required')
    rows=value['containers'];require(isinstance(rows,list) and len(rows)==3 and digest(rows)==value['cohort_sha256'],'complete bound product cohort required')
    identity=rows[0]['identity']
    from .live_observer import _identity
    _identity(identity)
    require(identity['deployment_id']==deployment['packet']['deployment_id'] and identity['image_ids'].get('python')==packet['manifest']['image_id'] and all(r['identity']==identity and r['image_id']==packet['manifest']['image_id'] for r in rows),'bound deployed identity mismatch')
    if gate.mode=='ACTUAL':require(path.stat().st_uid==0,'root-issued deployment context required')
    return packet,deployment,value,path


def bind(gate,cycle,bundle,template_path,template_pin):
    packet,deployment,cohort,context_path=context(gate,cycle,bundle);bundle=Path(bundle);template_path=_path(template_path)
    template=_read(template_path);require(file_hash(template_path)==template_pin,'observer template drift')
    from .live_observer import FIELDS,OPTIONAL,_load
    from .psql_metrics import PsqlMetricsReader
    require(FIELDS<=set(template)<=FIELDS|OPTIONAL and template['schema']=='pi-live-observer-v1' and template['mode']==gate.mode and template['interval_minutes']==15 and template['lookback_hours']==1 and type(template['minimum_samples']) is int and 20<=template['minimum_samples']<=500,'bounded observer template required')
    PsqlMetricsReader(template['source'],run=lambda *a,**k:None)
    if gate.mode=='ACTUAL':
        require(template_path==BASE/'config/observer/nightly-template.json' and template_path.stat().st_uid==0 and template_path.parent.stat().st_uid==0 and stat.S_IMODE(template_path.parent.stat().st_mode)==0o700,'root fixed observer template required')
        source=template['source'];require(source['docker']=='/usr/bin/docker' and source['endpoint']=='unix:///var/run/docker.sock' and source['daemon_id']=='0f90c176-9c45-4708-8103-37b5ff2464f1','original read-only metrics transport required')
        require(_path(template['audit_path']).parent==BASE/'audit/state' and _path(template.get('export_root',BASE/'audit/export'))==BASE/'audit/export','original observer audit scope required')
    folder=BASE/'config/nightly-observers'/cycle if gate.mode=='ACTUAL' else bundle.parent/'observer-config'
    path=folder/'observer.json';metrics=BASE/'observations'/('nightly-'+cycle) if gate.mode=='ACTUAL' else bundle.parent/'metrics'
    config=dict(template,identity=cohort['containers'][0]['identity'],root=str(metrics))
    receipt=bundle.parent/'observer-binding.json';intent=bundle.parent/'observer-binding-intent.json'
    expected=dict(schema='pi-nightly-observer-binding-v1',cycle_id=cycle,template_sha256=template_pin,deployment_receipt_sha256=deployment['sha256'],context_sha256=file_hash(context_path),path=str(path),sha256=digest(config))
    if receipt.exists():
        require(_read(receipt)==expected and file_hash(path)==expected['sha256'],'bound observer config drift');_load(path)
        return dict(path=str(path),sha256=expected['sha256'])
    require(not intent.exists(),'unfinished observer binding retained; no overwrite');_write(intent,expected)
    if gate.mode=='ACTUAL' and not folder.parent.exists():
        folder.parent.mkdir(mode=0o750)
        import pwd
        os.chown(folder.parent,0,pwd.getpwnam('ubuntu').pw_gid);os.chmod(folder.parent,0o750)
    require(not folder.exists() and not metrics.exists(),'new per-deployment observer outputs required')
    folder.mkdir(mode=0o700);metrics.mkdir(mode=0o700);_ordinary(folder,gate.mode);_ordinary(metrics,gate.mode)
    _write(path,config);_ordinary(path,gate.mode);_load(path)
    require(file_hash(template_path)==template_pin and file_hash(context_path)==expected['context_sha256'],'observer binding inputs changed')
    _write(receipt,expected);return dict(path=str(path),sha256=expected['sha256'])


def _audit_outputs(config):
    audit=_path(config['audit_path']);export=_path(config.get('export_root',BASE/'audit/export'))
    require(audit.parent==BASE/'audit/state' and export==BASE/'audit/export','fixed observer audit handoff required')
    manifest=export/'manifest.json';_plain(manifest)
    require(manifest.stat().st_size<=8388608 and stat.S_IMODE(manifest.stat().st_mode)==0o600,'bounded private audit manifest required')
    metadata=strict_json(manifest.read_bytes())
    require(metadata.get('schema_version')==1 and metadata.get('authority')=='audit_only' and isinstance(metadata.get('pages'),list) and len(metadata['pages'])<=10000,'bounded audit-only export required')
    pages=_path(export/'pages');files=[audit,manifest]
    for page in metadata['pages']:
        require(isinstance(page,dict) and hash_value(page.get('sha256')),'fixed audit page digest required')
        files.append(_path(pages/(page['sha256']+'.json')))
    for item in files:_plain(item)
    return files


def collect(path,pin,*,mode):
    from .live_observer import observe
    config=_read(path);require(file_hash(path)==pin,'observer config changed before collection')
    result=observe(path,expected_config_sha256=pin)
    require(file_hash(path)==pin,'observer config changed during collection')
    if mode=='ACTUAL':
        # Future ordinary investigation workers must be able to verify the same
        # immutable metrics receipt and audit export. No source/product DB/config tree changes.
        root=_path(Path(config['root'])/result['run_id'])
        require(root.is_dir() and stat.S_IMODE(root.stat().st_mode)==0o700 and root.parent==Path(config['root']) and len(list(root.iterdir()))<=4,'bounded own observer output required')
        files=list(root.iterdir())+_audit_outputs(config)
        for item in files:_plain(item)
        for item in files:_ordinary(item,mode)
        _ordinary(root,mode)
    return result
