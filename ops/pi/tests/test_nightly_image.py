"""Candidate-only local image preparation never executes candidate build commands."""
from hashlib import sha256
from pathlib import Path
import json,uuid
import pytest
from ops.pi.tests.test_nightly_gate import case

BASE_IMAGE='sha256:'+'3'*64
NEW_IMAGE='sha256:'+'4'*64
DAEMON='test-original-daemon'
FILE='src/myink/workflow/short_parse.py'


class Engine:
    def __init__(self,root,before,after,fault=None):self.root=root;self.before=before;self.after=after;self.calls=[];self.images={BASE_IMAGE:self.before,NEW_IMAGE:self.after};self.probes={};self.fault=fault
    def run(self,args,**kwargs):
        if args[0]=='--config':args=args[2:]
        if args[:2]==['buildx','build']:args=['build',*args[2:]]
        self.calls.append(args);value=b''
        if args==['info','--format','{{.ID}}']:value=DAEMON.encode()
        elif args[:2]==['image','inspect']:
            image=BASE_IMAGE if args[2].startswith('myink-pi-nightly-base:') else args[2];value=json.dumps([dict(Id=image,Size=10000,Os='linux',Architecture='amd64',Config=dict(User='10001',WorkingDir='/app',OnBuild=['RUN surprise'] if self.fault=='onbuild' else None,Labels={}))]).encode()
        elif args[:2] in (['image','ls'],['image','tag']):pass
        elif args[0]=='create':
            image=args[args.index('--entrypoint')+2];cid=uuid.uuid4().hex*2;self.probes[cid]=image;value=cid.encode()
        elif args[:2]==['start','--attach']:
            image=self.probes[args[-1]];files=dict(self.images[image]);
            if self.fault=='baseline':files[FILE]='0'*64
            if self.fault=='outside' and image==NEW_IMAGE:files['src/myink/other.py']='0'*64
            value=json.dumps(dict(package='/usr/local/lib/python3.12/site-packages/myink',files=files)).encode()
        elif args[:2]==['container','inspect']:
            value=json.dumps([dict(Id=args[-1],State=dict(Running=False,ExitCode=0),Config=dict(Labels={'myink.pi.nightly.cycle':self.cycle}))]).encode()
        elif args[:2]==['container','rm']:pass
        elif args[0]=='build':Path(args[args.index('--iidfile')+1]).write_text(NEW_IMAGE)
        elif args[:2]==['image','save']:Path(args[args.index('--output')+1]).write_bytes(b'local native archive')
        else:raise AssertionError(args)
        cid=str(uuid.uuid4());folder=self.root/cid;folder.mkdir();(folder/'stdout.bin').write_bytes(value)
        if self.fault=='build_unknown' and args[0]=='build':raise TimeoutError('unknown build')
        return dict(command_id=cid,status='done',returncode=0)


def setup(case,fault=None):
    g=case[0](True);cycle=str(uuid.uuid4());g.begin(cycle,'2026-10-31');root=case[-1].parent/'image';source=root.parent/'source';candidate=root.parent/'candidate'
    for p in (source,candidate):
        (p/FILE).parent.mkdir(parents=True);(p/FILE).write_text('value=1\n' if p==source else 'value=2\n')
    before={FILE:sha256((source/FILE).read_bytes()).hexdigest(),'src/myink/other.py':'5'*64};after=dict(before,**{FILE:sha256((candidate/FILE).read_bytes()).hexdigest()})
    commands=root/'commands';engine=Engine(commands,before,after,fault);engine.cycle=cycle
    from ops.pi.nightly_image import LocalImage
    image=LocalImage(g,cycle,root,Path('/bin/echo'),'unix:///test.sock',DAEMON,transport=engine)
    return g,image,engine,source,candidate


def test_fixed_copy_image_is_local_and_binds_real_source_and_archive(case):
    g,image,engine,source,candidate=setup(case);r=image.build(source,candidate,BASE_IMAGE)
    assert r['status']=='ready' and r['base_image_id']==BASE_IMAGE and r['image_id']==NEW_IMAGE
    assert r['archive_sha256']==sha256(Path(r['archive_path']).read_bytes()).hexdigest()
    text=(image.root/'context/Dockerfile').read_text();assert text.startswith('FROM myink-pi-nightly-base:'+image.cycle+'\n') and 'COPY [' in text and 'RUN ' not in text
    assert all('push' not in args and '--network=host' not in args for args in engine.calls)
    assert next(a for a in engine.calls if a[0]=='build')[1:3]==['--network=none','--pull=false']
    assert {p.relative_to(image.root/'context').as_posix() for p in (image.root/'context').rglob('*') if p.is_file()}=={'Dockerfile','files/'+FILE}
    assert g.status()['phase']=='preparing' # Driver still must seal evaluation and comparison.


@pytest.mark.parametrize('fault',['baseline','onbuild','outside','build_unknown'])
def test_drift_or_unknown_build_retains_intent_and_never_seals(case,fault):
    g,image,engine,source,candidate=setup(case,fault)
    with pytest.raises((ValueError,TimeoutError)):image.build(source,candidate,BASE_IMAGE)
    assert (image.root/'intent.json').exists() and not (image.root/'receipt.json').exists()
    with pytest.raises(ValueError):image.build(source,candidate,BASE_IMAGE)
    assert sum(a[0]=='build' for a in engine.calls)<=1


def test_waiting_gate_blocks_before_docker_or_filesystem_work(case):
    g,image,engine,source,candidate=setup(case);g.ready(image.cycle,case[2])
    with pytest.raises(ValueError):image.build(source,candidate,BASE_IMAGE)
    assert engine.calls==[] and not image.root.exists()


def test_link_or_extra_private_file_never_enters_context(case):
    g,image,engine,source,candidate=setup(case);(candidate/'private.key').write_text('private')
    with pytest.raises(ValueError):image.build(source,candidate,BASE_IMAGE)
    assert not any(a[0]=='build' for a in engine.calls)


def test_simulated_image_preparation_cannot_target_original_production_daemon(case):
    from ops.pi.nightly_image import LocalImage
    g=case[0](True)
    with pytest.raises(ValueError):LocalImage(g,str(uuid.uuid4()),case[-1].parent/'image',Path('/bin/echo'),'unix:///test.sock','0f90c176-9c45-4708-8103-37b5ff2464f1',transport=object())
