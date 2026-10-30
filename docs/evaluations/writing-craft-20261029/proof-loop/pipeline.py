import os,base64,json,logging,re
logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json, _check_draft
from myink.workflow import prompts
from myink.workflow.patches import parse_patches,apply_patches
from myink.seed import STYLE_PRESETS
from chapter_checks import parse_contract, parse_observations, parse_consistency, parse_fidelity, draft_segments, parse_indexed_observations
p=json.loads(base64.b64decode(os.environ['PROOF_PIPELINE']))
c=p['case'];draft=p['draft'];events=list(c.get('expected_events',[]))
if c['must_end'] not in events:events.append(c['must_end'])
config=load_configuration()
conn=resolve_connection('audit',{},config,tier='normal')
if p.get('alternate'):
 candidates=[r for r in config['connections'].values() if r.get('enabled') and r.get('model')!=conn['model']]
 assert len(candidates)==1
 conn=candidates[0]
provider=_chain_from_override(conn,False).providers[0]
print(json.dumps({'event':'model','model':conn['model']}),flush=True)
count=0
CAP=10
def emit(d):print(json.dumps(d,ensure_ascii=False),flush=True)
def cap(req):
 global count
 if count>=CAP:raise RuntimeError('Proof pipeline HTTP cap reached')
 count+=1;emit({'event':'attempt','attempt':count})
provider._client.event_hooks['request'].append(cap)
def ask(messages,tokens=1800,temp=0,json_mode=True):
 r=provider.generate(messages,model_id=conn['model'],max_tokens=tokens,temperature=temp,json_mode=json_mode,disable_thinking=True)
 if r.error or r.finish_reason=='length':raise RuntimeError('Provider failure/truncation')
 emit({'event':'usage','input_tokens':r.input_tokens,'output_tokens':r.output_tokens})
 return r.content
context={'previous_tail':c['previous_tail'],'facts':c['facts']}
participants=p['participants']
style=next((r['style_profile'] for r in STYLE_PRESETS if r['id']==c['style']),{})
compiler='''你只分解章节计划的结果承诺，不读正文，不新增情节要求。把每项拆成可分别回答“正文是否发生/存在这个命题”的原子命题。每条命题最多一个具体人物作为主体、一个动作或状态，坐下与核对必须分为两条，不得将动作接在姿态状态后；person的subject必须严格等于participants中的一个名字；物件状态用object。共同动作须按已知人物分别拆开，不用“母女/两人/双方”掩盖某人遗漏。保留亲口、已完成、原路、指定主体等限定。用单一subject、subject_kind=person|object和不带主体的肯定式action，加expected="present|absent"表达正反要求，如subject=“申请”,subject_kind=object,action=“已签字”,expected=absent；不要把双重否定交给观察者。相同命题去重但链接所有来源。拆分时须把同刻、先后、仅一次、同一路线等共享限定保留到相关命题的action中，不可因分拆而丢失关系。不增加必须直接写出所有给定背景的要求。每个links元素必须含event_index（从0开始）和该事件原文中逐字连续quote；全部事件的每个非空白语义字（逗号句号分号顿号无需覆盖）都须被links覆盖，一条命题可链接多个事件。每条必须标注temporal_scope=occurrence（本章发生过）或end_state（结尾仍成立）。仅明确持续/仍保持的约束为end_state，不因章内已完成要求出现在must_end来源中就要求最后一句还在进行。不改原意、不省略限定；保留否定语义用expected=absent，如未签字应为action=已签字,expected=absent。“不是约定以后再看”意为本章实际看而不能以约定替代，不额外禁止角色在实际看之后约定未来再看。共同打开用每个人参与查看同一课表表达，不要求每个人都独立操作打开程序。只输出JSON：{"atoms":[{"subject":"人物姓名或物件","subject_kind":"person|object","action":"单一动作或状态","temporal_scope":"occurrence|end_state","expected":"present|absent","links":[{"event_index":0,"quote":"原文连续片段"}]}]}。最多24条，无法无损分解时输出{"atoms":[],"error":"原因"}。'''
example_events=['赵启与徐明已经在门边蹲下检查锁，不是约好明天检查。','包裹尚未封口。']
example_atoms=[{'subject':name,'subject_kind':'person','action':action,'temporal_scope':'occurrence','expected':'present','links':[{'event_index':0,'quote':example_events[0]}]} for name in ['赵启','徐明'] for action in ['已蹲在门边','参与当场检查锁']]
example_atoms.append({'subject':'包裹','subject_kind':'object','action':'已封口','temporal_scope':'end_state','expected':'absent','links':[{'event_index':1,'quote':example_events[1]}]})
contract=_parse_json(ask([{'role':'system','content':compiler},{'role':'user','content':json.dumps({'events':example_events,'participants':['赵启','徐明']},ensure_ascii=False)},{'role':'assistant','content':json.dumps({'atoms':example_atoms},ensure_ascii=False)},{'role':'user','content':json.dumps({'events':events,'context':context,'participants':participants},ensure_ascii=False)}],tokens=4000))
emit({'event':'contract_candidate','contract':contract})
try:
 claims=parse_contract(contract,events,participants=participants,max_claims=24)
