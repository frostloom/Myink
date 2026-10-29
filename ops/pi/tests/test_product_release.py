"""Native release approval and durable effects; Docker acceptance is separate."""
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import importlib.util,json
import pytest
from ops.pi.audit import digest
from test_product_activation import activation_inputs,bootstrap_case,context,NOW
from test_product_backup import write
from test_product_business_probe import packet as business_packet


def api():
    assert importlib.util.find_spec('ops.pi.product_release'),'missing native product release controller'
    from ops.pi import product_release
    return product_release


@pytest.fixture
def release_case(activation_inputs,tmp_path):
    ledger,plan,c,*_=activation_inputs;ctx=context(activation_inputs)
    plan['candidate']['config_hash']=ctx['configuration_sha256'];ctx['plan_sha256']=digest(plan)
    cp=tmp_path/'context.json';cpin=write(cp,ctx);ap=tmp_path/'activation.json'
    from ops.pi.product_activation import ACTIONS
    apin=write(ap,dict(schema='pi-product-activation-approval-v2',mode='SIMULATED',target='rehearsal',plan_sha256=digest(plan),context_sha256=cpin,approved_actions=list(ACTIONS),expires_at=plan['expires_at']))
    root=tmp_path/'operation';root.mkdir(mode=0o700)
    write(root/'maintenance-start.json',dict(plan_sha256=digest(plan),started_at=(NOW-timedelta(seconds=1)).isoformat()))
    h=SimpleNamespace(plan=plan,config=c,root=root,ledger=ledger,clock=lambda:NOW,authorize=lambda p:None)
    cfg=dict(schema='pi-product-control-v1',mode='SIMULATED',target='rehearsal',plan_sha256=digest(plan),context_path=str(cp),context_sha256=cpin,activation_approval_path=str(ap),activation_approval_sha256=apin,ingress_before_sha256='f'*64,maximum_stopped_seconds=600,expires_at=plan['expires_at'])
    cfgpath=tmp_path/'control.json';cfgpin=write(cfgpath,cfg);approval=tmp_path/'control-approval.json'
    value=dict(schema='pi-product-control-approval-v1',mode='SIMULATED',target='rehearsal',plan_sha256=digest(plan),config_sha256=cfgpin,approved_actions=['activate','rollback'],expires_at=plan['expires_at']);approvalpin=write(approval,value)
    return h,cfgpath,cfgpin,approval,approvalpin,cfg,value


def controller(case):return api().NativeProductRelease(*case[:5])


def test_control_requires_separate_exact_approval_and_has_no_constructor_effects(release_case):
    r=controller(release_case)
    assert r.config['plan_sha256']==digest(release_case[0].plan)
    assert not (release_case[0].root/'native-control').exists()


@pytest.mark.parametrize('fault',['wrong-plan','wrong-config','old-actions','duplicate-actions','expired','wrong-mode','extra-field','negative-budget','boolean-budget','oversize-budget'])
def test_control_packet_rejections_precede_native_intent(release_case,fault):
    h,path,pin,approval,_,cfg,value=release_case
    if fault=='wrong-plan':value['plan_sha256']='0'*64
    elif fault=='wrong-config':value['config_sha256']='0'*64
    elif fault=='old-actions':value['approved_actions']=['backup_pre']
    elif fault=='duplicate-actions':value['approved_actions']=['activate','activate']
    elif fault=='expired':value['expires_at']=(NOW-timedelta(seconds=1)).isoformat()
    elif fault=='wrong-mode':value['mode']='ACTUAL'
    elif fault=='extra-field':cfg['allow_unknown']=True
    elif fault=='negative-budget':cfg['maximum_stopped_seconds']=-1
    elif fault=='boolean-budget':cfg['maximum_stopped_seconds']=True
    elif fault=='oversize-budget':cfg['maximum_stopped_seconds']=1801
    if fault in ('extra-field','negative-budget','boolean-budget','oversize-budget'):
        pin=write(path,cfg);value['config_sha256']=pin
    apin=write(approval,value)
    with pytest.raises(ValueError):api().NativeProductRelease(h,path,pin,approval,apin)
    assert not (h.root/'native-control').exists()


