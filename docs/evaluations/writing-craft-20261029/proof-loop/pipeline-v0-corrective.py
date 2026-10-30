import os,base64,json,logging,re
logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json, _check_draft
from myink.workflow import prompts
from myink.workflow.patches import parse_patches,apply_patches
from chapter_checks import parse_contract, parse_observation
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
CAP=8
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
compiler='''你只分解章节计划的结果承诺，不读正文，不新增情节要求。把每项拆成可分别回答“正文是否发生/存在这个命题”的原子命题。每条命题最多一个具体人物作为主体、一个动作或状态，坐下与核对必须分为两条，不得将动作接在姿态状态后；person的subject必须严格等于participants中的一个名字；物件状态用object。共同动作须按已知人物分别拆开，不用“母女/两人/双方”掩盖某人遗漏。保留亲口、已完成、原路、指定主体等限定。用单一subject、subject_kind=person|object和不带主体的肯定式action，加expected="present|absent"表达正反要求，如subject=“申请”,subject_kind=object,action=“已签字”,expected=absent；不要把双重否定交给观察者。相同命题去重但链接所有来源。不增加必须直接写出所有给定背景的要求。每个links元素必须含event_index（从0开始）和该事件原文中逐字连续quote；全部事件的每个非空白语义字（逗号句号分号顿号无需覆盖）都须被links覆盖，一条命题可链接多个事件。不改原意、不省略限定；保留否定语义用expected=absent，如未签字应为action=已签字,expected=absent。“不是约定以后再看”意为本章实际看而不能以约定替代，不额外禁止角色在实际看之后约定未来再看。共同打开用每个人参与查看同一课表表达，不要求每个人都独立操作打开程序。只输出JSON：{"atoms":[{"subject":"人物姓名或物件","subject_kind":"person|object","action":"单一动作或状态","expected":"present|absent","links":[{"event_index":0,"quote":"原文连续片段"}]}]}。最多16条，无法无损分解时输出{"atoms":[],"error":"原因"}。'''
example_events=['赵启与徐明已经在门边蹲下检查锁，不是约好明天检查。','包裹尚未封口。']
example_atoms=[{'subject':name,'subject_kind':'person','action':action,'expected':'present','links':[{'event_index':0,'quote':example_events[0]}]} for name in ['赵启','徐明'] for action in ['已蹲在门边','参与当场检查锁']]
example_atoms.append({'subject':'包裹','subject_kind':'object','action':'已封口','expected':'absent','links':[{'event_index':1,'quote':example_events[1]}]})
contract=_parse_json(ask([{'role':'system','content':compiler},{'role':'user','content':json.dumps({'events':example_events,'participants':['赵启','徐明']},ensure_ascii=False)},{'role':'assistant','content':json.dumps({'atoms':example_atoms},ensure_ascii=False)},{'role':'user','content':json.dumps({'events':events,'context':context,'participants':participants},ensure_ascii=False)}],tokens=4000))
emit({'event':'contract_candidate','contract':contract})
try:
 claims=parse_contract(contract,events,participants=participants,max_claims=16)
except ValueError as exc:
 emit({'event':'contract_retry','reason':str(exc)})
 contract=_parse_json(ask([{'role':'system','content':compiler},{'role':'user','content':json.dumps({'events':events,'context':context,'participants':participants},ensure_ascii=False)},{'role':'assistant','content':json.dumps(contract,ensure_ascii=False)},{'role':'user','content':'逐项补齐遗漏来源，不删除已覆盖要求、不改变原意。连接词可由相邻命题的来源引文覆盖；缺失概念必须有独立校验。错误：'+str(exc)}],tokens=4000))
 emit({'event':'contract_corrected','contract':contract})
 claims=parse_contract(contract,events,participants=participants,max_claims=16)
atoms=[{'predicate':claim.predicate,'expected':claim.expected} for claim in claims]
emit({'event':'contract','atoms':atoms})
observer='''只回答给定的一个肯定命题是否在正文中发生/成立，不评价好坏，不给整个章节pass。observed=该命题在正文发生/存在；not_observed=正文未发生或给出相反状态；uncertain=确有歧义。逐字引文只能来自draft；context只帮助理解代词/历史，不能把计划和背景当成本章已发生事件。指定人的动作不能由另一个人的动作替代；不能从一人就坐推断所有人都就坐。不能把“有条路能出”当“沿自己来路返回”。正常的新动作可改变开场状态。输出JSON：{"observation":"observed|not_observed|uncertain","quotes":["draft中连续逐字引文"],"reason":"一句话","scope":"local|structural|unknown"}。observed必须有能支持此命题的正文引文；未发生可无引文。'''
observer+='先抽取证据，再判断其语义是否支持命题；不要求正文出现命题的原词。日常共享过程（一个人操作打开、另一个人同时查看）可以构成共同打开；姿态、关键权限等未交代的事实不能推断。只有明确反向或确实缺失才not_observed，无法确定用uncertain。'
def inspect(text,phase):
 raw=_parse_json(ask([{'role':'system','content':observer+'逐项独立回答checks中所有命题，不能把一项结果当作其他项结果。每个结果附原始index，返回JSON：{"checks":[{"index":0,"observation":"observed|not_observed|uncertain","quotes":[],"reason":"理由","scope":"local|structural|unknown"}]}。'}, {'role':'user','content':json.dumps({'checks':[{'index':0,'predicate':'孟秋核对支出'},{'index':1,'predicate':'林岚已经坐下'}],'draft':'孟秋在桌边坐下，沿收据一笔笔读金额，和账本上的数字对照。林岚站在她旁边，把漏记的一笔指给她。'},ensure_ascii=False)}, {'role':'assistant','content':json.dumps({'checks':[{'index':0,'quotes':['沿收据一笔笔读金额，和账本上的数字对照'],'reason':'把收据金额与账本逐项对照即是核对，不需出现核对原词','scope':'local','observation':'observed'},{'index':1,'quotes':['林岚站在她旁边'],'reason':'林岚是站姿，孟秋坐下不能代表林岚坐下','scope':'local','observation':'not_observed'}]},ensure_ascii=False)}, {'role':'user','content':json.dumps({'checks':[{'index':i,'predicate':a['predicate']} for i,a in enumerate(atoms)],'context':context,'draft':text},ensure_ascii=False)}],tokens=6000))
 results=raw['checks']
 assert len(results)==len(atoms) and {r['index'] for r in results}==set(range(len(atoms)))
 checks=[]
 for result in sorted(results,key=lambda r:r['index']):
  i=result.pop('index');a=atoms[i]
  parsed=parse_observation(result,text)
  passed=parsed.observation==('observed' if a['expected']=='present' else 'not_observed')
  checks.append({'index':i,'passed':passed,**parsed.model_dump(mode='json')})
  emit({'event':'check','phase':phase,'atom':i,'predicate':a['predicate'],'expected':a['expected'],**checks[-1]})
 return checks