except ValueError as exc:
 emit({'event':'contract_retry','reason':str(exc)})
 contract=_parse_json(ask([{'role':'system','content':compiler},{'role':'user','content':json.dumps({'events':events,'context':context,'participants':participants},ensure_ascii=False)},{'role':'assistant','content':json.dumps(contract,ensure_ascii=False)},{'role':'user','content':'逐项补齐遗漏来源，不删除已覆盖要求、不改变原意。连接词可由相邻命题的来源引文覆盖；缺失概念必须有独立校验。错误：'+str(exc)}],tokens=4000))
 emit({'event':'contract_corrected','contract':contract})
 claims=parse_contract(contract,events,participants=participants,max_claims=24)
atoms=[{'predicate':claim.predicate,'expected':claim.expected,'temporal_scope':claim.temporal_scope} for claim in claims]
emit({'event':'contract','atoms':atoms})
fidelity=_parse_json(ask([{'role':'system','content':'你独立核对计划与拆分命题全体合取的语义是否等价，不读正文。核对的是所有命题连同共享来源限定合起来的意思，不要求每个单条复述整个原事件。未签字等价于已签字expected=absent；对两个人分别核对坐姿等价于两个人都坐着，不表示两次独立活动；分别核对同次观测的各个读数不表示分开测量。禁止仅因原事件被拆成多条、或否定状态用absent表示，就说语义改变。必须指出真正缺失的限定或确切新增的义务。对每个原事件按event_index判断：原有全部主体、动作、数量、先后/因果、否定范围、持续到结尾的限定是否都保留；不能增加新要求，不能把联合过程误拆成每人独立操作。看过不等于记录过，曾发生不等于结尾仍成立。引文覆盖不代表语义完整。一条拆分缺失/强化/弱化原意即unfaithful；有歧义uncertain；全部等价才faithful。返回JSON:{"checks":[{"event_index":0,"status":"faithful|unfaithful|uncertain","source_quotes":["该事件原句"],"reason":"具体逐项核对依据"}]}。每个原事件都必须有一项，不可缺漏。'}, {'role':'user','content':json.dumps({'events':events,'context':context,'participants':participants,'claims':[claim.model_dump(mode='json') for claim in claims]},ensure_ascii=False)}],tokens=2400))
review=parse_fidelity(fidelity,events)
emit({'event':'fidelity','result':review.model_dump(mode='json')})
if not review.passed:raise RuntimeError('Source meaning is not independently confirmed; hold for review')

observer='''只回答给定的一个肯定命题是否在正文中发生/成立，不评价好坏，不给整个章节pass。observed=该命题在正文发生/存在；not_observed=正文未发生或给出相反状态；uncertain=确有歧义。证据只能选择draft_segments中的编号，由服务端取原文；context只帮助理解代词/历史，不能把计划和背景当成本章已发生事件。指定人的动作不能由另一个人的动作替代；不能从一人就坐推断所有人都就坐。不能把“有条路能出”当“沿自己来路返回”。正常的新动作可改变开场状态。输出JSON：{"observation":"observed|not_observed|uncertain","evidence_ids":[0],"reason":"一句话","scope":"local|structural|unknown"}。observed必须有能支持此命题的正文证据编号；未发生可无引文。'''
observer+='source_events只解释命题的原始限定条件，不能当已发生证据；观察时保留同刻、先后、次数等共享条件。temporal_scope=occurrence问本章是否发生过，end_state问结尾还是否成立，曾满足但后来撤销不能算end_state成立。先抽取证据，再判断其语义是否支持命题；不要求正文出现命题的原词。日常共享过程（一个人操作打开、另一个人同时查看）可以构成共同打开；姿态、关键权限等未交代的事实不能推断。只有明确反向或确实缺失才not_observed，无法确定用uncertain。'
def validated(messages,parser,tokens):
 for attempt in range(2):
  raw_text=ask(messages,tokens=tokens)
  data=_parse_json(raw_text)
  emit({'event':'protocol_candidate','attempt':attempt+1,'data':data})
  try:return parser(data)
  except ValueError as exc:
   if attempt:raise
   messages=[*messages,{'role':'assistant','content':raw_text},{'role':'system','content':'只修正协议错误，不按预期结论修改判定；引文必须逐字复制，不可拼接或改字。找不到支持证据请保留不确定或未观察到，不得编造。校验错误：'+str(exc)}]
