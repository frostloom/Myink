import base64,json,logging,os,sys,time
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
from chapter_checks import draft_segments
p=json.loads(base64.b64decode(os.environ['SYMMETRIC_AUDIT']));units=p['units']
conn=resolve_connection('audit',{},load_configuration(),tier='normal');provider=_chain_from_override(conn,False).providers[0]
count=0
def emit(v):print(json.dumps(v,ensure_ascii=False),flush=True)
def cap(req):
 global count
 if count>=6:raise RuntimeError('Six-request symmetric audit cap')
 count+=1;emit({'event':'attempt','attempt':count})
provider._client.event_hooks['request'].append(cap)
for audit in range(2):
 ordered=units if audit==0 else list(reversed(units))
 for offset in range(0,len(ordered),3):
  items=ordered[offset:offset+3];mapping={u['id']:u for u in items};segments={u['id']:draft_segments(u['text']) for u in items}
  query={'units':[{**{k:u[k] for k in ['id','mode','requirement','reference_context']},'draft_segments':[{'id':i,'text':t} for i,t in enumerate(segments[u['id']])]} for u in items]}
  messages=[{'role':'system','content':p['prompt']},{'role':'user','content':json.dumps(query,ensure_ascii=False)}]
  payload=provider._payload(messages,model_id=conn['model'],max_tokens=8192,temperature=None,json_mode=True,tools=None,stream=False);payload['thinking']={'type':'enabled','budget_tokens':4096};payload['output_config']={'effort':'low'}
  emit({'event':'start','audit':audit,'offset':offset,'ids':list(mapping)});start=time.monotonic()
  try:
   res=provider._client.post(provider._url,headers=provider._headers(),json=payload);data=res.json();blocks=data.get('content',[]);text=''.join(b.get('text','') for b in blocks if b.get('type')=='text');final=None;valid=False
   if res.is_success and data.get('stop_reason')!='max_tokens' and text.strip():
    try:
     final=_parse_json(text);rows=final['units']
     if set(final)!={'units'} or len(rows)!=len(items) or {r['id'] for r in rows}!=set(mapping):raise ValueError('Incomplete batch')
     for row in rows:
      u=mapping[row['id']];ids=row['evidence_ids'];q=row['source_quote']
      if set(row)!={'id','status','source_quote','evidence_ids','reason'} or row['status'] not in ['supported','violated','missing','uncertain'] or not isinstance(q,str) or not q.strip() or q not in u['requirement'] or not isinstance(ids,list) or len(ids)>8 or any(type(i) is not int or not 0<=i<len(segments[u['id']]) for i in ids) or not isinstance(row['reason'],str) or not row['reason'].strip():raise ValueError('Invalid evidence')
      if (u['mode']=='obligation' and row['status']=='supported' or row['status']=='violated') and not ids:raise ValueError('Missing evidence')
     valid=True
    except Exception:pass
   emit({'event':'result','audit':audit,'offset':offset,'valid':valid,'result':final,'expected':{u['id']:u['expected'] for u in items},'http_status':res.status_code,'stop_reason':data.get('stop_reason'),'usage':{k:data.get('usage',{}).get(k) for k in ['input_tokens','output_tokens','cache_read_input_tokens']},'duration_ms':round((time.monotonic()-start)*1000)})
  except Exception as exc:emit({'event':'error','audit':audit,'offset':offset,'error_type':type(exc).__name__})
emit({'event':'complete','attempts':count})
