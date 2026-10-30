import base64,json,logging,os,sys,time
from copy import deepcopy
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json,_check_draft
from myink.workflow import prompts
from myink.workflow.patches import parse_patches,apply_patches
from myink.seed import STYLE_PRESETS
from myink.db import new_session
from myink.writing_resources import catalog,capture_role_prompts
from myink.writing_resource_seed import builtin_resources
from myink.writing_resource_runtime import bind_resources
from chapter_checks import draft_segments
payload=json.loads(base64.b64decode(os.environ['DIRECT_PIPELINE']))
case=payload['case'];draft=payload['draft'];people=payload['participants'];CAP=32;attempts=0
config=load_configuration();connections={};providers={}
events=list(case['expected_events'])
if case['must_end'] not in events:events.append(case['must_end'])
writer_events=list(events)
if case['goal'] not in events:events.append(case['goal'])
sources=[{'id':i,'mode':'obligation','text':text} for i,text in enumerate(events)]
facts=[{'id':len(sources)+i,'mode':'consistency','text':text} for i,text in enumerate(case['facts'])]
context={'previous_tail':case['previous_tail'],'facts':case['facts']}
def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)
def cap_request(request):
 global attempts
 if attempts>=CAP:raise RuntimeError('Request cap exhausted')
 attempts+=1;emit({'event':'attempt','attempt':attempts})
for role in ['audit','writer']:
 connections[role]=resolve_connection(role,{},config,tier='normal');providers[role]=_chain_from_override(connections[role],False).providers[0]
 providers[role]._client.event_hooks['request'].append(cap_request)
emit({'event':'start','id':payload['id'],'request_cap':CAP,'models':{r:c['model'] for r,c in connections.items()}})
class IncompleteOutput(ValueError):
 def __init__(self,message,content):super().__init__(message);self.content=content

def ask(messages,*,stage,role='audit',thinking=True,tokens=8192,json_mode=True):
 provider=providers[role];start=time.monotonic()
 request=provider._payload(messages,model_id=connections[role]['model'],max_tokens=tokens,temperature=None if thinking else (0 if role=='audit' else .3),json_mode=json_mode,tools=None,stream=False)
 request['thinking']={'type':'enabled','budget_tokens':4096} if thinking else {'type':'disabled'}
 if thinking:request['output_config']={'effort':'low'}
 try:response=provider._client.post(provider._url,headers=provider._headers(),json=request)
 except Exception as error:raise RuntimeError('Provider request failed: '+type(error).__name__) from None
 if not response.is_success:
  emit({'event':'provider_error','stage':stage,'http_status':response.status_code});raise RuntimeError('Provider status failed')
 data=response.json();blocks=data.get('content',[]);text=''.join(b.get('text','') for b in blocks if b.get('type')=='text')
 emit({'event':'usage','stage':stage,'thinking':thinking,'stop_reason':data.get('stop_reason'),'block_types':[b.get('type') for b in blocks],'usage':{k:data.get('usage',{}).get(k) for k in ['input_tokens','output_tokens','cache_read_input_tokens']},'duration_ms':round((time.monotonic()-start)*1000)})
 if data.get('stop_reason')=='max_tokens':raise IncompleteOutput('Model output truncated',text)
 if not text.strip():raise IncompleteOutput('No complete final answer',text)
 return text

def checked(messages,check,*,stage,role='audit',thinking=True,tokens=8192,json_mode=True):
 for attempt in range(2):
  text=None
  try:
   text=ask(messages,stage=stage,role=role,thinking=thinking,tokens=tokens,json_mode=json_mode)
   data=_parse_json(text) if json_mode else text
   result=check(data);emit({'event':'candidate','stage':stage,'data':data if json_mode else None});return result
  except ValueError as error:
   emit({'event':'invalid_candidate','stage':stage,'error':str(error)[:500]})
   if attempt:raise
   old=getattr(error,'content',text)
   messages=list(messages)
   if json_mode and old:messages.append({'role':'assistant','content':old})
   messages.append({'role':'user','content':'上一版未通过输出校验，请完整重新输出，不是续写或讲解。保持原始事实，不为想要结论改变判断。具体错误：'+str(error)[:500]})

