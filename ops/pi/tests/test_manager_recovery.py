"""Independent processes, synthetic callback side effects; never real model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from ops.pi.tests.test_manager import queue,enqueue,request_for,entry,pack,config_file
from ops.pi import manager

WORKER=r'''
import json,os,sys,time
from pathlib import Path
from ops.pi import manager
from ops.pi.development_inputs import read_json,file_hash
state,billing,root,kind=Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4]
def inspect(p):
 c=read_json(p);return c,read_json(c['selection_config_path']),[],read_json(c['templates_path'])
manager.inspect_cycle=inspect  # Explicit SIMULATED fixture, no runtime or provider.
def output(p):
 c=read_json(p)
 return dict(operation_id='maintenance:'+c['cycle_id'],schema_version=1,status='done',
   evidence=dict(verified=True,mode='SIMULATED',released=False,next_action='review_candidate'))
def record():
 with (root/'external-effects.txt').open('a') as f:f.write('effect\n');f.flush();os.fsync(f.fileno())
def execute(p,**kw):
 record()
 if kind=='after':os._exit(72)
 if kind=='hold':
  (root/'held').write_text('1');until=time.monotonic()+10
  while not (root/'release').exists():
   if time.monotonic()>until:raise TimeoutError('test release missing')
   time.sleep(.01)
 return output(p)
if kind=='before':
 def claim(ledger,c,callback):
  ledger.intent(c['operation_id'],'iteration_stage',c);os._exit(71)
 manager._run_action=claim
if kind=='enqueue':
 identity=sys.argv[5];p=Path(sys.argv[6]);original=manager.Ledger
 class SlowLedger(original):
  def intent(self,op,kind,payload):
   if kind=='manager_task':time.sleep(.5)
   return super().intent(op,kind,payload)
 manager.Ledger=SlowLedger
 (root/('ready-'+identity)).write_text('1');until=time.monotonic()+10
 while not (root/'go').exists():
  if time.monotonic()>until:raise TimeoutError('test barrier missing')
  time.sleep(.01)
 try:r=manager.enqueue(state,billing,identity,p,file_hash(p),mode='SIMULATED')
 except ValueError as error:r=dict(status='blocked',error=type(error).__name__)
else:r=manager.run(state,billing,max_tasks=1,mode='SIMULATED',executor=execute)
print(json.dumps(r),flush=True)
'''


def start(queue,kind,*args):
 state,billing,p,_=queue;worker=p.parent/'worker.py'
 if not worker.exists():worker.write_text(WORKER)
 env=dict(os.environ,PYTHONPATH=str(Path.cwd()),PYTHONDONTWRITEBYTECODE='1')
 return subprocess.Popen([sys.executable,str(worker),str(state),str(billing),str(p.parent),kind,*map(str,args)],
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)


def finish(p,expected=0):
 out,err=p.communicate(timeout=15);assert p.returncode==expected,(out,err)
 return json.loads(out) if out.strip() else None


def wait_for(path,seconds=10):
 until=time.monotonic()+seconds
 while not path.exists():
  assert time.monotonic()<until,'missing test barrier: '+str(path)
  time.sleep(.01)


def effects(queue):
 p=queue[2].parent/'external-effects.txt'
 return len(p.read_text().splitlines()) if p.exists() else 0


def test_concurrent_registration_cannot_share_native_identity(queue):
 p=request_for(queue);a=start(queue,'enqueue','one',p);b=start(queue,'enqueue','two',p)
 try:
  wait_for(p.parent/'ready-one');wait_for(p.parent/'ready-two');(p.parent/'go').write_text('1')
  results=[finish(a),finish(b)]
 finally:
  for proc in (a,b):
   if proc.poll() is None:proc.kill();proc.wait()
 assert sum(r.get('registered') is True for r in results)==1
 assert manager.status(queue[0],queue[1],mode='SIMULATED')['metrics']['registered_tasks']==1


@pytest.mark.parametrize('kind,code,before_count',[('before',71,0),('after',72,1)])
def test_crash_and_three_restarts_never_repeat_external_effect(queue,kind,code,before_count):
 enqueue(queue);finish(start(queue,kind),code);assert effects(queue)==before_count
 for _ in range(3):
  result=finish(start(queue,'ok'));assert result['reason']=='reconciliation_required' and result['dispatched']==0
 assert effects(queue)==before_count
 stats=manager.status(queue[0],queue[1],mode='SIMULATED')['metrics']
 assert stats['dispatch_claims']==1 and stats['outcomes']['pending']==1 and stats['reconciliation_stops']==3


def test_completed_dispatch_three_process_restarts_are_idle(queue):
 enqueue(queue);assert finish(start(queue,'ok'))['dispatched']==1
 for _ in range(3):assert finish(start(queue,'ok'))['dispatched']==0
 assert effects(queue)==1


def test_live_owner_excludes_second_process_and_next_task_survives(queue):
 enqueue(queue,'one');enqueue(queue,'two');p=queue[2].parent;a=start(queue,'hold')
 try:
  wait_for(p/'held');second=finish(start(queue,'ok'))
  assert second['reason']=='manager_busy' and second['dispatched']==0 and effects(queue)==1
  (p/'release').write_text('1');assert finish(a)['dispatched']==1
 finally:
  if a.poll() is None:a.kill();a.wait()
 assert finish(start(queue,'ok'))['dispatched']==1 and effects(queue)==2
 assert manager.status(queue[0],queue[1],mode='SIMULATED')['metrics']['outcomes']['done']==2