def consistency(text,phase):
 instruction='检查两类具体矛盾，不评价文风。opening只比较正文前350字符所建立的初始现场与previous_tail/facts中确为开场已知的事实；本章必须实现的要求不是已发生事实，后续有交代的正常新动作允许改变状态。internal从全稿追踪明确设立的知识/权限/物品/位置/能力障碍：若后续依赖缺失条件完成动作却没有得到该条件的过程则报矛盾，例如声称没有钥匙后无交代直接用钥匙开门；不要因省略普通操作步骤误报。每类输出issue_found真实布尔值及issues列表；issue_found与列表非空一致。每项含before_quote,after_quote,reason,scope。opening的before_quote逐字来自previous_tail或facts任一项，after_quote逐字来自draft前350字符；internal两引文逐字来自draft。证据必须支持同一事实矛盾，不能把可能性当确定。返回JSON:{"opening":{"issue_found":false,"issues":[]},"internal":{"issue_found":false,"issues":[]}}。最多每类2项。'
 data=_parse_json(ask([{'role':'system','content':instruction},{'role':'user','content':json.dumps({**context,'draft':text},ensure_ascii=False)}],tokens=2200))
 assert set(data)=={'opening','internal'}
 findings=[]
 for category,row in data.items():
  assert type(row['issue_found']) is bool and isinstance(row['issues'],list) and row['issue_found']==bool(row['issues']) and len(row['issues'])<=2
  for index,issue in enumerate(row['issues']):
   before=issue['before_quote'];after=issue['after_quote']
   assert before.strip() and after.strip() and issue['reason'].strip() and issue['scope'] in ['local','structural','unknown']
   source=[context['previous_tail'],*context['facts']] if category=='opening' else [text]
   assert any(before in source_text for source_text in source) and after in (text[:350] if category=='opening' else text)
   findings.append({'conflict_key':category+'-'+str(index),'conflict_type':'plotline','severity':'major','scope':issue['scope'],'evidence':[{'chapter':2,'quote':after}],'suggestion':issue['reason']+'；保持原事实，通过最小修订消除矛盾。'})
 emit({'event':'consistency','phase':phase,'result':data})
 return findings
checks=inspect(draft,'before')
other_findings=consistency(draft,'before')
failed=[r for r in checks if not r['passed']]
if failed or other_findings:
 findings=[{'conflict_key':'proof-'+str(r['index']),'conflict_type':'plotline','severity':'major','scope':r.get('scope','unknown'),'evidence':[{'chapter':2,'quote':q} for q in r['quotes']], 'suggestion':'只局部修正，使本章实际满足：'+atoms[r['index']]['predicate']+'；期望为'+atoms[r['index']]['expected']+'。'+r['reason']} for r in failed]+other_findings
 raw=ask(prompts.patch_messages({'draft':draft,'chapter_seq':2,'plan':{'goals':[c['goal']],'expected_events':events,'hard_constraints':c['facts']},'audit_verdict':{'findings':findings},'style_profile':{}}),tokens=2400,temp=.3,json_mode=False)
 edited=apply_patches(draft,parse_patches(raw))
 emit({'event':'patch','applied':edited.applied,'reason':edited.rejected_reason,'spans':[{'target':s.target,'replacement':s.replacement} for s in edited.applied_spans]})
 if not edited.applied:
  draft=_check_draft(ask(prompts.revise_messages(draft,findings,2,plan={'goals':[c['goal']],'expected_events':events,'hard_constraints':c['facts']},target_words=650),tokens=3000,temp=.3,json_mode=False))
  emit({'event':'full_revision'})
 else: draft=edited.content
 checks=inspect(draft,'after')
 other_findings=consistency(draft,'after')
emit({'event':'final','passed':all(x['passed'] for x in checks) and not other_findings,'text':draft,'attempts':count})