DISCOVERY_PROMPT='你只读作者原始要求，不读正文。为每个unit识别是否需要两种专门核对：posture仅指要求某人物已经/实际坐下或坐着参与活动；route_identity指要求某人物拟定或实际返回路线与本人来时路线相同。只识别原句真的要求的对象，不扩大演员集合。\n坐姿：只答应以后坐、仅提到坐下的假话、明确没有坐下、只共同查看但未要求坐，都不新增坐姿核对。有人扶别人坐，只核对真正坐的人，不要求扶的人也坐。原句集体必须落座时列齐每位相关成员。\n路线：只要求有路可出、回到同一目的地、明确改道或撒谎说走原路，不等于要求实际同一路线。甲原路、乙改道时只列甲。原句决定按原路返回也要核对路线同一性，不要求已走到终点。\n群体空间关系、禁止跨越/瞬移、算术/权限等不属于这两类，由原始要求核对负责，不能硬拆为坐姿或同一路线。reference_context只用于人物身份与代词，不得把上下文额外目标搬入本条。actors是可用规范姓名，输出只用这些姓名；有第三人时不自动全选。\n每个unit_id必须有且只有一项，不重新编号。source_quote必须是该unit.requirement里的逐字非空连续片段，不能来自context。status=framed时frames至少一项，none时空数组，确实无法解析用uncertain且空数组，不脑补。只返回严格JSON:{"units":[{"unit_id":0,"status":"framed|none|uncertain","frames":[{"kind":"posture|route_identity","actors":["规范姓名"],"source_quote":"原句片段"}],"reason":"为何这些人需要核对，或为何不触发"}]}。不改写requirement，不输出自由文本命题。'
DIRECT_PROMPT='你是事实核对员，只核对给出的原始requirement，不润色、不重写要求、不评其他目标。obligation模式：原句每一个明确子要求均在正文实际兑现才supported；相反为violated，未兑现为missing，确实无法判定为uncertain。保留原句主体、集体关系、数量、同时/先后、否定范围、决定与完成的差别。禁止某动作不等于要求角色口头宣布一个决定；共同活动不要求每个人独立操作全过程；个人坐姿不能由别人代替。不要按关键词命中判断，不脑补所需权限、资源或路线同一性；允许明确的同义、自然指代和足够清楚的含蓄表达，不要求抄验收原词。\nconsistency模式：requirement为作者给定事实，检查正文是否与之冲突；一致或没有相反内容为supported。先区分开场状态、历史记录、全章持续限制和目标。开场状态允许通过正文明确动作正常推进，不把它冻结到结尾；不能推翻历史记录或明确禁止变化的设定。不要求每条背景在正文重述。人物台词有不可靠性，不自动等同旁白或作者设定。\nreference_context仅用于解指代和理解开场；任务要求本身不是正文已经完成的证据。只用draft_segments编号取正文依据。返回严格JSON：{"status":"supported|violated|missing|uncertain","evidence_ids":[0],"reason":"逐项解释真正的差别或为何全部满足，不扩充义务"}。status只用一个值；evidence_ids为最多四个有效整数。obligation的supported必须有正文证据；violated必须有冲突正文证据。其余可空。不要输出原文引号或其他字段。'
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

def parse_specs(data,items):
 rows=data['units'];mapping={s['id']:s for s in items}
 if set(data)!={'units'} or len(rows)!=len(items) or any(type(row.get('unit_id')) is not int for row in rows) or {row['unit_id'] for row in rows}!=set(mapping):raise ValueError('Incomplete source inventory')
 result=[]
 for row in rows:
  if set(row)!={'unit_id','status','frames','reason'} or row['status'] not in ['framed','none','uncertain'] or not isinstance(row['frames'],list) or len(row['frames'])>4 or not isinstance(row['reason'],str) or not row['reason'].strip():raise ValueError('Invalid source spec')
  if bool(row['frames'])!=(row['status']=='framed'):raise ValueError('Invalid source applicability')
  if row['status']=='uncertain':raise RuntimeError('Unresolved source interpretation')
  source=mapping[row['unit_id']];seen=set()
  for frame in row['frames']:
   if set(frame)!={'kind','actors','source_quote'} or frame['kind'] not in ['posture','route_identity'] or not isinstance(frame['actors'],list) or not frame['actors'] or len(set(frame['actors']))!=len(frame['actors']) or any(a not in people for a in frame['actors']):raise ValueError('Invalid source actors')
   q=frame['source_quote']
   if not isinstance(q,str) or not q.strip() or q not in source['text']:raise ValueError('Invented source quote')
   key=(frame['kind'],tuple(sorted(frame['actors'])),q)
   if key in seen:raise ValueError('Duplicate source frame')
   seen.add(key);result.append({**frame,'source_id':source['id']})
 return result

