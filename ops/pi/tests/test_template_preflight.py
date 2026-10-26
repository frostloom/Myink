"""Package validation must precede even the first selection provider callback."""
from pathlib import Path
from copy import deepcopy
import time

import pytest

from ops.pi.contracts import Receipt
from ops.pi.development_inputs import digest, file_hash, ledger_snapshot, read_json
from ops.pi.maintenance_adapters import FileReview
from ops.pi.maintenance_handoff import run_local_development
from ops.pi.tests.test_development_inputs import config_file
from ops.pi.tests.test_maintenance_adapters import pack


def context(pack):
    adapter,ctx,c,template,review=pack
    tasks=[deepcopy(ctx['task'])]
    return dict(ctx,tasks=tasks,source_sha256=c['source_sha256'],catalog_sha256=digest(tasks))


def test_unsigned_template_checks_are_readonly_and_not_execution_approval(pack):
    from ops.pi.development_inputs import prepare, prepare_template
    adapter,ctx,c,template,_=pack
    Path(c['review_path']).unlink()
    c['review_sha256']='0'*64;template.write_text(__import__('json').dumps(c))
    before={str(p):p.read_bytes() for p in template.parent.rglob('*') if p.is_file()}
    result=prepare_template(template)
    assert result[4] is None
    assert not Path(c['root']).exists()
    assert before=={str(p):p.read_bytes() for p in template.parent.rglob('*') if p.is_file()}
    with pytest.raises((ValueError,OSError)):prepare(template)


def test_preflight_validates_without_waiting_for_review_or_creating_output(pack):
    adapter,ctx,c,template,_=pack
    adapter.reviewer=FileReview(seconds=1)
    before=ledger_snapshot(c['ledger_path'])
    result=adapter.preflight(dict(context(pack),mode='ACTUAL'))
    assert result.status=='done' and result.evidence['verified'] is True
    assert result.evidence['catalog_sha256']==digest([ctx['task']])
    assert result.evidence['templates']=={'names':file_hash(template)}
    assert list(adapter.root.iterdir())==[] and not Path(c['root']).exists()
    assert ledger_snapshot(c['ledger_path'])==before


@pytest.mark.parametrize('artifact',['policy','credential','plan','baseline','test'])
def test_insecure_template_artifact_blocks_actual_before_analyzer(pack,artifact):
    adapter,ctx,c,template,_=pack
    adapter.reviewer=FileReview(seconds=1)
    Path(c[artifact+'_path']).chmod(0o644)
    called=[];before=ledger_snapshot(c['ledger_path'])
    def analyze(ctx):
        called.append('analyze')
        raise AssertionError('provider sentinel must not be called')
    r=run_local_development(template.parent/'control.sqlite','invalid-private-'+artifact,[ctx['task']],
        billing_ledger_path=c['ledger_path'],source_identity=lambda:c['source_sha256'],analyze=analyze,
        prepare_development=adapter,mode='ACTUAL',deadline=time.monotonic()+1800)
    assert r.status=='blocked' and called==[]
    assert ledger_snapshot(c['ledger_path'])==before and list(adapter.root.iterdir())==[]


def test_missing_actual_preflight_hook_never_calls_analyzer(pack):
    adapter,ctx,c,template,_=pack;called=[]
    def analyze(value):
        called.append('analyze')
        return Receipt(value['operation_id'],'done',dict(verified=True,mode='ACTUAL',binding=value['input_hash'],
            proposal=dict(task_id=None,source_sha256=None,evidence_sha256=None,reason='synthetic no-work')))
    r=run_local_development(template.parent/'control.sqlite','missing-hook',[ctx['task']],
        billing_ledger_path=c['ledger_path'],source_identity=lambda:c['source_sha256'],analyze=analyze,
        prepare_development=lambda _:None,mode='ACTUAL',deadline=time.monotonic()+1800)
    assert r.status=='blocked' and called==[]


def test_all_catalog_templates_checked_before_selection(pack):
    adapter,ctx,c,template,_=pack
    second=deepcopy(ctx['task']);second['task_id']='unprepared'
    r=adapter.preflight(dict(context(pack),tasks=[ctx['task'],second]))
    assert r.status=='blocked' and list(adapter.root.iterdir())==[]


