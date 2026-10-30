import base64,json,logging,os,sys,time
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow import prompts
from myink.workflow.nodes import _parse_json
from myink.schemas import AuditVerdict
from myink.seed import STYLE_PRESETS
from myink.db import new_session
from myink.writing_resources import capture_role_prompts
from myink.writing_resource_runtime import bind_resources
samples=json.loads(base64.b64decode(os.environ['AUDIT_THINKING']))
conn=resolve_connection('audit',{},load_configuration(),tier='normal')
provider=_chain_from_override(conn,False).providers[0]
style=next(v['style_profile'] for v in STYLE_PRESETS if v['id']=='natural-narration')
with new_session() as db:roles=capture_role_prompts(db)
snapshot={'configured':True,'selections':[],'role_prompts':roles}
count=0
def emit(v):print(json.dumps(v,ensure_ascii=False),flush=True)
def cap(req):
 global count
 if count>=8:raise RuntimeError('Eight-request cap')
 count+=1;emit({'event':'attempt','attempt':count})
provider._client.event_hooks['request'].append(cap)
for sample in samples:
 c=sample['case'];events=[*c['expected_events'],c['must_end']]
 context={'short_context':[{'kind':'prev_chapter_tail','chapter':1,'tail':c['previous_tail']}],'long_term_facts':[{'content':f,'is_hard':True} for f in c['facts']]}
 plan={'goals':[c['goal']],'expected_events':events,'hard_constraints':c['facts']}
 with bind_resources(snapshot):messages=prompts.audit_messages(sample['draft'],plan,context,2,style_profile=style)
 for mode in ['current','thinking_high']:
  payload=provider._payload(messages,model_id=conn['model'],max_tokens=8192,temperature=None,json_mode=True,tools=None,stream=False)
  payload['thinking']={'type':'disabled'} if mode=='current' else {'type':'enabled','budget_tokens':4096}
  if mode=='thinking_high':payload['output_config']={'effort':'high'}
  start=time.monotonic();emit({'event':'start','id':sample['id'],'mode':mode,'model':conn['model']})
  try:
   res=provider._client.post(provider._url,headers=provider._headers(),json=payload);data=res.json()
   blocks=data.get('content',[]);text=''.join(b.get('text','') for b in blocks if b.get('type')=='text')
   valid=False;final=None
   if res.is_success and data.get('stop_reason')!='max_tokens' and text.strip():
    try:
     final=_parse_json(text)
     if not all(k in final for k in ['verdict','findings','reasons','confidence']):raise ValueError('Missing explicit audit fields')
     AuditVerdict(**{k:v for k,v in final.items() if k in AuditVerdict.model_fields});valid=True
    except Exception:pass
   emit({'event':'result','id':sample['id'],'mode':mode,'http_status':res.status_code,'stop_reason':data.get('stop_reason'),'block_types':[b.get('type') for b in blocks],'valid':valid,'judgment':final,'usage':{k:data.get('usage',{}).get(k) for k in ['input_tokens','output_tokens','cache_read_input_tokens']},'duration_ms':round((time.monotonic()-start)*1000)})
  except Exception as exc:emit({'event':'error','id':sample['id'],'mode':mode,'error_type':type(exc).__name__})
emit({'event':'complete','attempts':count})
