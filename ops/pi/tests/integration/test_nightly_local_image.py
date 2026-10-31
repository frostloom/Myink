"""One owned Docker-only image preparation; no provider or product deployment."""
from pathlib import Path
from hashlib import sha256
import json,shutil,subprocess,tarfile,uuid
import pytest
from ops.pi.tests.test_nightly_gate import case
from ops.pi.nightly_image import LocalImage
from ops.pi import manager

pytestmark=pytest.mark.pi_followup_docker


def test_real_local_copy_image_and_archive_preserve_original_manager_and_base(case):
    docker=Path(shutil.which('docker')).resolve()
    def d(*args):return subprocess.check_output([str(docker),*args],timeout=30).decode().strip()
    endpoint=json.loads(d('context','inspect','--format','{{json .Endpoints.docker.Host}}'))
    daemon=d('--host',endpoint,'info','--format','{{.ID}}');assert daemon!='0f90c176-9c45-4708-8103-37b5ff2464f1'
    base=json.loads(d('--host',endpoint,'image','inspect','myink-api:d25d8275'))[0]['Id']
    g=case[0](True);cycle=str(uuid.uuid4());g.begin(cycle,'2026-10-31');parent=case[-1].parent
    original=subprocess.check_output(['git','show','d25d8275:src/myink/workflow/short_parse.py'],timeout=10)
    source=parent/'source';candidate=parent/'candidate';relative='src/myink/workflow/short_parse.py'
    for path,data in ((source,original),(candidate,original+b'\n# Owned nightly image transport regression.\n')):
        f=path/relative;f.parent.mkdir(parents=True);f.write_bytes(data)
    before=manager.status(case[-3],case[-2],mode='SIMULATED');root=parent/'image'
    image=LocalImage(g,cycle,root,docker,endpoint,daemon)
    try:
        result=image.build(source,candidate,base)
        assert result['status']=='ready' and result['image_id']!=base and result['published'] is result['deployed'] is False
        assert Path(result['archive_path']).stat().st_size>1000000
        with Path(result['archive_path']).open('rb') as stream:assert __import__('hashlib').file_digest(stream,'sha256').hexdigest()==result['archive_sha256']
        with tarfile.open(result['archive_path']) as archive:
            manifest=json.load(archive.extractfile('manifest.json'));assert len(manifest)==1
            config=archive.extractfile(manifest[0]['Config']).read()
            config_id='sha256:'+sha256(config).hexdigest();assert manifest[0]['Layers']
            if config_id!=result['image_id']:
                # Containerd stores an OCI index as the image identity; prove
                # the digest chain to the exported runnable image's config.
                index=json.load(archive.extractfile('index.json'))
                assert result['image_id'] in {x['digest'] for x in index['manifests']}
                def includes_config(pin,depth=0):
                    assert depth<=3
                    blob=archive.extractfile('blobs/sha256/'+pin.removeprefix('sha256:')).read()
                    assert 'sha256:'+sha256(blob).hexdigest()==pin
                    node=json.loads(blob)
                    if 'config' in node:return node['config']['digest']==config_id
                    return any(includes_config(x['digest'],depth+1) for x in node['manifests'])
                assert includes_config(result['image_id'])
        assert manager.status(case[-3],case[-2],mode='SIMULATED')==before
        assert json.loads(d('--host',endpoint,'image','inspect',base))[0]['Id']==base
    finally:
        # Only this test's stopped probes and untagged candidate image may go.
        cids=d('--host',endpoint,'ps','-aq','--filter','label=myink.pi.nightly.cycle='+cycle)
        assert not cids, 'owned image probe cleanup incomplete'
        iid=root/'image-id'
        if iid.exists():
            created=iid.read_text().strip();assert created!=base
            row=json.loads(d('--host',endpoint,'image','inspect',created))[0]
            assert row['Config']['Labels']['myink.pi.nightly.cycle']==cycle and not row['RepoTags']
            d('--host',endpoint,'image','rm',created)
        refs=d('--host',endpoint,'image','ls','--quiet','--filter','reference=myink-pi-nightly-base:'+cycle)
        if refs:
            row=json.loads(d('--host',endpoint,'image','inspect',base))[0]
            assert 'myink-api:d25d8275' in row['RepoTags']
            d('--host',endpoint,'image','rm','myink-pi-nightly-base:'+cycle)
            assert json.loads(d('--host',endpoint,'image','inspect',base))[0]['Id']==base
