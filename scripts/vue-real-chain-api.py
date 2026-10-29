"""Real dedicated API/AMQP worker/local-model acceptance; no API monkeypatches."""
from __future__ import annotations
import json, os, time, uuid
from pathlib import Path
import httpx
from sqlalchemy import select, or_
from myink.config import settings
from myink.db import new_session
from myink.models import User, AgentRun
from sqlalchemy.engine import make_url
database=make_url(settings.database_url)
assert settings.app_env=='test' and database.host=='127.0.0.1' and database.port==28432
BASE='http://127.0.0.1:28110/api/v1'
client=httpx.Client(timeout=90,trust_env=False)
checks=[]; tokens={}; run=str(int(time.time()))
metadata={'base':BASE,'password':'VueChainPass0025','invitation':'vue-chain-local-invite-0025','run':run}
def call(method,path,data=None,token=None,status=200,**kwargs):
    r=client.request(method,BASE+path,json=data,headers={'Authorization':'Bearer '+token} if token else {},**kwargs)
    assert r.status_code==status,(method,path,r.status_code,r.text[:400]);return r.json()
def ok(name):checks.append(name);print(name,flush=True)
def wait(tid,statuses,timeout=100):
    start=time.time()
    while time.time()-start<timeout:
        response=client.get(BASE+'/tasks/'+tid,headers={'Authorization':'Bearer '+tokens['user']})
        if response.status_code==404:
            time.sleep(.4);continue
        assert response.status_code==200,(response.status_code,response.text[:300])
        out=response.json()
        if out['status'] in statuses:return out
        if out['status']=='failed':raise AssertionError(('worker task failed',out.get('error'),tid))
        time.sleep(.4)
    raise AssertionError(('task timed out',tid,out['status'],out.get('error')))
for role in ['user','other','admin']:
    username='chain_'+role+'_'+run
    auth=call('POST','/auth/register',{'username':username,'password':metadata['password'],'invitation_code':metadata['invitation']},status=201)
    tokens[role]=auth['token'];metadata[role]={'username':username,'userId':auth['user_id']}
    with new_session() as db:
        u=db.get(User,uuid.UUID(auth['user_id']));u.daily_quota=100;u.daily_budget_yuan=100
        if role=='admin':u.role='admin'
        db.commit()
ok('real_three_account_registration')
# Real long creation uses model-client HTTP for setup and full outline.
p=call('POST','/projects',{'request_id':str(uuid.uuid4()),'title':'真实队列长篇','genre':'现实','chapter_count':50,'target_words':1000,'form':'long'},tokens['user']);pid=p['id'];metadata['longProjectId']=pid
setup=call('POST',f'/projects/{pid}/setup-draft',{'premise':'林砚在渡口调查失踪木箱'},tokens['user']);assert not setup.get('error'),setup
assert setup['draft']['characters'][0]['name']=='林砚'
call('PUT',f'/projects/{pid}/setup',setup['draft'],tokens['user']);ok('long_setup_via_real_model_http')
outline=call('POST',f'/projects/{pid}/outline-draft',{'premise':'林砚在渡口调查失踪木箱','chapter_count':50},tokens['user']);assert not outline.get('error'),outline
call('PUT',f'/projects/{pid}/outline',{**outline['outline'],'premise':'林砚在渡口调查失踪木箱','chapter_count':50},tokens['user']);ok('long_outline_via_real_model_http')
httpx.post('http://127.0.0.1:28120/_control',json={'extract_card':True},trust_env=False).raise_for_status()
task=call('POST',f'/projects/{pid}/chapters/next/generate',{'seq':1,'mode':'manual'},tokens['user'],status=202);tid=task['task_id'];metadata['longTaskId']=tid
out=wait(tid,{'awaiting_plan'});planrun=next(r for r in out['runs'] if r['node']=='plan_chapter');detail=planrun['detail'];assert detail.get('plan'),out
ok('actual_queue_worker_manual_plan_persisted')
call('POST',f'/tasks/{tid}/plan/confirm',{'plan':detail['plan'],'expected_attempt':detail.get('plan_attempt',1)},tokens['user']);out=wait(tid,{'awaiting_review'})
candidates=call('GET',f'/projects/{pid}/candidates',token=tokens['user']);card=next(c for c in candidates if c['kind']=='character_card')
ok('actual_worker_stream_write_extract_human_review')
call('POST',f'/projects/{pid}/candidates/{card["candidate_id"]}/reject',{'mode':'revise','reason':'人物证词应由林砚核实，不增人物档案'},tokens['user'])
for cand in candidates:
    if cand['candidate_id']!=card['candidate_id']:call('POST',f'/projects/{pid}/candidates/{cand["candidate_id"]}/confirm',token=tokens['user'])