def test_post_failure_never_opens_and_original_intents_cannot_redispatch(release_case):
    r=controller(release_case);h=release_case[0];calls=[]
    def post():
        assert h.ledger.get('product-control:'+h.plan['operation_id']+':activate:post')['status']=='pending'
        calls.append('post');raise TimeoutError('outcome not confirmed')
    def flow():
        r._effect('post',post);calls.append('open');return {'verified':True}
    with pytest.raises(TimeoutError):r._operation('activate',flow)
    assert calls==['post']
    assert h.ledger.get('product-control:'+h.plan['operation_id']+':activate')['status']=='uncertain'
    with pytest.raises(ValueError):r._operation('activate',flow)
    assert calls==['post']


def test_revoked_approval_between_effects_prevents_open(release_case):
    r=controller(release_case);calls=[]
    def post():
        calls.append('post');write(release_case[3],{});return {'verified':True}
    def flow():
        r._effect('post',post);r._effect('open',lambda:calls.append('open'));return {'verified':True}
    with pytest.raises(ValueError):r._operation('activate',flow)
    assert calls==['post']


def test_native_operation_crash_keeps_pending_and_never_replays(release_case):
    r=controller(release_case);h=release_case[0];calls=[]
    def crash():calls.append('effect');raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):r._operation('activate',lambda:r._effect('post',crash))
    assert h.ledger.get('product-control:'+h.plan['operation_id']+':activate')['status']=='pending'
    with pytest.raises(ValueError):r._operation('activate',lambda:r._effect('post',crash))
    assert calls==['effect']


@pytest.mark.parametrize('post_fails',[False,True])
def test_release_qualifies_post_before_single_start_and_open(release_case,post_fails,monkeypatch):
    r=controller(release_case);calls=[]
    r._prepared=lambda:None;r._scope=lambda:{};r._ingress=lambda closed:{};r._state=lambda role,barriers:{}
    r._inventory=lambda phase:(calls.append('references-'+phase) or {'verified':True})
    r.actor.create=lambda role:(calls.append('create-'+role) or [])
    r._installed=lambda:(calls.append('installed') or {'verified':True})
    def post():
        calls.append('post')
        if post_fails:raise TimeoutError
        return {'verified':True}
    r._post=post;r.actor.start=lambda role:(calls.append('start-'+role) or {'verified':True})
    r._open=lambda role:(calls.append('open-'+role) or {'verified':True})
    if post_fails:
        with pytest.raises(TimeoutError):r.activate()
        assert calls==['references-PRE','create-candidate','installed','post']
    else:
        assert r.activate().status=='done'
        assert calls==['references-PRE','create-candidate','installed','post','references-POST','start-candidate','open-candidate']


def test_superseded_owner_prevents_even_closing_current_ingress(release_case):
    r=controller(release_case);calls=[];r._scope=lambda:{}
    current=dict(id=1,epoch=r.plan['operation_id'],deadline=r.plan['expires_at'],admission_closed=False,consumer_blocked=False,**{k:r.plan['candidate'][k] for k in ('deployment_id','generation','owner','image_ids')})
    r.host._cid=lambda role:'1'*64
    current['owner']='manual-owner';r.actor._json=lambda args:current
    r.host._caddy=lambda:(calls.append('ingress') or {})
    with pytest.raises(ValueError,match='superseded'):r._close()
    assert not calls


def test_clean_original_control_has_no_historical_post_debt(release_case):
    h=release_case[0]
    api()._preflight_recovery(h.ledger,h.plan['operation_id'],{'schema_context':'a'*64,'tool_context':'b'*64},h.clock())


@pytest.mark.parametrize('kind',['release','backup'])
def test_historical_unqualified_recovery_blocks_before_ingress(release_case,kind):
    h=release_case[0];h.ledger.intent('old-release',kind,{'release_pair_id':'old','phase':'POST','backup_id':'legacy'})
    with pytest.raises(ValueError,match='recovery'):
        api()._preflight_recovery(h.ledger,h.plan['operation_id'],{'schema_context':'a'*64,'tool_context':'b'*64},h.clock())


