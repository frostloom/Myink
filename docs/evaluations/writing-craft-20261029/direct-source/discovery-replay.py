import base64,json,logging,os,sys,time
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
from chapter_checks import draft_segments
p=json.loads(base64.b64decode(os.environ['DISCOVERY_REPLAY']));batches=p['batches']
conn=resolve_connection('audit',{},load_configuration(),tier='normal');provider=_chain_from_override(conn,False).providers[0]
count=0
def emit(v):print(json.dumps(v,ensure_ascii=False),flush=True)
def cap(req):
 global count
 if count>=6:raise RuntimeError('Six-request source replay cap')
 count+=1;emit({'event':'attempt','attempt':count})
provider._client.event_hooks['request'].append(cap)
for thinking in [False,True]:
 for batch in batches:
  query={'units':batch['units']};messages=[{'role':'system','content':p['prompt']},{'role':'user','content':json.dumps(query,ensure_ascii=False)}]
  payload=provider._payload(messages,model_id=conn['model'],max_tokens=8192,temperature=None if thinking else 0,json_mode=True,tools=None,stream=False)
  payload['thinking']={'type':'enabled','budget_tokens':4096} if thinking else {'type':'disabled'}
  if thinking:payload['output_config']={'effort':'low'}
  emit({'event':'start','id':batch['id'],'thinking':thinking});start=time.monotonic()
  try:
   res=provider._client.post(provider._url,headers=provider._headers(),json=payload);data=res.json();blocks=data.get('content',[]);text=''.join(b.get('text','') for b in blocks if b.get('type')=='text');final=None;valid=False;correct=False
   if res.is_success and data.get('stop_reason')!='max_tokens' and text.strip():
    try:
     final=_parse_json(text);rows=final['units'];mapping={u['unit_id']:u for u in batch['units']}
     if set(final)!={'units'} or len(rows)!=len(mapping) or {r['unit_id'] for r in rows}!=set(mapping):raise ValueError('Incomplete inventory')
     actual={}
     for row in rows:
      if row['status'] not in ['framed','none','uncertain'] or bool(row['frames'])!=(row['status']=='framed'):raise ValueError('Bad applicability')
      frames=[]
      for frame in row['frames']:
       if frame['kind'] not in ['posture','route_identity'] or not frame['source_quote'] or frame['source_quote'] not in mapping[row['unit_id']]['requirement'] or not frame['actors'] or any(a not in mapping[row['unit_id']]['actors'] for a in frame['actors']):raise ValueError('Invalid frame')
       frames.append([frame['kind'],sorted(frame['actors'])])
      actual[str(row['unit_id'])]=sorted(frames)
     valid=True;correct=actual==batch['expected'] and all(r['status']!='uncertain' for r in rows)
    except Exception:pass
   emit({'event':'result','id':batch['id'],'thinking':thinking,'valid':valid,'correct':correct,'result':final,'http_status':res.status_code,'stop_reason':data.get('stop_reason'),'usage':{k:data.get('usage',{}).get(k) for k in ['input_tokens','output_tokens','cache_read_input_tokens']},'duration_ms':round((time.monotonic()-start)*1000)})
  except Exception as exc:emit({'event':'error','id':batch['id'],'thinking':thinking,'error_type':type(exc).__name__})
emit({'event':'complete','attempts':count})
