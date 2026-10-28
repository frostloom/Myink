"""Explicit independent local Docker acceptance; no DB, provider or shared ports."""
from pathlib import Path
import json,os,shutil,subprocess,uuid
import pytest
from ops.pi.followup import _isolated_check
from ops.pi.development_inputs import tree_hash,file_hash
from ops.pi.container_probe import ProbeHost

pytestmark=pytest.mark.pi_followup_docker
IMAGE='sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1'
DOCKER=shutil.which('docker') or '/Applications/Docker.app/Contents/Resources/bin/docker'


@pytest.mark.parametrize('scenario',['pass','assertion_failure','case_mismatch'])
def test_real_fixed_check_and_owned_cleanup(tmp_path,scenario):
    socket=Path.home()/'.docker/run/docker.sock';endpoint='unix://'+str(socket) if socket.exists() else 'unix:///var/run/docker.sock'
    prefix=[DOCKER,'--host',endpoint]
    def docker(*args):return subprocess.check_output([*prefix,*args],text=True,timeout=15).strip()
    daemon=docker('info','--format','{{.ID}}');assert docker('image','inspect',IMAGE,'--format','{{.Id}}')==IMAGE
    root=Path.cwd()/'.local/pi-followup-20261028/docker-tests'/uuid.uuid4().hex;root.mkdir(mode=0o700,parents=True)
    candidate=tmp_path/'candidate';(candidate/'src').mkdir(parents=True);(candidate/'src/example.py').write_text('def value(): return "ok"\n')
    gold=tmp_path/'test.py';expected='wrong' if scenario=='assertion_failure' else 'ok'
    gold.write_text('''import os,errno,unittest
from pathlib import Path
from example import value
class Check(unittest.TestCase):
 def test_identity(self):
  self.assertEqual(os.getuid(),65534)
  self.assertNotIn('OPENAI_API_KEY',os.environ)
 def test_readonly(self):
  with self.assertRaises(OSError) as caught:Path('/source/src/forbidden').write_text('no')
  self.assertIn(caught.exception.errno,(errno.EACCES,errno.EROFS))
 def test_value(self):self.assertEqual(value(),'''+repr(expected)+''')
''')
    cases=['fixed_development_tests.Check.test_'+v for v in ('identity','readonly','value')]
    if scenario=='case_mismatch':cases.append('fixed_development_tests.Check.test_unknown')
    e=dict(candidate_path=str(candidate),candidate_sha256=tree_hash(candidate),test_path=str(gold),test_sha256=file_hash(gold),test_cases=cases,checker=dict(docker=DOCKER,endpoint=endpoint,daemon_id=daemon,checker_image_id=IMAGE))
    def write(name,value):
        p=root/name
        with p.open('x') as out:json.dump(value,out)
        p.chmod(0o600)
    result=None;remaining=[];cleanup=[]
    try:
        if scenario=='case_mismatch':
            with pytest.raises(ValueError):_isolated_check(e,root,write)
        else:
            result=_isolated_check(e,root,write)
            assert result['tests']==3 and result['cases']==cases and result['passed']==(scenario=='pass')
            assert result['errors']==result['skipped']==0 and all(r['removed'] for r in result['cleanup'])
        assert tree_hash(candidate)==e['candidate_sha256'] and file_hash(gold)==e['test_sha256']
    finally:
        assert docker('info','--format','{{.ID}}')==daemon
        for p in root.glob('owned-host-*.json'):
            operation=json.loads(p.read_text())['operation_id']
            found=docker('ps','-aq','--no-trunc','--filter','label=myink.pi.operation='+operation).split();remaining.extend(found)
            host=ProbeHost(docker=Path(DOCKER),endpoint=endpoint,daemon_id=daemon,image_id=IMAGE,operation_id=operation)
            host.reconcile()
            for cid in list(host.owned):cleanup.append(host.cleanup(cid))
            assert not docker('ps','-aq','--filter','label=myink.pi.operation='+operation)
        write('native-proof.json',dict(scenario=scenario,daemon_id=daemon,image_id=IMAGE,model_requests=0,initial_remaining=remaining,recovery_cleanup=cleanup,result=result))
        assert not remaining,'adapter must have cleaned its own containers before returning'
