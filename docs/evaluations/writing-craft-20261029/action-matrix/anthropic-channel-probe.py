"""Four raw Anthropic-protocol requests to existing connections; no reasoning text logged."""
import base64,json,logging,os,sys,time
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
from myink.providers.think_tag_stripper import isolate_response_body
from chapter_checks import parse_fidelity
p=json.loads(base64.b64decode(os.environ['CHANNEL_PROBE']))
config=load_configuration();selected=resolve_connection('audit',{},config,tier='normal')
records=[selected]+[r for r in config['connections'].values() if r.get('enabled') and r.get('model')!=selected['model']]
if len(records)!=2:raise RuntimeError('Expected two existing connections')
count=0
def emit(v):print(json.dumps(v,ensure_ascii=False),flush=True)
def hook(req):
 global count
 if count>=4:raise RuntimeError('Four-request Anthropic channel cap reached')
 count+=1;emit({'event':'attempt','attempt':count})
case=p['case'];query={k:v for k,v in case.items() if k not in ['id','expected']}
messages=[{'role':'system','content':p['prompt']},{'role':'user','content':json.dumps(query,ensure_ascii=False)}]
for record in records:
 provider=_chain_from_override(record,False).providers[0]
 if provider.name()!='anthropic':raise RuntimeError('Unexpected protocol')
 provider._client.event_hooks['request'].append(hook)
 for mode in ['application_payload','thinking_high']:
  payload=provider._payload(messages,model_id=record['model'],max_tokens=6000,temperature=0,json_mode=True,tools=None,stream=False)
  payload['thinking']={'type':'disabled'} if mode=='application_payload' else {'type':'enabled','budget_tokens':4096}
  if mode=='thinking_high':payload['output_config']={'effort':'high'};payload.pop('temperature',None)
  emit({'event':'request_metadata','model':record['model'],'protocol':record['protocol'],'mode':mode,'thinking_toggle':payload['thinking']['type']})
  started=time.monotonic()
  try:
   response=provider._client.post(provider._url,headers=provider._headers(),json=payload)
   response.raise_for_status();data=response.json()
  except Exception as exc:
   emit({'event':'request_error','model':record['model'],'mode':mode,'error_type':type(exc).__name__,'status_code':getattr(getattr(exc,'response',None),'status_code',None)});continue
  blocks=data.get('content',[]);types=[b.get('type') for b in blocks]
  text=''.join(b.get('text','') for b in blocks if b.get('type')=='text')
  body=isolate_response_body(text,json_mode=True)
  valid=False;actual=None;final=None
  if body.strip() and data.get('stop_reason')!='max_tokens':
   try:final=_parse_json(body);actual=parse_fidelity(final,case['events']).passed;valid=True
   except Exception:pass
  usage=data.get('usage',{})
  emit({'event':'result','model':record['model'],'reported_model':str(data.get('model',''))[:160],'mode':mode,'block_types':types,'text_present':bool(text.strip()),'thinking_present':any(t in ['thinking','reasoning'] for t in types),'stop_reason':data.get('stop_reason'),'valid_response':valid,'expected':case['expected'],'actual':actual,'correct':actual==case['expected'] if valid else None,'final_data':final,'input_tokens':usage.get('input_tokens',0),'output_tokens':usage.get('output_tokens',0),'cache_read_input_tokens':usage.get('cache_read_input_tokens',0),'duration_ms':round((time.monotonic()-started)*1000)})
emit({'event':'complete','attempts':count})
