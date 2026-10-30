"""Bounded synthetic research: source-only inventory, independent fact tables, repair/recheck."""
import base64, json, logging, os, re, sys
sys.path.insert(0, '/eval')
logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration, resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json, _check_draft
from myink.workflow import prompts
from myink.workflow.patches import apply_patches, parse_patches
from myink.seed import STYLE_PRESETS
from copy import deepcopy
from myink.db import new_session
from myink.writing_resources import catalog, capture_role_prompts
from myink.writing_resource_seed import builtin_resources
from myink.writing_resource_runtime import bind_resources
from chapter_checks import draft_segments, resolve_quote_id
from action_matrix import Action, parse_matrix, parse_source_matrix, compare_matrices

payload = json.loads(base64.b64decode(os.environ['MATRIX_PIPELINE']))
case = payload['case']; draft = payload['draft']; people = payload['participants']
events = list(case['expected_events'])
if case['must_end'] not in events: events.append(case['must_end'])
writer_events=list(events)
if case['goal'] not in events:events.append(case['goal'])
context = {'previous_tail': case['previous_tail'], 'facts': case['facts'], 'goal': case['goal']}
config = load_configuration(); connections = {}; providers = {}; attempts = 0; CAP = 12

def emit(value): print(json.dumps(value, ensure_ascii=False), flush=True)
def cap_request(request):
    global attempts
    if attempts >= CAP: raise RuntimeError('Twelve-request chapter cap reached')
    attempts += 1; emit({'event': 'attempt', 'attempt': attempts})
for role in ('audit', 'writer'):
    connections[role] = resolve_connection(role, {}, config, tier='normal')
    providers[role] = _chain_from_override(connections[role], False).providers[0]
    providers[role]._client.event_hooks['request'].append(cap_request)
    if role == 'audit':
        original_payload = providers[role]._payload
        def thinking_payload(*args, _original=original_payload, **kwargs):
            result = _original(*args, **kwargs)
            result['thinking'] = {'type': 'enabled', 'budget_tokens': 4096}
            result['output_config'] = {'effort': 'high'}
            result.pop('temperature', None)
            return result
        providers[role]._payload = thinking_payload
emit({'event': 'start', 'request_cap': CAP, 'models': {r: c['model'] for r,c in connections.items()}})

def ask(messages, *, stage, tokens=2400, role='audit', json_mode=True):
    response = providers[role].generate(messages, model_id=connections[role]['model'],
        max_tokens=max(tokens, 10000) if role=='audit' else tokens, temperature=0 if role=='audit' else .3,
        json_mode=json_mode, disable_thinking=role!='audit')
    emit({'event': 'usage', 'stage': stage, 'input_tokens': response.input_tokens,
          'output_tokens': response.output_tokens, 'truncated': response.finish_reason=='length',
          'provider_failed': bool(response.error)})
    if response.error or response.finish_reason=='length': raise RuntimeError('Provider failed or truncated')
    return response.content

def checked(messages, check, *, stage, tokens=5000):
    for attempt in range(2):
        text = ask(messages, stage=stage, tokens=tokens)
        data = _parse_json(text)
        emit({'event': 'candidate', 'stage': stage, 'data': data})
        try: return check(data)
        except ValueError as error:
            if attempt: raise
            messages = [*messages, {'role':'assistant','content':text},
                {'role':'system','content':'只纠正结构/来源错误，不按想要的结论改变事实。原文引用不得编造。具体错误：'+str(error)}]