def inspect(text,phase):
 parsed_results=validated([{'role':'system','content':observer+'逐项独立回答checks中所有命题，不能把一项结果当作其他项结果。每个结果附原始index，返回JSON：{"checks":[{"index":0,"observation":"observed|not_observed|uncertain","evidence_ids":[],"reason":"理由","scope":"local|structural|unknown"}]}。'}, {'role':'user','content':json.dumps({'checks':[{'index':0,'predicate':'孟秋核对支出'},{'index':1,'predicate':'林岚已经坐下'}],'draft_segments':[{'id':0,'text':'孟秋在桌边坐下，沿收据一笔笔读金额，和账本上的数字对照。'},{'id':1,'text':'林岚站在她旁边，把漏记的一笔指给她。'}]},ensure_ascii=False)}, {'role':'assistant','content':json.dumps({'checks':[{'index':0,'evidence_ids':[0],'reason':'把收据金额与账本逐项对照即是核对，不需出现核对原词','scope':'local','observation':'observed'},{'index':1,'evidence_ids':[1],'reason':'林岚是站姿，孟秋坐下不能代表林岚坐下','scope':'local','observation':'not_observed'}]},ensure_ascii=False)}, {'role':'user','content':json.dumps({'checks':[{'index':i,'predicate':a['predicate'],'temporal_scope':a['temporal_scope'],'source_events':[events[link.event_index] for link in claims[i].links]} for i,a in enumerate(atoms)],'context':context,'draft_segments':[{'id':j,'text':segment} for j,segment in enumerate(draft_segments(text))]},ensure_ascii=False)}],lambda raw:parse_indexed_observations(raw,claims,text),6000)
 checks=[]
 for i,claim in enumerate(claims):
  a=atoms[i];parsed=parsed_results[claim.key]
  passed=parsed.observation==('observed' if a['expected']=='present' else 'not_observed')
  checks.append({'index':i,'passed':passed,**parsed.model_dump(mode='json')})
  emit({'event':'check','phase':phase,'atom':i,**a,**checks[-1]})
 observed=[r for r in checks if r['observation']=='observed']
 if observed:
  support=_parse_json(ask([{'role':'system','content':'你只做证据蕴含检查，不读计划、背景或整稿，不能借任务要求补写事实。逐项判断quotes本身是否足以证明predicate的全部限定。supported=引文直接说明或由引文必然推出；unsupported=尚缺关键事实，不能仅凭合理猜测；uncertain=有歧义。比如“他选择西边的路离开”能证明选了出口，但不能证明那是他进来时走的同一条路；只写甲坐下不能证明乙也坐下。日常动作的同义表达可以支持，不要求命题原词。返回JSON:{"checks":[{"index":0,"status":"supported|unsupported|uncertain","reason":"简短说明缺什么或如何推出"}]}，逐项覆盖给定index，不增不漏。'}, {'role':'user','content':json.dumps({'checks':[{'index':r['index'],'predicate':atoms[r['index']]['predicate'],'temporal_scope':atoms[r['index']]['temporal_scope'],'quotes':r['quotes']} for r in observed]},ensure_ascii=False)}],tokens=2200))
  rows=support.get('checks',[])
  if len(rows)!=len(observed) or any(type(r.get('index')) is not int for r in rows) or {r['index'] for r in rows}!={r['index'] for r in observed}:raise ValueError('Incomplete evidence support check')
  for r in rows:
   if r['status'] not in ['supported','unsupported','uncertain'] or not r['reason'].strip():raise ValueError('Invalid evidence support verdict')
   if r['status']!='supported':
    row=checks[r['index']];row.update({'passed':False,'observation':'uncertain' if r['status']=='uncertain' else 'not_observed','reason':r['reason']})
  emit({'event':'support','phase':phase,'result':support})
 if any(r['observation']=='uncertain' for r in checks):raise RuntimeError('Ambiguous factual check; hold without rewriting')
 return checks
