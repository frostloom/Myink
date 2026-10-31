"""A real asynchronous waiter receives the original delayed FileReview."""
from pathlib import Path
from types import SimpleNamespace
import subprocess,sys,time
from ops.pi.tests.test_manager_review_worker import published,handoff,completed,review_config,dossier_input,config_file,proof,write,NOW,select,prepared_config
from ops.pi.development_inputs import file_hash,read_json


def test_delayed_selection_preparation_and_review_unblock_original_waiter(published,proof,monkeypatch,tmp_path):
    from ops.pi import nightly_driver as driver
    from ops.pi.manager_review_worker import tick
    done=tmp_path/'published';ready=tmp_path/'waiter-ready'
    process=subprocess.Popen([sys.executable,'-I','-S','-B','-c',
        'import pathlib,time,sys\np=pathlib.Path(sys.argv[1]);pathlib.Path(sys.argv[2]).touch()\nend=time.monotonic()+20\nwhile not p.exists() and time.monotonic()<end: time.sleep(.01)\nsys.exit(0 if p.exists() else 3)',str(done),str(ready)])
    real_sleep=time.sleep;stages=[];task=[None]
    def command(argv,**kwargs):
        if argv[1]=='show':
            live=process.poll() is None
            return SimpleNamespace(stdout=('ActiveState='+('active' if live else 'inactive')+'\nResult=success\n').encode(),returncode=0)
        if argv[-1]=='myink-pi-review-worker.service':
            if not stages:
                assert tick(published[0],file_hash(published[0]),clock=lambda:NOW)['status']=='waiting_selection'
                sp,sc,task[0]=select(published,proof,monkeypatch);stages.append('selection')
            elif len(stages)==1:
                assert tick(published[0],file_hash(published[0]),clock=lambda:NOW)['status']=='waiting_prepared'
                prepared_config(published,task[0]);stages.append('prepared')
            else:
                r=tick(published[0],file_hash(published[0]),clock=lambda:NOW)
                assert r['status']=='published' and r['model_requests']==0
                done.touch();stages.append('review')
        return SimpleNamespace(stdout=b'',returncode=0)
    try:
        limit=time.monotonic()+5
        while not ready.exists() and time.monotonic()<limit:real_sleep(.01)
        assert ready.exists()
        monkeypatch.setattr(driver.subprocess,'run',command);monkeypatch.setattr(driver,'_review_scope',lambda task:None)
        monkeypatch.setattr(driver.time,'sleep',lambda seconds:real_sleep(.02))
        result=driver._manager_start(published[1]['task_id'])
        assert result['active'] is False and process.wait(timeout=2)==0
        assert stages[:3]==['selection','prepared','review']
        assert Path(published[4]['lease_path']).parent.joinpath('binding/publication/receipt.json').exists()
    finally:
        if process.poll() is None:process.terminate();process.wait(timeout=5)