def inventory_check(data):
    if not isinstance(data,dict) or set(data)!={'tables'} or not isinstance(data['tables'],list):
        raise ValueError('tables required')
    tables=[]; covered=set(); cells=0
    for raw in data['tables']:
        if set(raw)!={'event_index','kind','subject','members','source_quote','actions'}:
            raise ValueError('Inventory fields invalid')
        index=raw['event_index']
        if type(index) is not int or not 0<=index<len(events): raise ValueError('Unknown source event')
        if not isinstance(raw['source_quote'],str) or not raw['source_quote'].strip() or raw['source_quote'] not in events[index]:
            raise ValueError('Inventory quote must be literal source')
        kind=raw['kind']
        if kind=='person':
            subject=raw['subject'];members=raw['members']
            if (not isinstance(subject,str) or not subject.strip() or subject not in events[index]
                    or not isinstance(members,list) or not members or len(set(members))!=len(members)
                    or any(name not in people for name in members)):
                raise ValueError('Person table needs a literal subject phrase from this source and known member names; unbound event must use scene')
            named=[name for name in people if name in subject]
            if named:
                remainder=subject
                for name in sorted(named,key=len,reverse=True):remainder=remainder.replace(name,'')
                remainder=re.sub(r'以及|[\s、和与及或跟同]','',remainder)
                if remainder or set(members)!=set(named):raise ValueError('Named subject phrase and member list disagree')
            elif subject in {'母女','父女','母子','父子','父母','夫妻','姐妹','兄弟','两人','二人','双方','他们','她们','众人','所有人','二者','师徒'}:
                if len(members)<2 or subject in {'两人','二人','二者'} and len(members)!=2:
                    raise ValueError('Collective subject cannot be represented by only one person')
            elif len(members)!=1 or len(subject)>16 or subject in {'同时','记录','准确','决定','之后','再','先','然后','当前','本章','本段','指出'}:
                raise ValueError('Unbound verb/adverb is not an individual subject; use scene for an event-level requirement')
            actors=[name for name in people if name in members]
        elif kind=='object':
            subject=raw['subject']
            if not isinstance(subject,str) or not subject.strip() or subject not in '\n'.join([*events,*case['facts'],case['previous_tail']]):
                raise ValueError('Object name must be literal source')
            actors=[subject]
        elif kind=='scene': actors=['叙述整体']
        else: raise ValueError('Unknown inventory kind')
        if not isinstance(raw['actions'],list) or not 1<=len(raw['actions'])<=10: raise ValueError('Invalid action inventory')
        actions=[Action.model_validate(action) for action in raw['actions']]
        negative=[a.text for a in actions if re.match(r'^(?:不|未|无|没有|不能|不会)',a.text)]
        if negative:raise ValueError('Question polarity invalid: '+repr(negative)+'。只改内部问题，不改原计划：不跨裂缝应问跨裂缝；没有无过程会合应问发生无过程会合；是否禁止由来源布尔表判断。保留其他全部已合格问题和来源。')
        if kind=='person' and any(re.search('来路|原路|来时',a.text) and re.search('返|回|退',a.text) for a in actions):
            identity=Action(text='明确选择沿自己来时走过的那条路线返回',temporal_scope='occurrence')
            if identity not in actions:actions.append(identity)
        if len({(a.text,a.temporal_scope) for a in actions})!=len(actions):raise ValueError('Duplicate action inventory')
        cells+=len(actors)*len(actions)
        tables.append({'event_index':index,'actors':actors,'actions':actions,'source_quote':raw['source_quote']})
        covered.add(index)
    if covered!=set(range(len(events))) or not 1<=len(tables)<=24 or cells>96:
        raise ValueError('Incomplete source-event inventory or over limit; do not drop requirements')
    return tables

inventory_prompt='''只从完整计划和上下文建立事实问题清单，不读正文，不判断草稿是否通过。每个events原项必须覆盖，保留全部动作、主体、数量、否定范围、先后、同刻、所有权/路线同一性限定。问题写成单个肯定事实，不把多个独立事实合成一个问题；动作、位置、结束状态分开。共享活动不等于每人各自独立操作。只有原项明确指定人物或人物集合的动作才用kind=person，subject必须逐字引用本项中的人名/代词/亲属称呼或集合短语，members列确切已知人物；不能用空主语、副词或动词当人物。集合主体至少两人，别漏掉第二个人。原项只约定有某个事件/结果发生、没绑定谁执行时用kind=scene，不能把事件级任务强加给所有出场人物；物件状态kind=object且subject逐字来自来源，members=[]；全章禁止/存在性或未绑定执行人的事件kind=scene，subject为空且members=[]。只要某事发生即可，不得把未指定人的事件变成每个人都必须做。保留决定/约定与实际完成的区别；原文只要求决定或约定时，问题必须包含决定/约定，不能要求已实现；原文要求实际完成时不能用计划代替。正常语境表达与同义动作可以证明，不增加必须出现验收原词的要求。同一路径/自己来路须问返回路线与进入路线是否为同一路线，不能只问有路可出；同刻/先后必须保留在相关问题中。temporal_scope=occurrence问章内发生过，end_state仅用于明确结尾仍成立，不把已完成动作要求永远持续。text只写动作/状态（不带主体），且为肯定式；禁止/缺失由稍后来源表判为forbidden，不把负问句交给正文阅读者。相同含义可合并，但不可遗漏义务。返回JSON:{"tables":[{"event_index":0,"kind":"person|object|scene","subject":"person为本项字面主语短语/object物件名/scene空串","members":["person主体对应的已知人名，其他类型空数组"],"source_quote":"对应事件逐字连续片段","actions":[{"text":"单个肯定事实问题","temporal_scope":"occurrence|end_state"}]}]}。最多24表、96个人物动作格子，不能截断。'''
tables = checked([{'role':'system','content':inventory_prompt}, {'role':'user','content':json.dumps({'events':events,'people':people,'context':context},ensure_ascii=False)}], inventory_check, stage='inventory', tokens=5000)