def consistency(text,phase):
 findings=[]
 segments=draft_segments(text)
 negative=[i for i,part in enumerate(segments) if re.search('没有|不能|无法|没|不知|不会|不够|未',part)]
 if True:
  ledger=_parse_json(ask([{'role':'system','content':'同时返回opening开场冲突和premises前提表。opening只比较draft前350字符的初始现场与previous_tail/facts中已发生的开场事实，正常后续动作允许变化；返回{issue_found:真实布尔值,issues:[{before_quote:来源原句,after_quote:前350字符原句,reason:原因,scope:local|structural|unknown}]}，无确定冲突时false和空列表。再逐项追踪negative_ids段落中人物明说缺失的行动条件（知识、权限、口令、资源、能力、位置）。不要笼统审稿。每个编号必须回答：relevance=relevant表示确有行动条件缺失；irrelevant表示只是普通否定或对话意图；uncertain表示有歧义。relevant须说明condition，列出后来依赖此条件而完成动作的use_ids，以及正文明确交代获得/恢复条件的resolution_ids。只允许使用正文编号，不能用角色猜测或剧情要求作获得条件的证据；没有就空列表。声称没有必要凭证后，直接输入凭证完成操作属于有use而无resolution，不可假设省略获得过程。返回JSON:{"opening":{"issue_found":false,"issues":[]},"premises":[{"draft_id":0,"relevance":"relevant|irrelevant|uncertain","condition":"条件或不相关理由","use_ids":[],"resolution_ids":[]}]}，不增不漏所有negative_ids。'}, {'role':'user','content':json.dumps({**context,'negative_ids':negative,'draft_segments':[{'id':i,'text':part} for i,part in enumerate(segments)]},ensure_ascii=False)}],tokens=2200))
  report=parse_consistency({'opening':ledger['opening'],'internal':{'issue_found':False,'issues':[]}},text,[context['previous_tail'],*context['facts']])
  for index,issue in enumerate(report.opening.issues):
   findings.append({'conflict_key':'opening-'+str(index),'conflict_type':'plotline','severity':'major','scope':issue.scope,'evidence':[{'chapter':2,'quote':issue.after_quote}],'suggestion':issue.reason})
  rows=ledger.get('premises',[])
  if len(rows)!=len(negative) or any(type(r.get('draft_id')) is not int for r in rows) or {r['draft_id'] for r in rows}!=set(negative):raise ValueError('Incomplete premise ledger')
  for r in rows:
   if r['relevance'] not in ['relevant','irrelevant','uncertain'] or not r['condition'].strip():raise ValueError('Invalid premise classification')
   for key in ['use_ids','resolution_ids']:
    if not isinstance(r[key],list) or any(type(i) is not int or not r['draft_id']<i<len(segments) for i in r[key]):raise ValueError('Invalid premise evidence index')
   if r['relevance']=='uncertain':raise RuntimeError('Uncertain premise; hold without rewriting')
   if r['relevance']=='relevant' and r['use_ids'] and not any(i<min(r['use_ids']) for i in r['resolution_ids']):
    findings.append({'conflict_key':'premise-'+str(r['draft_id']),'conflict_type':'plotline','severity':'major','scope':'local','evidence':[{'chapter':2,'quote':segments[i]} for i in [r['draft_id'],*r['use_ids']]],'suggestion':'角色明确缺失的条件没有获得过程，却完成依赖它的动作：'+r['condition']+'。保持人物既有知识与权限，局部修复前提或动作。'})
  emit({'event':'premises','phase':phase,'result':ledger})
 return findings
checks=inspect(draft,'before')
other_findings=consistency(draft,'before')
failed=[r for r in checks if not r['passed']]
if failed or other_findings:
 findings=[{'conflict_key':'proof-'+str(r['index']),'conflict_type':'plotline','severity':'major','scope':r.get('scope','unknown'),'evidence':[{'chapter':2,'quote':q} for q in r['quotes']], 'suggestion':'只局部修正，使本章实际满足：'+atoms[r['index']]['predicate']+'；期望为'+atoms[r['index']]['expected']+'。'+r['reason']} for r in failed]+other_findings
 raw=ask(prompts.patch_messages({'draft':draft,'chapter_seq':2,'plan':{'goals':[c['goal']],'expected_events':events,'hard_constraints':c['facts']},'audit_verdict':{'findings':findings},'style_profile':style}),tokens=2400,temp=.3,json_mode=False)
 edited=apply_patches(draft,parse_patches(raw))
 emit({'event':'patch','applied':edited.applied,'reason':edited.rejected_reason,'spans':[{'target':s.target,'replacement':s.replacement} for s in edited.applied_spans]})
 if not edited.applied:
  draft=_check_draft(ask(prompts.revise_messages(draft,findings,2,plan={'goals':[c['goal']],'expected_events':events,'hard_constraints':c['facts']},target_words=650,style_profile=style),tokens=3000,temp=.3,json_mode=False))
  emit({'event':'full_revision'})
 else: draft=edited.content
 checks=inspect(draft,'after')
 other_findings=consistency(draft,'after')
emit({'event':'final','passed':all(x['passed'] for x in checks) and not other_findings,'text':draft,'attempts':count})
