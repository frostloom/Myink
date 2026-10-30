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
CAP=6
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
contract=_parse_json(ask([{'role':'system','content':compiler},{'role':'user','content':json.dumps({'events':events,'context':context,'participants':participants},ensure_ascii=False)}],tokens=4000))
emit({'event':'contract_candidate','contract':contract})
claims=parse_contract(contract,events,participants=participants,max_claims=16)
atoms=[{'predicate':claim.predicate,'expected':claim.expected} for claim in claims]
emit({'event':'contract','atoms':atoms})
observer='''只回答给定的一个肯定命题是否在正文中发生/成立，不评价好坏，不给整个章节pass。observed=该命题在正文发生/存在；not_observed=正文未发生或给出相反状态；uncertain=确有歧义。逐字引文只能来自draft；context只帮助理解代词/历史，不能把计划和背景当成本章已发生事件。指定人的动作不能由另一个人的动作替代；不能从一人就坐推断所有人都就坐。不能把“有条路能出”当“沿自己来路返回”。正常的新动作可改变开场状态。输出JSON：{"observation":"observed|not_observed|uncertain","quotes":["draft中连续逐字引文"],"reason":"一句话","scope":"local|structural|unknown"}。observed必须有能支持此命题的正文引文；未发生可无引文。'''
def inspect(text,phase):
 raw=_parse_json(ask([{'role':'system','content':observer+'逐项独立回答checks中所有命题，不能把一项结果当作其他项结果。每个结果附原始index，返回JSON：{"checks":[{"index":0,"observation":"observed|not_observed|uncertain","quotes":[],"reason":"理由","scope":"local|structural|unknown"}]}。'}, {'role':'user','content':json.dumps({'checks':[{'index':i,'predicate':a['predicate']} for i,a in enumerate(atoms)],'context':context,'draft':text},ensure_ascii=False)}],tokens=6000))
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
checks=inspect(draft,'before')
failed=[r for r in checks if not r['passed']]
if failed:
 findings=[{'conflict_key':'proof-'+str(r['index']),'conflict_type':'plotline','severity':'major','scope':r.get('scope','unknown'),'evidence':[{'chapter':2,'quote':q} for q in r['quotes']], 'suggestion':'只局部修正，使本章实际满足：'+atoms[r['index']]['predicate']+'；期望为'+atoms[r['index']]['expected']+'。'+r['reason']} for r in failed]
 raw=ask(prompts.patch_messages({'draft':draft,'chapter_seq':2,'plan':{'goals':[c['goal']],'expected_events':events,'hard_constraints':c['facts']},'audit_verdict':{'findings':findings},'style_profile':{}}),tokens=2400,temp=.3,json_mode=False)
 edited=apply_patches(draft,parse_patches(raw))
 emit({'event':'patch','applied':edited.applied,'reason':edited.rejected_reason,'spans':[{'target':s.target,'replacement':s.replacement} for s in edited.applied_spans]})
 if not edited.applied:
  draft=_check_draft(ask(prompts.revise_messages(draft,findings,2,plan={'goals':[c['goal']],'expected_events':events,'hard_constraints':c['facts']},target_words=650),tokens=3000,temp=.3,json_mode=False))
  emit({'event':'full_revision'})
 else: draft=edited.content
 checks=inspect(draft,'after')
emit({'event':'final','passed':all(x['passed'] for x in checks),'text':draft,'attempts':count})