specs=[]
for offset in range(0,len(sources),4):
 items=sources[offset:offset+4]
 query={'units':[{'unit_id':s['id'],'requirement':s['text'],'actors':people,'reference_context':[case['previous_tail'],*case['facts']]} for s in items]}
 specs.extend(checked([{'role':'system','content':DISCOVERY_PROMPT},{'role':'user','content':json.dumps(query,ensure_ascii=False)}],lambda data:parse_specs(data,items),stage='source_inventory_'+str(offset),thinking=False,tokens=4096))
emit({'event':'source_specs','specs':specs})

def direct_result(data,segments,mode):
 if set(data)!={'status','evidence_ids','reason'} or data['status'] not in ['supported','violated','missing','uncertain'] or not isinstance(data['reason'],str) or not data['reason'].strip():raise ValueError('Invalid direct check')
 ids=data['evidence_ids']
 if not isinstance(ids,list) or len(ids)>8 or any(type(i) is not int or not 0<=i<len(segments) for i in ids):raise ValueError('Invalid direct evidence')
 if (mode=='obligation' and data['status']=='supported' or data['status']=='violated') and not ids:raise ValueError('Missing direct evidence')
 return data

def finding(source,reason,ids,segments,*,suffix='',actor=None,focus=None):
 target=(actor+'：' if actor else '')+(focus or source['text'])
 return {'conflict_key':'direct-'+str(source['id'])+suffix,'conflict_type':'plotline','severity':'major','scope':'unknown','evidence':[{'chapter':2,'quote':segments[i]} for i in ids],
 'suggestion':'仅修复/澄清原要求中确实未兑现或冲突的部分：'+target+'。实际依据：'+reason+'。保持原始世界观、前文和角色权限；不添加新凭证、能力、通道来绕过限制；不强求验收原词，不改已成立的含蓄表达。相同问题只修一次。'}

def confirmation_result(data,source,segments):
 if not isinstance(data,dict) or set(data)!={'decision','requirement_status','source_quote','evidence_ids','reason'}:raise ValueError('Invalid confirmation fields')
 if data['decision'] not in ['confirmed','rejected','uncertain'] or data['requirement_status'] not in ['supported','not_supported','uncertain']:raise ValueError('Invalid confirmation status')
 q=data['source_quote'];ids=data['evidence_ids']
 if not isinstance(q,str) or q and q not in source['text']:raise ValueError('Invalid confirmation source')
 if not isinstance(ids,list) or len(ids)>8 or any(type(i) is not int or not 0<=i<len(segments) for i in ids):raise ValueError('Invalid confirmation evidence')
 if not isinstance(data['reason'],str) or not data['reason'].strip():raise ValueError('Missing confirmation reason')
 if data['decision']=='confirmed' and (not q.strip() or not ids or data['requirement_status']!='not_supported'):raise ValueError('Unsubstantiated confirmation')
 if source['mode']=='obligation' and data['requirement_status']=='supported' and not ids:raise ValueError('Missing fulfillment evidence')
 return data

def confirmation_resolution(data):
 if data['decision']=='confirmed' and data['requirement_status']=='not_supported':return 'repair'
 if data['decision']=='rejected' and data['requirement_status']=='supported':return 'clear'
 return 'hold'

