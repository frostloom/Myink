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

def inspect(text,phase):
 segments=draft_segments(text);findings=[]
 for source in [*sources,*facts]:
  query={'mode':source['mode'],'requirement':source['text'],'reference_context':context,'draft_segments':[{'id':i,'text':part} for i,part in enumerate(segments)]}
  result=checked([{'role':'system','content':DIRECT_PROMPT.replace('最多四个有效整数','最多八个有效整数')},{'role':'user','content':json.dumps(query,ensure_ascii=False)}],lambda data:direct_result(data,segments,source['mode']),stage='direct_'+phase+'_'+str(source['id']))
  emit({'event':'direct_check','phase':phase,'source_id':source['id'],'result':result})
  if result['status']!='supported':findings.append(finding(source,result['reason'],result['evidence_ids'],segments))
 for index,spec in enumerate(specs):
  source=sources[spec['source_id']]
  query={'actors':spec['actors'],'requirement':source['text'],'source_focus':spec['source_quote'],'reference_context':context,'draft_segments':[{'id':i,'text':part} for i,part in enumerate(segments)]}
  frame_case={'kind':spec['kind'],'actors':spec['actors']}
  def validate(data):frame_supported(data,frame_case,segments);return data
  messages=[{'role':'system','content':payload['frame_common']+'\n'+payload['frame_prompts'][spec['kind']]},{'role':'user','content':json.dumps(query,ensure_ascii=False)}]
  result=checked(messages,validate,stage='frame_'+phase+'_'+str(index))
  emit({'event':'frame_check','phase':phase,'source_id':source['id'],'kind':spec['kind'],'result':result})
  for row in result['actors']:
   status=row['seated_during_activity'] if spec['kind']=='posture' else row['same_route']
   if status!='yes':
    ids=row['evidence_ids'] if spec['kind']=='posture' else sorted(set(row['incoming_evidence_ids']+row['return_evidence_ids']))
    findings.append(finding(source,row['reason'],ids,segments,suffix='-frame-'+str(index)+'-'+row['actor'],actor=row['actor'],focus=spec['source_quote']))
 return findings

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
 findings=inspect(draft,'before')
 for revision in range(2):
  if not findings:break
  state={'draft':draft,'chapter_seq':2,'plan':{'goals':[case['goal']],'expected_events':writer_events,'hard_constraints':case['facts']},'style_profile':style,'audit_verdict':{'findings':findings}}
  with bind_resources(snapshot):messages=prompts.patch_messages(state)
  messages[-1]['content']+='\n【前章现场证据】\n'+case['previous_tail']
  patches=checked(messages,parse_patches,stage='patch_'+str(revision+1),role='writer',thinking=False,tokens=3000,json_mode=False)
  patched=apply_patches(draft,patches)
  emit({'event':'patch','revision':revision+1,'applied':patched.applied,'reason':patched.rejected_reason,'spans':[{'target':p.target,'replacement':p.replacement} for p in patched.applied_spans]})
  if patched.applied:draft=patched.content
  else:
   with bind_resources(snapshot):messages=prompts.revise_messages(draft,findings,2,context=writer_context,plan=state['plan'],style_profile=style,target_words=650)
   draft=checked(messages,_check_draft,stage='full_revision_'+str(revision+1),role='writer',thinking=False,tokens=3200,json_mode=False)
  findings=inspect(draft,'after-'+str(revision+1))
 emit({'event':'final','passed':not findings,'unresolved':findings,'text':draft,'attempts':attempts})
except Exception as error:
 emit({'event':'pipeline_failed','error_type':type(error).__name__,'reason':str(error)[:400],'attempts':attempts,'text':draft})
 raise SystemExit(1)
