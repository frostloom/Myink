"""Bootstrap telemetry preparation leaves the original waiting cycle untouched."""
from pathlib import Path
from hashlib import sha256
import json
import pytest
from ops.pi.tests.test_nightly_bundle import bundle_case,finished,stopped,completed,config_file,prepare
from ops.pi.tests.test_nightly_image import Engine,BASE_IMAGE,NEW_IMAGE,DAEMON
from ops.pi.audit import digest
from ops.pi.development_inputs import ledger_snapshot,file_hash


def setup(case,monkeypatch,fault=None):
    from ops.pi import nightly_compatibility as module
    prepare(case);g,cycle,old,*_=case;root=old.parent/('compatibility-'+cycle);source=old.parent/'telemetry-before';candidate=old.parent/'telemetry-after';patch=old.parent/'telemetry.patch';patch.write_bytes(b'fixed operator patch')
    before={};after={}
    for name in module.FILES:
        data=b'old=1\n';target=candidate/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'new=2\n');after[name]=file_hash(target)
        if not name.endswith('/observability.py'):
            target=source/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);before[name]=file_hash(target)
    monkeypatch.setattr(module,'PREIMAGES',{n:before.get(n) for n in module.FILES});monkeypatch.setattr(module,'CANDIDATES',after);monkeypatch.setattr(module,'PATCH',file_hash(patch))
    installed=dict(before,**{'src/myink/other.py':'5'*64})
    if fault=='baseline':installed['src/myink/config.py']='0'*64
    engine=Engine(root/'image/commands',installed,dict(installed,**after),fault);engine.cycle=cycle
    return module,g,cycle,old,root,source,candidate,patch,engine


def run(c):
    m,g,cycle,old,root,source,candidate,patch,engine=c
    return m.prepare(g,old/'bundle',root,source,candidate,patch,BASE_IMAGE,Path('/bin/echo'),'unix:///fixture.sock',DAEMON,transport=engine)


def test_bootstrap_build_is_local_and_does_not_advance_old_gate(bundle_case,monkeypatch):
    c=setup(bundle_case,monkeypatch);m,g,cycle,old,root,source,candidate,patch,engine=c;state=g.status();before=ledger_snapshot(g.state),ledger_snapshot(g.billing)
    report=run(c)
    assert report['schema']=='pi-nightly-compatible-base-v1' and report['cycle_id']==cycle and report['package_sha256']==state['package_sha256']
    assert report['parent_image_id']==BASE_IMAGE and report['image_id']==NEW_IMAGE and report['patch_sha256']==file_hash(patch)
    assert set(report)==__import__('ops.pi.nightly_rebuild',fromlist=['FIELDS']).FIELDS
    assert report['changes']['src/myink/observability.py']['before'] is None
    assert g.status()==state and (ledger_snapshot(g.state),ledger_snapshot(g.billing))==before
    assert json.loads((root/'compatibility.json').read_bytes())==report
    dockerfile=(root/'image/context/Dockerfile').read_text();assert 'RUN ' not in dockerfile and dockerfile.count('COPY ')==3
    assert not any(a[0]=='push' for a in engine.calls)
    with pytest.raises(ValueError):run(c)


@pytest.mark.parametrize('fault',['candidate','patch','baseline','outside','onbuild'])
def test_changed_inputs_or_outside_package_never_produce_report(bundle_case,monkeypatch,fault):
    c=setup(bundle_case,monkeypatch,fault if fault in ('baseline','outside','onbuild') else None);m,g,cycle,old,root,source,candidate,patch,engine=c;state=g.status()
    if fault=='candidate':(candidate/'src/myink/config.py').write_bytes(b'changed=3\n')
    if fault=='patch':patch.write_bytes(b'changed patch')
    with pytest.raises(ValueError):run(c)
    assert g.status()==state and not (root/'compatibility.json').exists()


def test_retained_original_bundle_alias_does_not_block_compatibility(bundle_case,monkeypatch):
    c=setup(bundle_case,monkeypatch);m,g,cycle,old,root,source,candidate,patch,engine=c;original=engine.run
    def retained(args,**kwargs):
        result=original(args,**kwargs)
        if args==['image','ls','--quiet','--filter','reference=myink-pi-nightly-base:'+cycle]:
            (engine.root/result['command_id']/'stdout.bin').write_text(BASE_IMAGE)
        return result
    engine.run=retained
    report=run(c)
    assert report['image_id']==NEW_IMAGE and g.status()['cycle_id']==cycle
    assert not any(a[:2]==['image','tag'] and a[-1]=='myink-pi-nightly-base:'+cycle for a in engine.calls)
