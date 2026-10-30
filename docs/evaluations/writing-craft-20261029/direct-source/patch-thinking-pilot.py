import base64,json,logging,os,sys,time
from copy import deepcopy
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json,_check_draft
from myink.workflow import prompts
from myink.workflow.patches import parse_patches,apply_patches
from myink.seed import STYLE_PRESETS
from myink.db import new_session
from myink.writing_resources import catalog,capture_role_prompts
from myink.writing_resource_seed import builtin_resources
from myink.writing_resource_runtime import bind_resources
from chapter_checks import draft_segments
payload=json.loads(base64.b64decode(os.environ['DIRECT_PIPELINE']))
case=payload['case'];draft=payload['draft'];people=payload['participants'];CAP=4;attempts=0
config=load_configuration();connections={};providers={}
events=list(case['expected_events'])
if case['must_end'] not in events:events.append(case['must_end'])
writer_events=list(events)
if case['goal'] not in events:events.append(case['goal'])
sources=[{'id':i,'mode':'obligation','text':text} for i,text in enumerate(events)]
facts=[{'id':len(sources)+i,'mode':'consistency','text':text} for i,text in enumerate(case['facts'])]
context={'previous_tail':case['previous_tail'],'facts':case['facts']}
def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)
def cap_request(request):
 global attempts
 if attempts>=CAP:raise RuntimeError('Request cap exhausted')
 attempts+=1;emit({'event':'attempt','attempt':attempts})
for role in ['audit','writer']:
 connections[role]=resolve_connection(role,{},config,tier='normal');providers[role]=_chain_from_override(connections[role],False).providers[0]
 providers[role]._client.event_hooks['request'].append(cap_request)
emit({'event':'start','id':payload['id'],'request_cap':CAP,'models':{r:c['model'] for r,c in connections.items()}})
class IncompleteOutput(ValueError):
 def __init__(self,message,content):super().__init__(message);self.content=content

def ask(messages,*,stage,role='audit',thinking=True,tokens=8192,json_mode=True):
 provider=providers[role];start=time.monotonic()
 request=provider._payload(messages,model_id=connections[role]['model'],max_tokens=tokens,temperature=None if thinking else (0 if role=='audit' else .3),json_mode=json_mode,tools=None,stream=False)
 request['thinking']={'type':'enabled','budget_tokens':4096} if thinking else {'type':'disabled'}
 if thinking:request['output_config']={'effort':'low'}
 try:response=provider._client.post(provider._url,headers=provider._headers(),json=request)
 except Exception as error:raise RuntimeError('Provider request failed: '+type(error).__name__) from None
 if not response.is_success:
  emit({'event':'provider_error','stage':stage,'http_status':response.status_code});raise RuntimeError('Provider status failed')
 data=response.json();blocks=data.get('content',[]);text=''.join(b.get('text','') for b in blocks if b.get('type')=='text')
 emit({'event':'usage','stage':stage,'thinking':thinking,'stop_reason':data.get('stop_reason'),'block_types':[b.get('type') for b in blocks],'usage':{k:data.get('usage',{}).get(k) for k in ['input_tokens','output_tokens','cache_read_input_tokens']},'duration_ms':round((time.monotonic()-start)*1000)})
 if data.get('stop_reason')=='max_tokens':raise IncompleteOutput('Model output truncated',text)
 if not text.strip():raise IncompleteOutput('No complete final answer',text)
 return text

def checked(messages,check,*,stage,role='audit',thinking=True,tokens=8192,json_mode=True):
 for attempt in range(2):
  text=None
  try:
   text=ask(messages,stage=stage,role=role,thinking=thinking,tokens=tokens,json_mode=json_mode)
   data=_parse_json(text) if json_mode else text
   result=check(data);emit({'event':'candidate','stage':stage,'data':data if json_mode else None});return result
  except ValueError as error:
   emit({'event':'invalid_candidate','stage':stage,'error':str(error)[:500]})
   if attempt:raise
   old=getattr(error,'content',text)
   messages=list(messages)
   if json_mode and old:messages.append({'role':'assistant','content':old})
   messages.append({'role':'user','content':'上一版未通过输出校验，请完整重新输出，不是续写或讲解。保持原始事实，不为想要结论改变判断。具体错误：'+str(error)[:500]})