CONFIRM_PROMPT='你独立复核一条审稿意见是否成立，不默认原审稿正确。对照未经改写的requirement、模式、reference_context和完整draft_segments核对。不得为否定审稿而制造例外，也不得把原句强化成额外要求。\n先分清源句的主体、动作对象/作用对象、初始状态与后续状态、持续限制、历史事实、已完成动作和本章结果。一次准备已完成，不等于所有同词动作永远禁止；同一物件后续对不同对象/目的的动作，不能仅因动词类似就当作重演。群体关系不能改成每个人同时占据所有位置；叙述先后不必然证明过程互不重叠。未指明左右的动作不能擅自指定为受伤侧，疼痛不等于所有动作均不可能。角色台词可能回避/撒谎，不自动变成作者世界事实，尤其有充分潜台词时。\nobligation模式的积极结果必须真正兑现，不能以可能发生/可以脑补为支持；明确的间接姿态、自然指代可算，不要求抄验收原词。路线有出口不等于本人来时路线。consistency模式只在源句实际含义下有明确相反事实才判不支持；不要求复述全部背景，正常推进允许。不要因没有明确表示拒绝某行为就说违反禁止。\n若审稿意见确实成立decision=confirmed；意见添加原句没有的要求、误解证据或忽略明确隐含表达时rejected；无法判断uncertain。同时独立给出本条原要求整体的requirement_status=supported|not_supported|uncertain；不能因为驳回一条意见就自动认为全部条件兑现。对积极结果只有完整支持才能supported，缺失/不确定不能强通过。\n只返回严格JSON:{"decision":"confirmed|rejected|uncertain","requirement_status":"supported|not_supported|uncertain","source_quote":"requirement中真正相关的逐字片段，没有则空","evidence_ids":[0],"reason":"说明意见与原句真正含义、正文证据的关系，不泛泛说合理"}。confirmed必须引用源句和实际正文依据；evidence_ids最多8个有效整数。obligation的supported必须有正文证据。不要写引用正文文字，用编号。'

def indexed_batch(final, items, segments):
    mapping = {u['id']: u for u in items}
    if not isinstance(final, dict) or set(final) != {'units'} or (not isinstance(final['units'], list)):
        raise ValueError('Invalid batch')
    rows = final['units']
    if len(rows) != len(items) or {r.get('id') for r in rows} != set(mapping):
        raise ValueError('Incomplete batch')
    for row in rows:
        if set(row) != {'id', 'status', 'evidence_ids', 'reason'} or row['status'] not in ['supported', 'violated', 'missing', 'uncertain']:
            raise ValueError('Invalid result')
        u = mapping[row['id']]
        ids = row['evidence_ids']
        if not isinstance(ids, list) or len(ids) > 8 or any((type(i) is not int or not 0 <= i < len(segments[u['id']]) for i in ids)):
            raise ValueError('Invalid evidence')
        if not isinstance(row['reason'], str) or not row['reason'].strip():
            raise ValueError('Missing reason')
        if (u['mode'] == 'obligation' and row['status'] == 'supported' or row['status'] == 'violated') and (not ids):
            raise ValueError('Missing evidence')
    return {'units': [{**r, 'source_requirement': mapping[r['id']]['requirement']} for r in rows]}

BATCH_PROMPT='你是独立的逐条原要求核对员。每条unit的requirement未经改写，始终以它为标准；不要把原句强化或弱化，也不从别的unit补充本条正文。逐项核对主体、成员、条件、否定范围、时间范围和决定/实际完成的差别，保留自然指代与足够清楚的含蓄表达，不要求验收原词。\nobligation：每个明确条件均有正文实际兑现依据才supported；明确相反事实用violated；必须发生的内容没有兑现证据用missing；证据或原句存在不能可靠消除的歧义用uncertain。consistency：只在正文有与源句真实含义不相容的事实时violated，否则supported；区分初始可变状态与全章持续限制，不要求复述背景。角色台词不自动等同作者事实。\n举证责任对称：supported不得靠脑补填空；violated必须有直接不相容的正文事实，单纯缺少明确支持不是矛盾，叙述先后本身也不能证明过程不重叠；有歧义不能强判冲突或强通过。reference_context仅供解指代和开场状态，不是正文已完成证据。\n返回严格JSON：{"units":[{"id":"原ID","status":"supported|violated|missing|uncertain","evidence_ids":[0],"reason":"具体条件与正文事实关系，简洁说明，不复述评分标准"}]}。每ID恰好一行，不能漏条或跨unit编号；源要求归属由程序按id回填，禁止返回源句或引用字段；evidence_ids仅取该unit正文段落编号，最多8个。obligation的supported、violated必须有正文依据；其余可空。'

