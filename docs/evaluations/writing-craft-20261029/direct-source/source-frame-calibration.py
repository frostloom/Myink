import base64,json,logging,os,sys,time
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
from chapter_checks import draft_segments
p=json.loads(base64.b64decode(os.environ['SOURCE_FRAME_CALIBRATION']));cases=p['cases']
conn=resolve_connection('audit',{},load_configuration(),tier='normal');provider=_chain_from_override(conn,False).providers[0]
count=0
def emit(v):print(json.dumps(v,ensure_ascii=False),flush=True)
def cap(req):
 global count
 if count>=8:raise RuntimeError('Eight-request frame calibration cap')
 count+=1;emit({'event':'attempt','attempt':count})
provider._client.event_hooks['request'].append(cap)
prompt=p['common_prompt']
def frame_supported(final,case,segments):
 rows=final['actors']
 if set(final)!={'actors'} or len(rows)!=len(case['actors']) or {row['actor'] for row in rows}!=set(case['actors']):raise ValueError('Missing or duplicate actor')
 passed=True
 for row in rows:
  if not isinstance(row['reason'],str) or not row['reason'].strip():raise ValueError('Missing reason')
  def ids(key):
   value=row[key]
   if not isinstance(value,list) or len(value)>4 or any(type(i) is not int or not 0<=i<len(segments) for i in value):raise ValueError('Invalid evidence')
   return value
  if case['kind']=='posture':
   if set(row)!={'actor','seated_during_activity','basis','evidence_ids','reason'} or row['seated_during_activity'] not in ['yes','no','unknown'] or row['basis'] not in ['explicit_posture','clear_implicit_posture','insufficient']:raise ValueError('Invalid posture')
   evidence=ids('evidence_ids')
   if row['seated_during_activity']=='yes' and (not evidence or row['basis']=='insufficient'):raise ValueError('Unsupported posture')
   passed=passed and row['seated_during_activity']=='yes'
  else:
   if set(row)!={'actor','same_route','basis','incoming_evidence_ids','return_evidence_ids','reason'} or row['same_route'] not in ['yes','no','unknown'] or row['basis'] not in ['explicit_identity','matched_routes','different_route','insufficient']:raise ValueError('Invalid route')
   incoming=ids('incoming_evidence_ids');outgoing=ids('return_evidence_ids')
   if row['same_route']=='yes' and (not outgoing or row['basis'] not in ['explicit_identity','matched_routes'] or row['basis']=='matched_routes' and not incoming):raise ValueError('Unsupported identity')
   passed=passed and row['same_route']=='yes'
 return passed

for case in cases:
 segments=draft_segments(case['text']);query={k:case[k] for k in ['actors','requirement','reference_context']};query['draft_segments']=[{'id':i,'text':t} for i,t in enumerate(segments)]
 messages=[{'role':'system','content':prompt+'\n'+p['frame_prompts'][case['kind']]},{'role':'user','content':json.dumps(query,ensure_ascii=False)}]
 payload=provider._payload(messages,model_id=conn['model'],max_tokens=8192,temperature=None,json_mode=True,tools=None,stream=False)
 payload['thinking']={'type':'enabled','budget_tokens':4096};payload['output_config']={'effort':'low'}
 emit({'event':'start','id':case['id'],'model':conn['model']});start=time.monotonic()
 try:
  res=provider._client.post(provider._url,headers=provider._headers(),json=payload);data=res.json();blocks=data.get('content',[]);text=''.join(b.get('text','') for b in blocks if b.get('type')=='text')
  valid=False;final=None;actual=None
  if res.is_success and data.get('stop_reason')!='max_tokens' and text.strip():
   try:
    final=_parse_json(text);actual=frame_supported(final,case,segments);valid=True
   except Exception:pass
  emit({'event':'result','id':case['id'],'valid':valid,'expected_supported':case['expected_supported'],'actual_supported':actual,'correct':valid and actual==case['expected_supported'],'result':final,'http_status':res.status_code,'stop_reason':data.get('stop_reason'),'block_types':[b.get('type') for b in blocks],'usage':{k:data.get('usage',{}).get(k) for k in ['input_tokens','output_tokens','cache_read_input_tokens']},'duration_ms':round((time.monotonic()-start)*1000)})
 except Exception as exc:emit({'event':'error','id':case['id'],'error_type':type(exc).__name__})
emit({'event':'complete','attempts':count})
