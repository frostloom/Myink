import base64,json,logging,os,sys,time
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
p=json.loads(base64.b64decode(os.environ['INVENTORY_PROBE']))
record=resolve_connection('audit',{},load_configuration(),tier='normal')
provider=_chain_from_override(record,False).providers[0]
for mode in p['modes']:
 payload=provider._payload(p['messages'],model_id=record['model'],max_tokens=mode['max_tokens'],temperature=None,json_mode=True,tools=None,stream=False)
 payload['thinking']={'type':'enabled','budget_tokens':4096};payload['output_config']={'effort':mode['effort']}
 start=time.monotonic()
 print(json.dumps({'event':'attempt',**mode}),flush=True)
 try:
  res=provider._client.post(provider._url,headers=provider._headers(),json=payload)
  data=res.json()
  blocks=data.get('content',[]);text=''.join(b.get('text','') for b in blocks if b.get('type')=='text')
  try: final=_parse_json(text) if text.strip() else None
  except Exception:final=None
  print(json.dumps({'event':'result',**mode,'http_status':res.status_code,'error_type':(data.get('error') or {}).get('type'),'stop_reason':data.get('stop_reason'),'block_types':[b.get('type') for b in blocks],'usage':{k:data.get('usage',{}).get(k) for k in ['input_tokens','output_tokens','cache_read_input_tokens']},'final_data':final,'duration_ms':round((time.monotonic()-start)*1000)},ensure_ascii=False),flush=True)
 except Exception as exc:print(json.dumps({'event':'error',**mode,'error_type':type(exc).__name__}),flush=True)