TABLE_INSTRUCTION='''逐表、逐人、逐动作填完整格子。每个表的actors×actions每格都要独立回答，不能跳格，不能以一人的动作代替另一人。多人共享查看/操作过程不要求每个人独自完成全部操作。允许自然同义表达、代词和语境中明确的省略；不能凭剧情合理就补上没有依据的坐姿、权限获得或路线同一性。叙述整体作为主体时回答整篇是否存在该事实。occurrence问本章是否发生过；end_state问结尾仍成立，曾满足但后来撤销不能当作结尾满足。证据只能选segments中的编号，服务端取原文，不生成引文。required/forbidden/observed必须给有效证据编号。reason一句简短依据。返回JSON:{"tables":[{"table_id":0,"cells":[{"actor_id":0,"action_id":0,"status":"状态","evidence_ids":[0],"reason":"依据"}]}]}。每个table_id必须有且仅有一份，所有格子完整。'''

SOURCE_INSTRUCTION='逐表逐人逐动作核对原要求，不看正文。actors若为“叙述整体”表示该事件在本章是否必须发生，不是一个真实人物，不把全局事件强派到每个出场人物。每个actors×actions格子都填，先选原文证据并写简短理由，再回答四个布尔事实：required_individually=原文明确要求此人实现此事实（含明确的集体人人动作）；required_as_one_of=原文只要求相关候选人至少一人实现此事实，此人是候选者，而非每个人重复；must_be_absent=原文明示禁止此人实现此事实，或明确状态要求本事实为假；uncertain=原文确实无法判定。四者最多一个true；明确未要求也未禁止时全部false。没有要求不等于必须没有：甲记录乙照明，并不禁止乙帮忙记录。只有明确限定“只许/不得/不能/不具备”等时才判排除，不能从职责分工推测禁止。共享活动中的参与不要求每人独立操作全过程；亲自坐下等个体状态不能由别人替代。scope=occurrence表示发生过，end_state表示结尾仍成立。证据编号来自segments，每个非空要求必须有证据。返回JSON:{"tables":[{"table_id":0,"cells":[{"actor_id":0,"action_id":0,"evidence_ids":[0],"reason":"原文依据","required_individually":false,"required_as_one_of":false,"must_be_absent":false,"uncertain":false}]}]}。不用status字段，全部字段必须显式给出，编号必须整数，不增不漏所有表和格子。'

def table_wire(items):
    return [{'table_id':i,'actors':t['actors'],'actions':[a.model_dump() for a in t['actions']]} for i,t in enumerate(items)]

def read_tables(items, segments, mode, *, stage, extra=None):
    def parse(data):
        if not isinstance(data,dict) or set(data)!={'tables'} or not isinstance(data['tables'],list): raise ValueError('Table batch required')
        rows=data['tables']
        if len(rows)!=len(items) or any(type(r.get('table_id')) is not int for r in rows) or {r['table_id'] for r in rows}!=set(range(len(items))):
            raise ValueError('Table IDs incomplete or duplicate')
        result={}
        for row in rows:
            if set(row)!={'table_id','cells'}:raise ValueError('Unexpected table fields')
            i=row['table_id'];t=items[i]
            result[i]=(parse_source_matrix({'cells':row['cells']},actors=t['actors'],actions=t['actions'],segments=segments) if mode=='requirements' else parse_matrix({'cells':row['cells']},actors=t['actors'],actions=t['actions'],segments=segments,mode=mode))
        return result
    instruction=SOURCE_INSTRUCTION if mode=='requirements' else TABLE_INSTRUCTION+'只读正文，不读计划、目标、希望满足的结果。status=observed|not_observed|uncertain。记录文中事实，不为作者补完。认知、发现、判断、指出可以由明确跟随人物的叙述交代，不强迫人物复读验收句；只有明确要求亲口说出/对白时才限为台词。'
    content={'tables':table_wire(items),'segments':[{'id':i,'text':s} for i,s in enumerate(segments)]}
    if extra:content.update(extra)
    return checked([{'role':'system','content':instruction},{'role':'user','content':json.dumps(content,ensure_ascii=False)}],parse,stage=stage,tokens=8000)