def merge_verdicts(first,second):
 statuses=[first['status'],second['status']]
 if statuses==['supported','supported']:return 'pass'
 if all(status in ['missing','violated'] for status in statuses):return 'repair'
 return 'hold'

def read_units(text,items,phase):
 segments=draft_segments(text);observations=[]
 for audit in range(2):
  ordered=items if audit==0 else list(reversed(items));results={}
  for offset in range(0,len(ordered),3):
   selected=ordered[offset:offset+3]
   units=[{'id':'unit-'+str(u['id']),'mode':u['mode'],'requirement':u['text'],'reference_context':context} for u in selected]
   mapping={u['id']:source for u,source in zip(units,selected)}
   wire={'units':[{**u,'draft_segments':[{'id':i,'text':t} for i,t in enumerate(segments)]} for u in units]}
   result=checked([{'role':'system','content':BATCH_PROMPT},{'role':'user','content':json.dumps(wire,ensure_ascii=False)}],lambda data:indexed_batch(data,units,{u['id']:segments for u in units}),stage=phase+'-audit-'+str(audit)+'-batch-'+str(offset))
   for row in result['units']:results[mapping[row['id']]['id']]=row
  if set(results)!={source['id'] for source in items}:raise ValueError('Missing full-source audit coverage')
  observations.append(results)
 merged={}
 for source in items:
  rows=[r[source['id']] for r in observations];decision=merge_verdicts(*rows)
  if source['mode']=='consistency' and decision=='repair' and any(r['status']!='violated' for r in rows):decision='hold'
  merged[source['id']]={'decision':decision,'rows':rows}
  emit({'event':'symmetric_check','phase':phase,'source_id':source['id'],**merged[source['id']]})
 return merged

def inspect(text,phase):
 segments=draft_segments(text);issues={};holds=[]
 def add_issue(source,reason,ids):
  item=issues.setdefault(source['id'],{'source':source,'reasons':[],'ids':set()})
  item['reasons'].append(reason);item['ids'].update(ids)
 results=read_units(text,[*sources,*facts],phase)
 for source in [*sources,*facts]:
  result=results[source['id']]
  if result['decision']=='repair':add_issue(source,'；'.join(r['reason'] for r in result['rows']),sorted({i for r in result['rows'] for i in r['evidence_ids']}))
  elif result['decision']=='hold':holds.append({'source_id':source['id'],'result':result})
 for index,spec in enumerate(specs):
  source=sources[spec['source_id']]
  query={'actors':spec['actors'],'requirement':source['text'],'source_focus':spec['source_quote'],'reference_context':context,'draft_segments':[{'id':i,'text':part} for i,part in enumerate(segments)]}
  frame_case={'kind':spec['kind'],'actors':spec['actors']}
  def validate(data):frame_supported(data,frame_case,segments);return data
  result=checked([{'role':'system','content':payload['frame_common']+'\n'+payload['frame_prompts'][spec['kind']]},{'role':'user','content':json.dumps(query,ensure_ascii=False)}],validate,stage='frame_'+phase+'_'+str(index))
  emit({'event':'frame_check','phase':phase,'source_id':source['id'],'kind':spec['kind'],'result':result})
  for row in result['actors']:
   status=row['seated_during_activity'] if spec['kind']=='posture' else row['same_route']
   if status!='yes':
    ids=row['evidence_ids'] if spec['kind']=='posture' else sorted(set(row['incoming_evidence_ids']+row['return_evidence_ids']))
    add_issue(source,row['actor']+'：'+row['reason'],ids)
 return [finding(v['source'],'；'.join(v['reasons']),sorted(v['ids']),segments) for v in issues.values()],holds

def stage_patch(draft,patches,verify):
 patched=apply_patches(draft,patches)
 if not patched.applied:return draft,False,patched.rejected_reason
 if verify(patched.content) is not True:return draft,False,'repair_target_not_supported'
 return patched.content,True,None

