"""Repeatable SIMULATED process-recovery evidence; never invokes a provider."""
from pathlib import Path
import argparse
import json,time
import pytest
from ops.pi.development_inputs import file_hash

def main():
    collector_sha=file_hash(__file__)
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    from ops.pi.development_inputs import path
    import stat
    W=Path.cwd();out=path(args.output)
    if out.exists() or not out.parent.is_dir() or stat.S_IMODE(out.parent.stat().st_mode)!=0o700:raise ValueError('new output in private parent required')
    out.mkdir(mode=0o700)
    records={};active=None;pid_records={}
    class Evidence:
     def pytest_collection_modifyitems(self,items):
      module=items[0].module;start=module.start;finish=module.finish
      def begin(queue,kind,*args):
       before=module.effects(queue);p=start(queue,kind,*args)
       entry=dict(kind=kind,before_effects=before,after_effects=None,returncode=None)
       records[active]['processes'].append(entry);pid_records[p.pid]=(entry,queue)
       return p
      def end(p,expected=0):
       result=finish(p,expected);entry,queue=pid_records[p.pid];entry.update(after_effects=module.effects(queue),returncode=p.returncode)
       return result
      module.start=begin;module.finish=end
     def pytest_runtest_setup(self,item):
      nonlocal active
      active=item.nodeid;records[active]=dict(mode='SIMULATED',processes=[],passed=False)
     @pytest.hookimpl(hookwrapper=True)
     def pytest_runtest_makereport(self,item,call):
      outcome=yield;report=outcome.get_result()
      if report.when=='call':records[item.nodeid]['passed']=report.passed;records[item.nodeid]['duration_seconds']=report.duration
    code=pytest.main(['ops/pi/tests/test_manager_recovery.py','-q','--basetemp='+str(out/'tmp'),'--junitxml='+str(out/'tests.xml')],plugins=[Evidence()])
    report=dict(schema='pi-manager-recovery-evidence-v1',mode='SIMULATED',core_pi_modified=False,
     collector_sha256=collector_sha,manager_sha256=file_hash('ops/pi/manager.py'),test_sha256=file_hash('ops/pi/tests/test_manager_recovery.py'),pytest_exit=code,
     scenarios=records,independent_process_starts=sum(len(x['processes']) for x in records.values()),
     model_attempts=None,known_cost_microyuan=None,production_availability=None,paired_efficiency_improvement=None)
    restarts=[]
    for name,entry in records.items():
     if 'crash_and_three_restarts' in name or 'completed_dispatch_three_process_restarts' in name:
      restarts.extend(p for p in entry['processes'][1:] if p['kind']=='ok')
    report['restart_observations']=len(restarts);report['extra_fixture_effects_on_restarts']=sum(x['after_effects']-x['before_effects'] for x in restarts)
    (out/'summary.json').write_text(json.dumps(report,indent=2));assert code==0 and all(x['passed'] for x in records.values())
    assert report['independent_process_starts']==17 and report['restart_observations']==9 and report['extra_fixture_effects_on_restarts']==0
    print(json.dumps({k:v for k,v in report.items() if k!='scenarios'}),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
