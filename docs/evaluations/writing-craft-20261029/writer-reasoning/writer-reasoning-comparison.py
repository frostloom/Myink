import base64,hashlib,json,logging,os,sys,time
from copy import deepcopy
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.db import new_session
from myink.writing_resources import catalog,capture_role_prompts
from myink.writing_resource_seed import builtin_resources
from myink.writing_resource_runtime import bind_resources
from myink.workflow import prompts
from myink.workflow.nodes import _check_draft
from myink.seed import STYLE_PRESETS
samples=json.loads(base64.b64decode(os.environ['WRITER_REASONING']))
conn=resolve_connection('writer',{},load_configuration(),tier='normal')
provider=_chain_from_override(conn,False).providers[0]
if provider.name()!='anthropic':raise RuntimeError('Expected existing Anthropic connection')
with new_session() as db:documents=catalog(db,include_automatic=True);roles=capture_role_prompts(db)
definitions={r['id']:r for r in builtin_resources()}
style=next(v['style_profile'] for v in STYLE_PRESETS if v['id']=='natural-narration')
base_ids={'writing-rule:continuity','expression-rule:bans','expression-rule:prose','writing-rule:scene-causality','expression-rule:dialogue','writing-rule:genre-pacing'}
count=0
def emit(v):print(json.dumps(v,ensure_ascii=False),flush=True)
def cap(req):
 global count
 if count>=12:raise RuntimeError('Twelve-request writer comparison cap')
 count+=1;emit({'event':'attempt','attempt':count})
provider._client.event_hooks['request'].append(cap)
prepared={}
for sample in samples:
 c=sample['case'];genre=next(r for r in documents if r['kind']=='genre' and r['name']==c['genre']);selections=[]
 for row in documents:
  if row['id'] in base_ids or row['id']==genre['id'] or row['kind']=='genre_rule' and genre['body']['catalog_id'] in row['body'].get('genre_ids',[]):
   body=definitions[row['id']]['body'] if row['id']=='writing-rule:continuity' else row['body']
   selections.append({'resource_id':row['id'],'kind':row['kind'],'name':row['name'],'origin':'platform','body':deepcopy(body)})
 craft=definitions['genre-rule:craft-realism-suspense']
 if genre['body']['catalog_id'] in craft['body']['genre_ids']:selections.append({'resource_id':craft['id'],'kind':craft['kind'],'name':craft['name'],'origin':'platform','body':deepcopy(craft['body'])})
 admitted=deepcopy(roles)
 for role in ['writer','planner']:admitted[role]={'body':deepcopy(definitions['role-prompt:'+role]['body'])}
 snapshot={'configured':True,'selections':selections,'role_prompts':admitted}
 context={'short_context':[{'kind':'prev_chapter_tail','chapter':1,'tail':c['previous_tail']}],'long_term_facts':[{'content':f,'is_hard':True} for f in c['facts']]}
 plan={'goals':[c['goal']],'expected_events':[*c['expected_events'],c['must_end']],'hard_constraints':c['facts'],'transition':{'mode':'continue','pending_action':c['goal'],'opening_beat':c['goal']}}
 with bind_resources(snapshot):messages=prompts.write_messages(context,plan,style_profile=style,target_words=650)
 rendered='\n'.join(m['content'] for m in messages)
 if any(value not in rendered and json.dumps(value,ensure_ascii=False)[1:-1] not in rendered for value in [c['previous_tail'],c['goal'],*c['facts'],*plan['expected_events']]):raise ValueError('Writer lost benchmark source')
 prepared[sample['id']]=messages
 emit({'event':'inputs','id':sample['id'],'model':conn['model'],'prompt_sha256':hashlib.sha256(json.dumps(messages,ensure_ascii=False).encode()).hexdigest(),'resource_ids':[r['resource_id'] for r in selections],'style':'original-natural-narration'})
requests=[]
for i,sample in enumerate(samples):
 for mode in (['current','thinking_low'] if i%2==0 else ['thinking_low','current']):requests.append((sample['id'],mode,1))
for sample in samples:requests.append((sample['id'],'thinking_low',2))
for case_id,mode,repeat in requests:
 messages=prepared[case_id];payload=provider._payload(messages,model_id=conn['model'],max_tokens=8192,temperature=.7,json_mode=False,tools=None,stream=False)
 payload['thinking']={'type':'disabled'} if mode=='current' else {'type':'enabled','budget_tokens':4096}
 if mode=='thinking_low':payload['output_config']={'effort':'low'};payload.pop('temperature',None)
 emit({'event':'start','id':case_id,'mode':mode,'repeat':repeat});start=time.monotonic()
 try:
  res=provider._client.post(provider._url,headers=provider._headers(),json=payload);data=res.json();blocks=data.get('content',[])
  text=''.join(b.get('text','') for b in blocks if b.get('type')=='text');draft=None;valid=False
  if res.is_success and data.get('stop_reason')!='max_tokens' and text.strip():
   try:draft=_check_draft(text);valid=True
   except Exception:pass
  emit({'event':'sample','id':case_id,'mode':mode,'repeat':repeat,'http_status':res.status_code,'stop_reason':data.get('stop_reason'),'block_types':[b.get('type') for b in blocks],'valid':valid,'text':draft,'invalid_final_text':text if not valid else None,'usage':{k:data.get('usage',{}).get(k) for k in ['input_tokens','output_tokens','cache_read_input_tokens']},'duration_ms':round((time.monotonic()-start)*1000)})
 except Exception as exc:emit({'event':'sample_error','id':case_id,'mode':mode,'repeat':repeat,'error_type':type(exc).__name__})
emit({'event':'complete','attempts':count})