@pytest.mark.parametrize('failure',[None,'business','post'])
def test_v2_business_then_post_then_distinct_admission_start(release_case,tmp_path,failure):
    h,path,pin,approval,ap,config,permit=release_case
    pp=tmp_path/'business.json';ppin=write(pp,business_packet(h.plan,config['context_sha256']))
    config.update(schema='pi-product-control-v2',business_probe_path=str(pp),business_probe_sha256=ppin)
    pin=write(path,config);permit['config_sha256']=pin;ap=write(approval,permit)
    r=api().NativeProductRelease(h,path,pin,approval,ap);calls=[]
    r._prepared=lambda:None;r._scope=lambda:{};r._ingress=lambda closed:{};r._state=lambda role,barriers:{}
    r._inventory=lambda phase:(calls.append('references-'+phase) or {'verified':True})
    r.actor.create=lambda role:(calls.append('create') or [])
    r.actor.start=lambda role:(calls.append('validation-start') or {'verified':True})
    r.actor.stop=lambda role:(calls.append('validation-stop') or {'verified':True})
    def business():
        calls.append('business')
        if failure=='business':raise ValueError('data differs')
        return {'verified':True}
    def post():
        calls.append('post')
        if failure=='post':raise TimeoutError
        return {'verified':True}
    r._business=business;r._post=post;r._installed=lambda:(calls.append('installed') or {'verified':True})
    r.actor.start_admission=lambda:(calls.append('admission-start') or {'verified':True})
    r._open=lambda role:(calls.append('open') or {'verified':True})
    if failure:
        with pytest.raises((ValueError,TimeoutError)):r.activate()
        assert 'admission-start' not in calls and 'open' not in calls
        if failure=='business':assert 'post' not in calls
    else:
        assert r.activate().status=='done'
        assert calls==['references-PRE','create','validation-start','business','validation-stop','installed','post','references-POST','admission-start','open']


def test_admission_start_cannot_create_intent_without_qualified_original_phases(release_case):
    r=controller(release_case)
    with pytest.raises(ValueError):r.actor.start_admission()
    assert not (r.host.root/'native-actions').exists()


def test_legacy_six_action_approval_cannot_authorize_admission_phase(release_case):
    from ops.pi.product_activation import NativeActivation,LEGACY_ACTIONS
    h,path,pin,permit,permit_pin,cfg,_=release_case
    p=__import__('pathlib').Path(cfg['activation_approval_path']);value=json.loads(p.read_bytes())
    value.update(schema='pi-product-activation-approval-v1',approved_actions=list(LEGACY_ACTIONS));ap=write(p,value)
    actor=NativeActivation(h,cfg['context_path'],cfg['context_sha256'],p,ap)
    assert actor.protocol_version==1
    with pytest.raises(ValueError,match='separate admission'):actor.start_admission()
    assert not (h.root/'native-actions').exists()


@pytest.mark.parametrize('status',[None,'uncertain','wrong-config'])
def test_admission_start_requires_exact_completed_post(release_case,status):
    from ops.pi.contracts import Receipt
    r=controller(release_case);h=r.host;op=h.plan['operation_id'];root='product-control:'+op+':activate'
    for action in ('start_candidate','stop_candidate'):
        name='native:'+op+':'+action;h.ledger.intent(name,'product_native_action',dict(plan_sha256=digest(h.plan),context_sha256=r.actor.context_pin,action=action));h.ledger.finish(Receipt(name,'done',dict(verified=True)))
    h.ledger.intent(root,'product_control',dict(plan_sha256=digest(h.plan),config_sha256=r.pin,action='activate'))
    for step in ('business','stop-validation','post','start-admission'):
        if step=='post' and status is None:continue
        name=root+':'+step;h.ledger.intent(name,'product_control_step',dict(plan_sha256=digest(h.plan),config_sha256='0'*64 if step=='post' and status=='wrong-config' else r.pin,step=step))
        if step!='start-admission':h.ledger.finish(Receipt(name,'uncertain' if step=='post' and status=='uncertain' else 'done',dict(verified=True)))
    with pytest.raises(ValueError):r.actor.start_admission()
    assert not (h.root/'native-actions').exists()
