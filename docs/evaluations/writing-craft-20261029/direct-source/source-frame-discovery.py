import base64,json,logging,os,sys,time
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
units=json.loads(base64.b64decode(os.environ['SOURCE_FRAME_DISCOVERY']))
conn=resolve_connection('audit',{},load_configuration(),tier='normal');provider=_chain_from_override(conn,False).providers[0]
count=0
def emit(v):print(json.dumps(v,ensure_ascii=False),flush=True)
def cap(req):
 global count
 if count>=5:raise RuntimeError('Five-request source-frame discovery cap')
 count+=1;emit({'event':'attempt','attempt':count})
provider._client.event_hooks['request'].append(cap)
prompt='你只读作者原始要求，不读正文。为每个unit识别是否需要两种专门核对：posture仅指要求某人物已经/实际坐下或坐着参与活动；route_identity指要求某人物拟定或实际返回路线与本人来时路线相同。只识别原句真的要求的对象，不扩大演员集合。\n坐姿：只答应以后坐、仅提到坐下的假话、明确没有坐下、只共同查看但未要求坐，都不新增坐姿核对。有人扶别人坐，只核对真正坐的人，不要求扶的人也坐。原句集体必须落座时列齐每位相关成员。\n路线：只要求有路可出、回到同一目的地、明确改道或撒谎说走原路，不等于要求实际同一路线。甲原路、乙改道时只列甲。原句决定按原路返回也要核对路线同一性，不要求已走到终点。\n群体空间关系、禁止跨越/瞬移、算术/权限等不属于这两类，由原始要求核对负责，不能硬拆为坐姿或同一路线。reference_context只用于人物身份与代词，不得把上下文额外目标搬入本条。actors是可用规范姓名，输出只用这些姓名；有第三人时不自动全选。\n每个unit_id必须有且只有一项，不重新编号。source_quote必须是该unit.requirement里的逐字非空连续片段，不能来自context。status=framed时frames至少一项，none时空数组，确实无法解析用uncertain且空数组，不脑补。只返回严格JSON:{"units":[{"unit_id":0,"status":"framed|none|uncertain","frames":[{"kind":"posture|route_identity","actors":["规范姓名"],"source_quote":"原句片段"}],"reason":"为何这些人需要核对，或为何不触发"}]}。不改写requirement，不输出自由文本命题。'
for offset in range(0,len(units),4):
 batch=units[offset:offset+4];query=[{k:u[k] for k in ['unit_id','requirement','actors','reference_context']} for u in batch];mapping={u['unit_id']:u for u in batch}
 messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps({'units':query},ensure_ascii=False)}]
 payload=provider._payload(messages,model_id=conn['model'],max_tokens=4096,temperature=0,json_mode=True,tools=None,stream=False);payload['thinking']={'type':'disabled'}
 emit({'event':'start','offset':offset,'ids':list(mapping),'model':conn['model']});start=time.monotonic()
 try:
  res=provider._client.post(provider._url,headers=provider._headers(),json=payload);data=res.json();blocks=data.get('content',[]);text=''.join(b.get('text','') for b in blocks if b.get('type')=='text');final=None;valid=False;scored=[]
  if res.is_success and data.get('stop_reason')!='max_tokens' and text.strip():
   try:
    final=_parse_json(text);rows=final['units']
    if set(final)!={'units'} or len(rows)!=len(batch) or any(type(row.get('unit_id')) is not int for row in rows) or {row['unit_id'] for row in rows}!=set(mapping):raise ValueError('Missing source units')
    for row in rows:
     if set(row)!={'unit_id','status','frames','reason'} or row['status'] not in ['framed','none','uncertain'] or not isinstance(row['frames'],list) or len(row['frames'])>4 or not isinstance(row['reason'],str) or not row['reason'].strip():raise ValueError('Invalid unit')
     if bool(row['frames'])!=(row['status']=='framed'):raise ValueError('Invalid applicability')
     source=mapping[row['unit_id']];atoms=[];seen=set()
     for frame in row['frames']:
      if set(frame)!={'kind','actors','source_quote'} or frame['kind'] not in ['posture','route_identity'] or not isinstance(frame['actors'],list) or not frame['actors'] or len(set(frame['actors']))!=len(frame['actors']) or any(a not in source['actors'] for a in frame['actors']):raise ValueError('Invalid frame actors')
      q=frame['source_quote']
      if not isinstance(q,str) or not q.strip() or q not in source['requirement']:raise ValueError('Invented source quote')
      key=(frame['kind'],tuple(sorted(frame['actors'])),q)
      if key in seen:raise ValueError('Duplicate frame')
      seen.add(key);atoms.extend((frame['kind'],actor) for actor in frame['actors'])
     actual=sorted(set(atoms));expected=sorted(tuple(x) for x in source['expected'])
     scored.append({'unit_id':row['unit_id'],'correct':row['status']!='uncertain' and actual==expected,'actual':actual,'expected':expected})
    valid=True
   except Exception:pass
  emit({'event':'result','offset':offset,'valid':valid,'scores':scored if valid else [],'result':final,'http_status':res.status_code,'stop_reason':data.get('stop_reason'),'block_types':[b.get('type') for b in blocks],'usage':{k:data.get('usage',{}).get(k) for k in ['input_tokens','output_tokens','cache_read_input_tokens']},'duration_ms':round((time.monotonic()-start)*1000)})
 except Exception as exc:emit({'event':'error','offset':offset,'error_type':type(exc).__name__})
emit({'event':'complete','attempts':count})