required=read_tables(tables,events,'requirements',stage='source_matrix',extra={'context':context})
for matrix in required.values():
    if not any(c.status in {'required','one_of','forbidden','uncertain'} for c in matrix.cells):raise ValueError('Source table contains no obligations')

PREMISE_PROMPT='''只识别给定negative段落中人物明确缺少的知识、资源、权限、能力；每个negative_id必须返回一项。你只看该段及前一段以解析说话人，不看之后剧情，不判断矛盾。普通“没说话/没问/不愿/尚未做某动作”和不许做的规范不等于缺少能力，conditions=[]并解释。真正缺少时返回actor（people中的确切名字）、condition（保留具体限定的肯定资源/能力名）、quote（该negative段或前一段的逐字片段，服务端按引文绑定真实段号）。例：缺少修改文件权限，不等于缺少读取文件权限；不能省略修改限定。不要因为可能撒谎就丢掉缺失声明，谎话会由另一步核实。返回JSON:{"entries":[{"negative_id":0,"conditions":[{"actor":"名字","condition":"肯定资源或能力","quote":"逐字片段"}],"reason":"分类依据"}]}。每段最多2个条件。'''

def premise_inventory(text):
    segments=draft_segments(text)
    negative=[i for i,s in enumerate(segments) if re.search('没有|不能|无法|没|不知|不会|不够|未',s)]
    if not negative:return []
    def check(data):
        if not isinstance(data,dict) or set(data)!={'entries'}:raise ValueError('Premise entries required')
        rows=data['entries']
        if not isinstance(rows,list) or len(rows)!=len(negative) or any(type(r.get('negative_id')) is not int for r in rows) or {r['negative_id'] for r in rows}!=set(negative):raise ValueError('Premise coverage incomplete: expected '+str(negative)+' got '+str([r.get('negative_id') for r in rows]))
        result=[]
        for row in rows:
            index=row['negative_id']
            if set(row)!={'negative_id','conditions','reason'} or not isinstance(row['conditions'],list) or len(row['conditions'])>2:raise ValueError('Premise fields invalid')
            for condition in row['conditions']:
                if set(condition)!={'actor','condition','quote'} or condition['actor'] not in people or not condition['condition'].strip() or not condition['quote'].strip() :raise ValueError('Ungrounded premise fields at paragraph '+str(index))
                origin=resolve_quote_id(condition['quote'],segments,[j for j in [index-1,index] if j>=0])
                resource=condition['condition'];actor=condition['actor']
                questions=[f'在第{origin}段明确表示缺少：{resource}',f'在第{origin}段的缺失声明之后实际依赖或使用：{resource}',f'在第{origin}段的缺失声明之后、使用之前正文明确交代获得或恢复：{resource}',f'正文明确说明第{origin}段的缺失声明是撒谎、误解或玩笑']
                result.append({'actors':[actor],'actions':[Action(text=q,temporal_scope='occurrence') for q in questions],'negative_id':origin,'condition':resource})
        if sum(len(t['actions']) for t in result)>40:raise ValueError('Premise inventory over limit')
        return result
    content={'people':people,'negative':[{'negative_id':i,'text':segments[i],'previous':segments[i-1] if i else ''} for i in negative]}
    return checked([{'role':'system','content':PREMISE_PROMPT},{'role':'user','content':json.dumps(content,ensure_ascii=False)}],check,stage='premise_inventory',tokens=3500)


