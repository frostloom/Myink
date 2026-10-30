import base64,json,logging,os,sys,time
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
from chapter_checks import draft_segments
cases=json.loads(base64.b64decode(os.environ['DIRECT_SOURCE_CALIBRATION']))
conn=resolve_connection('audit',{},load_configuration(),tier='normal');provider=_chain_from_override(conn,False).providers[0]
count=0
def emit(v):print(json.dumps(v,ensure_ascii=False),flush=True)
def cap(req):
 global count
 if count>=8:raise RuntimeError('Eight-request direct source calibration cap')
 count+=1;emit({'event':'attempt','attempt':count})
provider._client.event_hooks['request'].append(cap)
prompt='你是事实核对员，只核对给出的原始requirement，不润色、不重写要求、不评其他目标。obligation模式：原句每一个明确子要求均在正文实际兑现才supported；相反为violated，未兑现为missing，确实无法判定为uncertain。保留原句主体、集体关系、数量、同时/先后、否定范围、决定与完成的差别。禁止某动作不等于要求角色口头宣布一个决定；共同活动不要求每个人独立操作全过程；个人坐姿不能由别人代替。不要按关键词命中判断，不脑补所需权限、资源或路线同一性；允许明确的同义、自然指代和足够清楚的含蓄表达，不要求抄验收原词。\nconsistency模式：requirement为作者给定事实，检查正文是否与之冲突；一致或没有相反内容为supported。先区分开场状态、历史记录、全章持续限制和目标。开场状态允许通过正文明确动作正常推进，不把它冻结到结尾；不能推翻历史记录或明确禁止变化的设定。不要求每条背景在正文重述。人物台词有不可靠性，不自动等同旁白或作者设定。\nreference_context仅用于解指代和理解开场；任务要求本身不是正文已经完成的证据。只用draft_segments编号取正文依据。返回严格JSON：{"status":"supported|violated|missing|uncertain","evidence_ids":[0],"reason":"逐项解释真正的差别或为何全部满足，不扩充义务"}。status只用一个值；evidence_ids为最多四个有效整数。obligation的supported必须有正文证据；violated必须有冲突正文证据。其余可空。不要输出原文引号或其他字段。'
for case in cases:
 segments=draft_segments(case['text']);query={k:case[k] for k in ['mode','requirement','reference_context']};query['draft_segments']=[{'id':i,'text':t} for i,t in enumerate(segments)]
 messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps(query,ensure_ascii=False)}]
 payload=provider._payload(messages,model_id=conn['model'],max_tokens=8192,temperature=None,json_mode=True,tools=None,stream=False)
 payload['thinking']={'type':'enabled','budget_tokens':4096};payload['output_config']={'effort':'low'}
 emit({'event':'start','id':case['id'],'model':conn['model']});start=time.monotonic()
 try:
  res=provider._client.post(provider._url,headers=provider._headers(),json=payload);data=res.json();blocks=data.get('content',[]);text=''.join(b.get('text','') for b in blocks if b.get('type')=='text')
  valid=False;final=None;actual=None
  if res.is_success and data.get('stop_reason')!='max_tokens' and text.strip():
   try:
    final=_parse_json(text)
    if set(final)!={'status','evidence_ids','reason'} or final['status'] not in ['supported','violated','missing','uncertain']:raise ValueError('Invalid status')
    ids=final['evidence_ids']
    if not isinstance(ids,list) or len(ids)>4 or any(type(i) is not int or not 0<=i<len(segments) for i in ids) or not isinstance(final['reason'],str) or not final['reason'].strip():raise ValueError('Invalid evidence')
    if (case['mode']=='obligation' and final['status']=='supported' or final['status']=='violated') and not ids:raise ValueError('Missing evidence')
    actual=final['status']=='supported';valid=True
   except Exception:pass
  emit({'event':'result','id':case['id'],'valid':valid,'expected_supported':case['expected_supported'],'actual_supported':actual,'correct':valid and actual==case['expected_supported'],'result':final,'http_status':res.status_code,'stop_reason':data.get('stop_reason'),'block_types':[b.get('type') for b in blocks],'usage':{k:data.get('usage',{}).get(k) for k in ['input_tokens','output_tokens','cache_read_input_tokens']},'duration_ms':round((time.monotonic()-start)*1000)})
 except Exception as exc:emit({'event':'error','id':case['id'],'error_type':type(exc).__name__})
emit({'event':'complete','attempts':count})
