import base64,json,logging,os,sys,time
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
from action_matrix import Action
from action_matrix import resolve_subject_source
p=json.loads(base64.b64decode(os.environ['RETRY_TURN_PROBE']))
config=load_configuration();selected=resolve_connection('audit',{},config,tier='normal')
records=[selected]+[r for r in config['connections'].values() if r.get('enabled') and r.get('model')!=selected['model']]
if len(records)!=2:raise RuntimeError('Expected two existing connections')
count=0
def emit(v):print(json.dumps(v,ensure_ascii=False),flush=True)
def cap(req):
 global count
 if count>=4:raise RuntimeError('Four-request cap')
 count+=1;emit({'event':'attempt','attempt':count})
for record in records:
 provider=_chain_from_override(record,False).providers[0];provider._client.event_hooks['request'].append(cap)
 for role in ['system','user']:
  messages=[*p['messages'],{'role':'assistant','content':p['bad']},{'role':role,'content':p['correction']}]
  payload=provider._payload(messages,model_id=record['model'],max_tokens=4096,temperature=0,json_mode=True,tools=None,stream=False);payload['thinking']={'type':'disabled'}
  emit({'event':'start','model':record['model'],'correction_role':role,'wire_last_role':payload['messages'][-1]['role']})
  start=time.monotonic()
  try:
   res=provider._client.post(provider._url,headers=provider._headers(),json=payload);data=res.json();blocks=data.get('content',[])
   text=''.join(b.get('text','') for b in blocks if b.get('type')=='text');final=None;valid=False
   if res.is_success and data.get('stop_reason')!='max_tokens' and text.strip():
    try:
     final=_parse_json(text)
     if not 1<=len(final['tables'])<=24:raise ValueError('Missing inventory')
     for t in final['tables']:
      if t['event_index']!=0 or not t['source_quote'].strip() or t['source_quote'] not in p['source_event']:raise ValueError('Missing source')
      if t['kind']=='person':resolve_subject_source(t['subject'],t['members'],p['source_event'],p['context_sources'],t.get('subject_quote',''))
      if not t['actions']:raise ValueError('Missing actions')
      for a in t['actions']:Action.model_validate(a)
     valid=True
    except Exception:pass
   emit({'event':'result','model':record['model'],'correction_role':role,'http_status':res.status_code,'stop_reason':data.get('stop_reason'),'block_types':[b.get('type') for b in blocks],'valid_provenance_output':valid,'final_data':final,'final_text':text if not valid else None,'usage':{k:data.get('usage',{}).get(k) for k in ['input_tokens','output_tokens','cache_read_input_tokens']},'duration_ms':round((time.monotonic()-start)*1000)})
  except Exception as exc:emit({'event':'error','model':record['model'],'correction_role':role,'error_type':type(exc).__name__})
emit({'event':'complete','attempts':count})