def inspect(text, phase):
    premises=premise_inventory(text);all_tables=[*tables,*premises]
    actual=read_tables(all_tables,draft_segments(text),'observations',stage='body_matrix_'+phase)
    findings=[]
    for i,t in enumerate(tables):
        result=compare_matrices(required[i],actual[i])
        emit({'event':'comparison','phase':phase,'table_id':i,'failed':result.failed,'uncertain':result.uncertain,'failed_groups':result.failed_groups,'uncertain_groups':result.uncertain_groups})
        actual_by={(c.actor_id,c.action_id):c for c in actual[i].cells}
        source_by={(c.actor_id,c.action_id):c for c in required[i].cells}
        for actor_id,action_id in (*result.failed,*result.uncertain):
            cell=actual_by[(actor_id,action_id)];source=source_by[(actor_id,action_id)]
            target=t['actors'][actor_id]+t['actions'][action_id].text
            findings.append({'conflict_key':f'matrix-{i}-{actor_id}-{action_id}','conflict_type':'plotline','severity':'major','scope':'local','evidence':[{'chapter':2,'quote':actual[i].segments[index]} for index in cell.evidence_ids], 'suggestion':f'按原计划的{source.status}要求检查并最小修正：{target}。原要求：{events[t["event_index"]]}。正文依据：{cell.reason}。不要把含蓄表达一律改成直白说明，不添加计划外事实。'})
        for group in (*result.failed_groups,*result.uncertain_groups):
            action_id=group[0][1];names='、'.join(t['actors'][actor_id] for actor_id,_ in group)
            evidence=[{'chapter':2,'quote':actual[i].segments[index]} for pair in group for index in actual_by[pair].evidence_ids]
            findings.append({'conflict_key':f'matrix-any-{i}-{action_id}','conflict_type':'plotline','severity':'major','scope':'local','evidence':evidence,'suggestion':f'原要求只需至少一名相关参与者完成，不要每人重复：{names}之中至少一人{t["actions"][action_id].text}。原要求：{events[t["event_index"]]}。保留原文有效的叙述认知与潜台词，只补真正未实现的条件。'})
    for offset,t in enumerate(premises,start=len(tables)):
        cells=actual[offset].cells;states={c.action_id:c.status for c in cells}
        if states[0]!='observed':raise ValueError('Premise inventory not substantiated in independent reading')
        uncertain=any(value=='uncertain' for value in states.values())
        conflict=states[1]=='observed' and states[2]!='observed' and states[3]!='observed'
        emit({'event':'premise_comparison','phase':phase,'actor':t['actors'][0],'condition':t['condition'],'states':states,'conflict':conflict,'uncertain':uncertain})
        if conflict or uncertain:
            findings.append({'conflict_key':'premise-'+str(t['negative_id']),'conflict_type':'plotline','severity':'major','scope':'local','evidence':[{'chapter':2,'quote':actual[offset].segments[index]} for c in cells for index in c.evidence_ids], 'suggestion':'角色缺少的前提没有得到/恢复过程，却完成依赖它的动作，或前提状态有歧义：'+t['actors'][0]+'，'+t['condition']+'。保持原计划和台账事实。若缺失声明只是本稿误加的限制，优先修正这句声明，使它和已存在的后续动作一致；若来源明确规定缺失，则调整依赖它的后续动作，不能篡改原事实。不得通过临时找到新凭证、隐藏物品或新能力救场。只改最小必要片段。'})
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
findings=inspect(draft,'before')
for revision in range(2):
    if not findings:break
    state={'draft':draft,'chapter_seq':2,'plan':{'goals':[case['goal']],'expected_events':writer_events,'hard_constraints':case['facts']},'style_profile':style,'audit_verdict':{'findings':findings}}
    with bind_resources(snapshot):
        messages=prompts.patch_messages(state)
    messages[-1]['content']+='\n【前章现场证据】\n'+case['previous_tail']
    text='\n'.join(m.get('content','') for m in messages)
    if any(item not in text for item in [*events,*case['facts'],case['goal'],case['previous_tail']]):raise ValueError('Writer lost source constraints')
    raw=ask(messages,stage='patch',tokens=3000,role='writer',json_mode=False)
    patched=apply_patches(draft,parse_patches(raw))
    emit({'event':'patch','revision':revision+1,'applied':patched.applied,'reason':patched.rejected_reason,'spans':[{'target':p.target,'replacement':p.replacement} for p in patched.applied_spans]})
    if patched.applied:draft=patched.content
    else:
        with bind_resources(snapshot):
            messages=prompts.revise_messages(draft,findings,2,context=writer_context,plan=state['plan'],style_profile=style,target_words=650)
        draft=_check_draft(ask(messages,stage='full_revision',tokens=3200,role='writer',json_mode=False))
    findings=inspect(draft,'after-'+str(revision+1))
emit({'event':'final','passed':not findings,'unresolved':findings,'text':draft,'attempts':attempts})
