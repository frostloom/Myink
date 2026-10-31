"""Only operator-selected installed files, bound to the full approved package."""
from pathlib import Path
from hashlib import sha256
import json,uuid
import pytest
from ops.pi.audit import digest

FILE='src/myink/context_budget.py'
TEXT='value = 3\n'


class Commands:
    def __init__(self,root,fault=None):self.root=root;self.fault=fault;self.calls=[]
    def run(self,args,**kwargs):
        self.calls.append(args)
        if args[0]=='info':value=b'fixture-daemon'
        elif args[0]=='exec':
            if len(args)==10:value=json.dumps(dict(package='/usr/local/lib/python3.12/site-packages/myink',files={FILE:sha256(TEXT.encode()).hexdigest()})).encode()
            else:value=json.dumps({FILE:TEXT if self.fault!='body' else 'changed'}).encode()
            if self.fault=='package' and len(args)==10:value=json.dumps(dict(package='/usr/local/lib/python3.12/site-packages/myink',files={FILE:'1'*64})).encode()
        else:raise AssertionError(args)
        folder=self.root/uuid.uuid4().hex;folder.mkdir();(folder/'stdout.bin').write_bytes(value);return dict(status='done',returncode=0,command_id=folder.name)


def call(tmp_path,fault=None,files=None):
    from ops.pi.nightly_source_read import read
    root=tmp_path/'read';commands=Commands(root/'commands',fault);packet=dict(manifest=dict(image_id='sha256:'+'7'*64),image=dict(package_sha256=digest({FILE:sha256(TEXT.encode()).hexdigest()})))
    rows=[dict(role='myink-api',container_id='a'*64,image_id='sha256:'+'7'*64)]
    result=read('SIMULATED',packet,rows,files or [FILE],root,transport=commands);return result,commands


def test_selected_installed_text_is_readonly_and_full_package_bound(tmp_path):
    result,commands=call(tmp_path)
    assert result=={FILE:TEXT} and len([a for a in commands.calls if a[0]=='exec'])==2
    assert all(a[0] in ('info','exec') for a in commands.calls)
    assert all('-I' in a and '-S' in a and '-B' in a for a in commands.calls if a[0]=='exec')


@pytest.mark.parametrize('fault',['package','body'])
def test_drift_is_rejected_and_intent_is_retained(tmp_path,fault):
    with pytest.raises(ValueError):call(tmp_path,fault)
    assert (tmp_path/'read/intent.json').exists() and not (tmp_path/'read/receipt.json').exists()


@pytest.mark.parametrize('files',[['src/myink/../secret.py'],['/etc/passwd'],[FILE]*2])
def test_invalid_paths_never_start_transport(tmp_path,files):
    with pytest.raises(ValueError):call(tmp_path,files=files)
    assert not (tmp_path/'read').exists()


@pytest.mark.parametrize('fault',[None,'symlink','hardlink','oversize','encoding'])
def test_fixed_reader_program_never_imports_source_and_rejects_nonregular_bytes(tmp_path,fault):
    import subprocess,sys,os
    from ops.pi.nightly_source_read import READ
    package=tmp_path/'myink';package.mkdir();path=package/'context_budget.py';body="raise RuntimeError('application source was executed')\n";path.write_text(body)
    if fault=='symlink':path.unlink();path.symlink_to(tmp_path/'outside.py');(tmp_path/'outside.py').write_text(body)
    elif fault=='hardlink':os.link(path,tmp_path/'alias.py')
    elif fault=='oversize':path.write_bytes(b'x'*24001)
    elif fault=='encoding':path.write_bytes(b'\xff')
    program='import sysconfig;sysconfig.get_path=lambda key:'+repr(str(tmp_path))+';\n'+READ
    result=subprocess.run([sys.executable,'-I','-S','-B','-c',program,json.dumps([FILE])],capture_output=True)
    if fault is None:assert result.returncode==0 and json.loads(result.stdout)=={FILE:body}
    else:assert result.returncode!=0