call('POST',f'/tasks/{tid}/resume',token=tokens['user']);out=wait(tid,{'done'});ok('actual_human_rejection_revise_resume_to_done')
chapters=call('GET',f'/projects/{pid}/chapters',token=tokens['user']);assert len(chapters)==1 and chapters[0]['status']=='confirmed',chapters
cid=chapters[0]['id'];metadata['longChapterId']=cid
original=call('GET',f'/projects/{pid}/chapters/{cid}',token=tokens['user']);assert '林砚' in original['content'];ok('actual_worker_chapter_database_persistence')
rewrite=call('POST',f'/projects/{pid}/chapters/{cid}/generate',{'seq':1,'rewrite':True,'mode':'auto'},tokens['user'],status=202)
wait(rewrite['task_id'],{'done'});versions=call('GET',f'/projects/{pid}/chapters/{cid}/versions',token=tokens['user']);assert versions['versions'];ok('actual_worker_rewrite_creates_history')
# Short chat -> model plan -> ready project -> actual queue worker.
session=call('GET','/short/creation',token=tokens['user']);sid=session['session']['id']
chat=call('POST',f'/short/creation/sessions/{sid}/messages',{'content':'写两章渡口调查故事，每章一千字','card':{}},tokens['user']);assert chat['ready'],chat
commit=call('POST',f'/short/creation/sessions/{sid}/commit',{'card':chat['session']['card'],'style_item_id':None},tokens['user']);spid=commit['project_id'];metadata['shortProjectId']=spid
ok('short_chat_card_plan_commit_via_real_model_http')
snapshot=call('GET',f'/projects/{spid}/writing-resources',token=tokens['user'])
call('PUT',f'/projects/{spid}/writing-resources',{'expected_revision':snapshot['revision'],'selections':[]},tokens['user']);assert not call('GET',f'/projects/{spid}/tasks',token=tokens['user']);ok('short_resource_first_has_no_generation_before_manual_start')
httpx.post('http://127.0.0.1:28120/_control',json={'short_revise':True},trust_env=False).raise_for_status()
short=call('POST',f'/projects/{spid}/short/generate',token=tokens['user'],status=202);metadata['shortTaskId']=short['task_id'];out=wait(short['task_id'],{'done'},timeout=150)
sc=call('GET',f'/projects/{spid}/chapters',token=tokens['user']);assert len(sc)==2 and all(c['status']=='confirmed' for c in sc),sc
nodes={r['node'] for r in out['runs']};assert {'short_write','short_review','short_revise'} <= nodes,nodes
ok('actual_short_queue_worker_write_review_revise_persistence')
# Owner boundary and concrete model provenance.
call('GET',f'/projects/{pid}/tasks',token=tokens['other'],status=403);ok('real_foreign_task_project_owner_denied')
with new_session() as db:
    runs=db.scalars(select(AgentRun).where(or_(AgentRun.user_id==uuid.UUID(metadata['user']['userId']), AgentRun.project_id.in_([uuid.UUID(pid),uuid.UUID(spid)])))).all()
    assert runs and all(r.model_id=='fixture-local' or (r.model_id is None and not r.input_tokens and not r.output_tokens) for r in runs),(len(runs),{r.model_id for r in runs})
    metadata['agentRunCount']=len(runs);metadata['modelRunCount']=sum(r.model_id=='fixture-local' for r in runs);metadata['agentRunNodes']=sorted({r.node for r in runs})
ok('database_agent_runs_only_local_fixture_model')
metadata['tokens']=tokens
Path(os.environ.get('MYINK_CHAIN_METADATA','/tmp/myink-vue-chain-metadata-0025.json')).write_text(json.dumps(metadata,ensure_ascii=False))
Path('/tmp/myink-vue-chain-api-receipt-0025.json').write_text(json.dumps({'checks':checks,'count':len(checks),'modelId':'fixture-local','agentRunCount':metadata['agentRunCount'],'modelRunCount':metadata['modelRunCount'],'agentRunNodes':metadata['agentRunNodes']},ensure_ascii=False,indent=2))
print(json.dumps({'passed':len(checks)}))
