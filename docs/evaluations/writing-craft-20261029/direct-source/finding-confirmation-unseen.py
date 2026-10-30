import base64,json,logging,os,sys,time
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
from chapter_checks import draft_segments
p=json.loads(base64.b64decode(os.environ['FINDING_CONFIRMATION_CALIBRATION']));cases=p['cases']
conn=resolve_connection('audit',{},load_configuration(),tier='normal');provider=_chain_from_override(conn,False).providers[0]
count=0
def emit(v):print(json.dumps(v,ensure_ascii=False),flush=True)
def cap(req):
 global count
 if count>=12:raise RuntimeError('Twelve-request finding-confirmation cap')
 count+=1;emit({'event':'attempt','attempt':count})
provider._client.event_hooks['request'].append(cap)
for case in cases:
 segments=draft_segments(case['text']);query={k:case[k] for k in ['mode','requirement','reference_context','candidate_problem']};query['draft_segments']=[{'id':i,'text':part} for i,part in enumerate(segments)]
 messages=[{'role':'system','content':p['prompt']},{'role':'user','content':json.dumps(query,ensure_ascii=False)}]
 payload=provider._payload(messages,model_id=conn['model'],max_tokens=8192,temperature=None,json_mode=True,tools=None,stream=False);payload['thinking']={'type':'enabled','budget_tokens':4096};payload['output_config']={'effort':'low'}
 emit({'event':'start','id':case['id'],'model':conn['model']});start=time.monotonic()
 try:
  res=provider._client.post(provider._url,headers=provider._headers(),json=payload);data=res.json();blocks=data.get('content',[]);text=''.join(b.get('text','') for b in blocks if b.get('type')=='text');final=None;valid=False;actual=None
  if res.is_success and data.get('stop_reason')!='max_tokens' and text.strip():
   try:
    final=_parse_json(text)
    if set(final)!={'decision','requirement_status','source_quote','evidence_ids','reason'} or final['decision'] not in ['confirmed','rejected','uncertain'] or final['requirement_status'] not in ['supported','not_supported','uncertain']:raise ValueError('Invalid decision')
    q=final['source_quote'];ids=final['evidence_ids']
    if not isinstance(q,str) or q and q not in case['requirement'] or not isinstance(ids,list) or len(ids)>8 or any(type(i) is not int or not 0<=i<len(segments) for i in ids) or not isinstance(final['reason'],str) or not final['reason'].strip():raise ValueError('Invalid source evidence')
    if final['decision']=='confirmed' and (not q.strip() or not ids or final['requirement_status']!='not_supported'):raise ValueError('Unsubstantiated confirmation')
    if case['mode']=='obligation' and final['requirement_status']=='supported' and not ids:raise ValueError('Missing fulfillment evidence')
    actual=final['decision']=='confirmed';valid=True
   except Exception:pass
  expected_status=case['expected_requirement_status']
  emit({'event':'result','id':case['id'],'valid':valid,'expected_confirmed':case['expected_confirmed'],'actual_confirmed':actual,'correct':valid and actual==case['expected_confirmed'] and final['requirement_status']==expected_status,'result':final,'http_status':res.status_code,'stop_reason':data.get('stop_reason'),'usage':{k:data.get('usage',{}).get(k) for k in ['input_tokens','output_tokens','cache_read_input_tokens']},'duration_ms':round((time.monotonic()-start)*1000)})
 except Exception as exc:emit({'event':'error','id':case['id'],'error_type':type(exc).__name__})
emit({'event':'complete','attempts':count})