def finding(source,reason,ids,segments,*,suffix='',actor=None,focus=None):
 target=(actor+'：' if actor else '')+(focus or source['text'])
 return {'conflict_key':'direct-'+str(source['id'])+suffix,'conflict_type':'plotline','severity':'major','scope':'unknown','evidence':[{'chapter':2,'quote':segments[i]} for i in ids],
 'suggestion':'仅修复/澄清原要求中确实未兑现或冲突的部分：'+target+'。实际依据：'+reason+'。保持原始世界观、前文和角色权限；不添加新凭证、能力、通道来绕过限制；不强求验收原词，不改已成立的含蓄表达。相同问题只修一次。'}

style=payload.get('style_profile') or next(r['style_profile'] for r in STYLE_PRESETS if r['id']=='natural-narration')
# Bind the same candidate writing resources and baseline profile as the saved drafts.
with new_session() as db:
    documents=catalog(db,include_automatic=True)
    roles=capture_role_prompts(db)
definitions={r['id']:r for r in builtin_resources()}
base_ids={'writing-rule:continuity','expression-rule:bans','expression-rule:prose','writing-rule:scene-causality','expression-rule:dialogue','writing-rule:genre-pacing'}
genre=next(r for r in documents if r['kind']=='genre' and r['name']==case['genre'])
selections=[]
for row in documents:
    selected=(row['id'] in base_ids or row['id']==genre['id'] or row['kind']=='genre_rule' and genre['body']['catalog_id'] in row['body'].get('genre_ids',[]))
    if selected:
        body=definitions[row['id']]['body'] if row['id']=='writing-rule:continuity' else row['body']
        selections.append({'resource_id':row['id'],'kind':row['kind'],'name':row['name'],'origin':'platform','body':deepcopy(body)})
craft=definitions['genre-rule:craft-realism-suspense']
if genre['body']['catalog_id'] in craft['body']['genre_ids']:
    selections.append({'resource_id':craft['id'],'kind':craft['kind'],'name':craft['name'],'origin':'platform','body':deepcopy(craft['body'])})
for role in ['writer','planner']:roles[role]={'body':deepcopy(definitions['role-prompt:'+role]['body'])}
snapshot={'configured':True,'selections':selections,'role_prompts':roles}
writer_context={'short_context':[{'kind':'prev_chapter_tail','tail':case['previous_tail']}], 'long_term_facts':[{'content':f,'is_hard':True} for f in case['facts']]}
emit({'event':'writing_resources','resource_ids':[r['resource_id'] for r in selections],'style':'original-natural-narration'})

segments=draft_segments(draft)
if payload['id']=='P05':
 source=sources[2]
 ids=[i for i,t in enumerate(segments) if '原路' in t or '干沟' in t]
 reason='宁师姐明确沿来路返回；秦鹤只说明有条干沟可出去，没有建立它就是他进入时走的路线。双方都沿自己的来路返回这一原要求尚未完整兑现。'
else:
 source=facts[-1]
 ids=[i for i,t in enumerate(segments) if '口令' in t or '导出' in t or '压缩包' in t]
 reason='作者和旁白明确值班员没有管理员口令或新的导出权限，但随后输入口令并实际导出日志。不能通过补写口令或新授权化解，须保持原作者限制。'
findings=[finding(source,reason,ids,segments)]
state={'draft':draft,'chapter_seq':2,'plan':{'goals':[case['goal']],'expected_events':writer_events,'hard_constraints':case['facts']},'style_profile':style,'audit_verdict':{'findings':findings}}
with bind_resources(snapshot):messages=prompts.patch_messages(state)
messages[-1]['content']+='\n【前章现场证据】\n'+case['previous_tail']
message_text='\n'.join(m['content'] for m in messages)
for required in [case['goal'],*writer_events,*case['facts']]:
 if required not in message_text:raise ValueError('Missing original author input')
for repeat in range(2):
 for thinking in [False,True]:
  try:
   text=ask(messages,stage='patch-pilot-'+str(repeat)+'-'+str(thinking),role='writer',thinking=thinking,tokens=8192,json_mode=False)
   patches=parse_patches(text);patched=apply_patches(draft,patches)
   emit({'event':'result','id':payload['id'],'repeat':repeat,'thinking':thinking,'applied':patched.applied,'reason':patched.rejected_reason,'patches':text,'text':patched.content if patched.applied else draft})
  except Exception as error:emit({'event':'pilot_failed','id':payload['id'],'repeat':repeat,'thinking':thinking,'error_type':type(error).__name__,'reason':str(error)[:400]})
emit({'event':'complete','id':payload['id'],'attempts':attempts})