@pytest.mark.parametrize('change',['source','gold','baseline','billing','template_sha'])
def test_catalog_preflight_rejects_drift(pack,change):
    adapter,ctx,c,template,_=pack;value=context(pack)
    if change=='source':(Path(c['source_path'])/'src/a.py').write_text('drift')
    elif change=='gold':Path(c['test_path']).write_text('different')
    elif change=='baseline':value['tasks'][0]['baseline']['failures']=0
    elif change=='billing':adapter.billing=template.parent/'wrong.sqlite'
    else:adapter.templates['names']['sha256']='0'*64
    assert adapter.preflight(value).status=='blocked'


def test_completed_cycle_replay_does_not_repeat_preflight(pack):
    adapter,ctx,c,template,_=pack;adapter.reviewer=FileReview(seconds=1);calls=[]
    original=adapter.preflight
    def preflight(value):calls.append('preflight');return original(value)
    adapter.preflight=preflight
    def analyze(value):
        calls.append('analyze')
        return Receipt(value['operation_id'],'done',dict(verified=True,mode='ACTUAL',binding=value['input_hash'],
            proposal=dict(task_id=None,source_sha256=None,evidence_sha256=None,reason='synthetic no-work')))
    opts=dict(billing_ledger_path=c['ledger_path'],source_identity=lambda:c['source_sha256'],analyze=analyze,
              prepare_development=adapter,mode='ACTUAL',deadline=time.monotonic()+1800)
    control=template.parent/'control.sqlite'
    r=run_local_development(control,'replay',[ctx['task']],**opts)
    assert r.status=='done' and calls==['preflight','analyze']
    Path(c['test_path']).chmod(0o644)
    assert run_local_development(control,'replay',[ctx['task']],**opts)==r
    assert calls==['preflight','analyze']


def test_cancellation_after_readonly_package_check_is_blocked_before_analysis(pack):
    adapter,ctx,c,template,_=pack;adapter.reviewer=FileReview(seconds=1);calls=[]
    original=adapter.preflight
    def preflight(value):
        result=original(value);value['cancel'].set();return result
    adapter.preflight=preflight
    r=run_local_development(template.parent/'control.sqlite','cancel-after-package',[ctx['task']],
        billing_ledger_path=c['ledger_path'],source_identity=lambda:c['source_sha256'],
        analyze=lambda _:calls.append('analyze'),prepare_development=adapter,
        mode='ACTUAL',deadline=time.monotonic()+1800,cancel=ctx['cancel'])
    assert r.status=='blocked' and calls==[]


def test_preflight_cannot_mutate_the_catalog_seen_by_analyzer(pack):
    adapter,ctx,c,template,_=pack;adapter.reviewer=FileReview(seconds=1)
    original=adapter.preflight;expected=deepcopy(ctx['task'])
    def preflight(value):
        result=original(value);value['tasks'][0]['problem']='mutated observation';return result
    adapter.preflight=preflight
    def analyze(value):
        assert value['tasks']==[expected]
        return Receipt(value['operation_id'],'done',dict(verified=True,mode='ACTUAL',binding=value['input_hash'],
            proposal=dict(task_id=None,source_sha256=None,evidence_sha256=None,reason='synthetic no-work')))
    r=run_local_development(template.parent/'control.sqlite','immutable-package-context',[ctx['task']],
        billing_ledger_path=c['ledger_path'],source_identity=lambda:c['source_sha256'],analyze=analyze,
        prepare_development=adapter,mode='ACTUAL',deadline=time.monotonic()+1800)
    assert r.status=='done'


@pytest.mark.parametrize('field,value',[('mode','SIMULATED'),('verified',1),('binding','wrong'),('catalog_sha256','wrong')])
def test_unbound_preflight_receipt_never_calls_analyzer(pack,field,value):
    adapter,ctx,c,template,_=pack;adapter.reviewer=FileReview(seconds=1);calls=[]
    original=adapter.preflight
    def preflight(context):
        r=original(context)
        return Receipt(r.operation_id,r.status,dict(r.evidence,**{field:value}))
    adapter.preflight=preflight
    r=run_local_development(template.parent/'control.sqlite','unbound-package-'+field,[ctx['task']],
        billing_ledger_path=c['ledger_path'],source_identity=lambda:c['source_sha256'],
        analyze=lambda _:calls.append('analyze'),prepare_development=adapter,
        mode='ACTUAL',deadline=time.monotonic()+1800)
    assert r.status=='blocked' and calls==[]