def inspect_targets(text,findings):
 segments=draft_segments(text)
 selected={int(f['conflict_key'].split('-')[1]) for f in findings}
 items=[source for source in [*sources,*facts] if source['id'] in selected]
 results=read_units(text,items,'repair_target')
 if any(result['decision']!='pass' for result in results.values()):return False
 for index,spec in enumerate(specs):
  if spec['source_id'] not in selected:continue
  source=sources[spec['source_id']]
  query={'actors':spec['actors'],'requirement':source['text'],'source_focus':spec['source_quote'],'reference_context':context,'draft_segments':[{'id':i,'text':part} for i,part in enumerate(segments)]}
  frame_case={'kind':spec['kind'],'actors':spec['actors']}
  def validate(data):frame_supported(data,frame_case,segments);return data
  result=checked([{'role':'system','content':payload['frame_common']+'\n'+payload['frame_prompts'][spec['kind']]},{'role':'user','content':json.dumps(query,ensure_ascii=False)}],validate,stage='repair_target_frame_'+str(index))
  emit({'event':'repair_target_frame','source_id':source['id'],'result':result})
  if not frame_supported(result,frame_case,segments):return False
 return True

style=payload.get('style_profile') or next(r['style_profile'] for r in STYLE_PRESETS if r['id']=='natural-narration')
# Bind the same candidate writing resources and baseline profile as the saved drafts.
with new_session() as db:
    documents=catalog(db,include_automatic=True)
    roles=capture_role_prompts(db)
definitions={r['id']:r for r in builtin_resources()}
base_ids={'writing-rule:continuity','expression-rule:bans','expression-rule:prose','writing-rule:scene-causality','expression-rule:dialogue','writing-rule:genre-pacing'}
genre=next(r for r in documents if r['kind']=='genre' and r['name']==case['genre'])
selections=[]
for row in documents:
    selected=(row['id'] in base_ids or row['id']==genre['id'] or row['kind']=='genre_rule' and genre['body']['catalog_id'] in row['body'].get('genre_ids',[]))
    if selected:
        body=definitions[row['id']]['body'] if row['id']=='writing-rule:continuity' else row['body']
        selections.append({'resource_id':row['id'],'kind':row['kind'],'name':row['name'],'origin':'platform','body':deepcopy(body)})
craft=definitions['genre-rule:craft-realism-suspense']
if genre['body']['catalog_id'] in craft['body']['genre_ids']:
    selections.append({'resource_id':craft['id'],'kind':craft['kind'],'name':craft['name'],'origin':'platform','body':deepcopy(craft['body'])})
for role in ['writer','planner']:roles[role]={'body':deepcopy(definitions['role-prompt:'+role]['body'])}
snapshot={'configured':True,'selections':selections,'role_prompts':roles}
writer_context={'short_context':[{'kind':'prev_chapter_tail','tail':case['previous_tail']}], 'long_term_facts':[{'content':f,'is_hard':True} for f in case['facts']]}
emit({'event':'writing_resources','resource_ids':[r['resource_id'] for r in selections],'style':'original-natural-narration'})

try:
 diagnostic_text=draft
 findings,holds=inspect(draft,'before')
 if findings:
  state={'draft':draft,'chapter_seq':2,'plan':{'goals':[case['goal']],'expected_events':writer_events,'hard_constraints':case['facts']},'style_profile':style,'audit_verdict':{'findings':findings}}
  with bind_resources(snapshot):messages=prompts.patch_messages(state)
  messages[-1]['content']+='\n【前章现场证据】\n'+case['previous_tail']
  patches=checked(messages,parse_patches,stage='patch_candidate',role='writer',thinking=False,tokens=3000,json_mode=False)
  proposed=apply_patches(draft,patches)
  candidate,target_verified,reason=stage_patch(draft,patches,lambda text:inspect_targets(text,findings))
  emit({'event':'staged_patch','target_verified':target_verified,'reason':reason,'proposed_text':proposed.content if proposed.applied else None})
  if target_verified:
   diagnostic_text=candidate
   findings,holds=inspect(candidate,'final')
   if not findings and not holds:draft=candidate
 emit({'event':'final','passed':not findings and not holds,'unresolved':findings,'uncertain':holds,'text':draft,'diagnostic_text':diagnostic_text,'attempts':attempts})
except Exception as error:
 emit({'event':'pipeline_failed','error_type':type(error).__name__,'reason':str(error)[:400],'attempts':attempts,'text':draft,'diagnostic_text':diagnostic_text})
 raise SystemExit(1)
