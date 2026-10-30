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
from chapter_checks import draft_segments
from action_matrix import Action, parse_matrix, compare_matrices

payload = json.loads(base64.b64decode(os.environ['MATRIX_PIPELINE']))
case = payload['case']; draft = payload['draft']; people = payload['participants']
events = list(case['expected_events'])
if case['must_end'] not in events: events.append(case['must_end'])
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
emit({'event': 'start', 'request_cap': CAP, 'models': {r: c['model'] for r,c in connections.items()}})

def ask(messages, *, stage, tokens=2400, role='audit', json_mode=True):
    response = providers[role].generate(messages, model_id=connections[role]['model'],
        max_tokens=tokens, temperature=0 if role=='audit' else .3,
        json_mode=json_mode, disable_thinking=True)
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
        if set(raw)!={'event_index','kind','subject','source_quote','actions'}:
            raise ValueError('Inventory fields invalid')
        index=raw['event_index']
        if type(index) is not int or not 0<=index<len(events): raise ValueError('Unknown source event')
        if not isinstance(raw['source_quote'],str) or not raw['source_quote'].strip() or raw['source_quote'] not in events[index]:
            raise ValueError('Inventory quote must be literal source')
        kind=raw['kind']
        if kind=='person': actors=list(people)
        elif kind=='object':
            subject=raw['subject']
            if not isinstance(subject,str) or not subject.strip() or subject not in '\n'.join([*events,*case['facts'],case['previous_tail']]):
                raise ValueError('Object name must be literal source')
            actors=[subject]
        elif kind=='scene': actors=['叙述整体']
        else: raise ValueError('Unknown inventory kind')
        if not isinstance(raw['actions'],list) or not 1<=len(raw['actions'])<=10: raise ValueError('Invalid action inventory')
        actions=[Action.model_validate(action) for action in raw['actions']]
        if len({(a.text,a.temporal_scope) for a in actions})!=len(actions):raise ValueError('Duplicate action inventory')
        cells+=len(actors)*len(actions)
        tables.append({'event_index':index,'actors':actors,'actions':actions,'source_quote':raw['source_quote']})
        covered.add(index)
    if covered!=set(range(len(events))) or not 1<=len(tables)<=16 or cells>96:
        raise ValueError('Incomplete source-event inventory or over limit; do not drop requirements')
    return tables

inventory_prompt='''只从完整计划和上下文建立事实问题清单，不读正文，不判断草稿是否通过。每个events原项必须覆盖，保留全部动作、主体、数量、否定范围、先后、同刻、所有权/路线同一性限定。问题写成单个肯定事实，不把多个独立事实合成一个问题；动作、位置、结束状态分开。共享活动不等于每人各自独立操作。人类动作kind=person，服务端会展开到所有已知people，不必你挑人物；物件状态kind=object且subject逐字来自来源；全章禁止/存在性kind=scene。正常语境表达与同义动作可以证明，不增加必须出现验收原词的要求。同一路径/自己来路须问返回路线与进入路线是否为同一路线，不能只问有路可出；同刻/先后必须保留在相关问题中。temporal_scope=occurrence问章内发生过，end_state仅用于明确结尾仍成立，不把已完成动作要求永远持续。text只写动作/状态（不带主体），且为肯定式；禁止/缺失由稍后来源表判为forbidden，不把负问句交给正文阅读者。相同含义可合并，但不可遗漏义务。返回JSON:{"tables":[{"event_index":0,"kind":"person|object|scene","subject":"object物件名，其余空串","source_quote":"对应事件逐字连续片段","actions":[{"text":"单个肯定事实问题","temporal_scope":"occurrence|end_state"}]}]}。最多16表、96个人物动作格子，不能截断。'''
tables = checked([{'role':'system','content':inventory_prompt}, {'role':'user','content':json.dumps({'events':events,'people':people,'context':context},ensure_ascii=False)}], inventory_check, stage='inventory', tokens=5000)

TABLE_INSTRUCTION='''逐表、逐人、逐动作填完整格子。每个表的actors×actions每格都要独立回答，不能跳格，不能以一人的动作代替另一人。多人共享查看/操作过程不要求每个人独自完成全部操作。允许自然同义表达、代词和语境中明确的省略；不能凭剧情合理就补上没有依据的坐姿、权限获得或路线同一性。叙述整体作为主体时回答整篇是否存在该事实。occurrence问本章是否发生过；end_state问结尾仍成立，曾满足但后来撤销不能当作结尾满足。证据只能选segments中的编号，服务端取原文，不生成引文。required/forbidden/observed必须给有效证据编号。reason一句简短依据。返回JSON:{"tables":[{"table_id":0,"cells":[{"actor_id":0,"action_id":0,"status":"状态","evidence_ids":[0],"reason":"依据"}]}]}。每个table_id必须有且仅有一份，所有格子完整。'''

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
            result[i]=parse_matrix({'cells':row['cells']},actors=t['actors'],actions=t['actions'],segments=segments,mode=mode)
        return result
    instruction=TABLE_INSTRUCTION+('只读原要求，不看正文。status=required|forbidden|not_required|uncertain。原要求禁止肯定事实时用forbidden；没要求不等于禁止。' if mode=='requirements' else '只读正文，不读计划、目标、希望满足的结果。status=observed|not_observed|uncertain。记录文中事实，不为作者补完。')
    content={'tables':table_wire(items),'segments':[{'id':i,'text':s} for i,s in enumerate(segments)]}
    if extra:content.update(extra)
    return checked([{'role':'system','content':instruction},{'role':'user','content':json.dumps(content,ensure_ascii=False)}],parse,stage=stage,tokens=8000)

required=read_tables(tables,events,'requirements',stage='source_matrix',extra={'context':context})
for matrix in required.values():
    if not any(c.status in {'required','forbidden','uncertain'} for c in matrix.cells):raise ValueError('Source table contains no obligations')

PREMISE_PROMPT='''只识别给定negative段落中人物明确缺少的知识、资源、权限、能力；每个negative_id必须返回一项。你只看该段及前一段以解析说话人，不看之后剧情，不判断矛盾。普通“没说话/没问/不愿/尚未做某动作”和不许做的规范不等于缺少能力，conditions=[]并解释。真正缺少时返回actor（people中的确切名字）、condition（保留具体限定的肯定资源/能力名）、quote（该negative段逐字片段）。例：缺少修改文件权限，不等于缺少读取文件权限；不能省略修改限定。不要因为可能撒谎就丢掉缺失声明，谎话会由另一步核实。返回JSON:{"entries":[{"negative_id":0,"conditions":[{"actor":"名字","condition":"肯定资源或能力","quote":"逐字片段"}],"reason":"分类依据"}]}。每段最多2个条件。'''

def premise_inventory(text):
    segments=draft_segments(text)
    negative=[i for i,s in enumerate(segments) if re.search('没有|不能|无法|没|不知|不会|不够|未',s)]
    if not negative:return []
    def check(data):
        if not isinstance(data,dict) or set(data)!={'entries'}:raise ValueError('Premise entries required')
        rows=data['entries']
        if not isinstance(rows,list) or len(rows)!=len(negative) or any(type(r.get('negative_id')) is not int for r in rows) or {r['negative_id'] for r in rows}!=set(negative):raise ValueError('Premise coverage incomplete')
        result=[]
        for row in rows:
            index=row['negative_id']
            if set(row)!={'negative_id','conditions','reason'} or not isinstance(row['conditions'],list) or len(row['conditions'])>2:raise ValueError('Premise fields invalid')
            for condition in row['conditions']:
                if set(condition)!={'actor','condition','quote'} or condition['actor'] not in people or not condition['condition'].strip() or not condition['quote'].strip() or condition['quote'] not in segments[index]:raise ValueError('Ungrounded premise')
                resource=condition['condition'];actor=condition['actor']
                questions=[f'在第{index}段明确表示缺少：{resource}',f'在第{index}段的缺失声明之后实际依赖或使用：{resource}',f'在第{index}段的缺失声明之后、使用之前正文明确交代获得或恢复：{resource}',f'正文明确说明第{index}段的缺失声明是撒谎、误解或玩笑']
                result.append({'actors':[actor],'actions':[Action(text=q,temporal_scope='occurrence') for q in questions],'negative_id':index,'condition':resource})
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
        emit({'event':'comparison','phase':phase,'table_id':i,'failed':result.failed,'uncertain':result.uncertain})
        actual_by={(c.actor_id,c.action_id):c for c in actual[i].cells}
        source_by={(c.actor_id,c.action_id):c for c in required[i].cells}
        for actor_id,action_id in (*result.failed,*result.uncertain):
            cell=actual_by[(actor_id,action_id)];source=source_by[(actor_id,action_id)]
            target=t['actors'][actor_id]+t['actions'][action_id].text
            findings.append({'conflict_key':f'matrix-{i}-{actor_id}-{action_id}','conflict_type':'plotline','severity':'major','scope':'local','evidence':[{'chapter':2,'quote':actual[i].segments[index]} for index in cell.evidence_ids], 'suggestion':f'按原计划的{source.status}要求检查并最小修正：{target}。原要求：{events[t["event_index"]]}。正文依据：{cell.reason}。不要把含蓄表达一律改成直白说明，不添加计划外事实。'})
    for offset,t in enumerate(premises,start=len(tables)):
        cells=actual[offset].cells;states={c.action_id:c.status for c in cells}
        if states[0]!='observed':raise ValueError('Premise inventory not substantiated in independent reading')
        uncertain=any(value=='uncertain' for value in states.values())
        conflict=states[1]=='observed' and states[2]!='observed' and states[3]!='observed'
        emit({'event':'premise_comparison','phase':phase,'actor':t['actors'][0],'condition':t['condition'],'states':states,'conflict':conflict,'uncertain':uncertain})
        if conflict or uncertain:
            findings.append({'conflict_key':'premise-'+str(t['negative_id']),'conflict_type':'plotline','severity':'major','scope':'local','evidence':[{'chapter':2,'quote':actual[offset].segments[index]} for c in cells for index in c.evidence_ids], 'suggestion':'角色缺少的前提没有得到/恢复过程，却完成依赖它的动作，或前提状态有歧义：'+t['actors'][0]+'，'+t['condition']+'。保持原计划和台账事实，通过最小修订交代或纠正，不能凭空新增权限、能力或物品。'})
    return findings

style=next((r['style_profile'] for r in STYLE_PRESETS if r['id']==case['style']),{})
findings=inspect(draft,'before')
for revision in range(2):
    if not findings:break
    state={'draft':draft,'chapter_seq':2,'plan':{'goals':[case['goal']],'expected_events':events,'hard_constraints':case['facts']},'style_profile':style,'audit_verdict':{'findings':findings}}
    raw=ask(prompts.patch_messages(state),stage='patch',tokens=3000,role='writer',json_mode=False)
    patched=apply_patches(draft,parse_patches(raw))
    emit({'event':'patch','revision':revision+1,'applied':patched.applied,'reason':patched.rejected_reason,'spans':[{'target':p.target,'replacement':p.replacement} for p in patched.applied_spans]})
    if patched.applied:draft=patched.content
    else:
        draft=_check_draft(ask(prompts.revise_messages(draft,findings,2,plan=state['plan'],style_profile=style,target_words=650),stage='full_revision',tokens=3200,role='writer',json_mode=False))
    findings=inspect(draft,'after-'+str(revision+1))
emit({'event':'final','passed':not findings,'unresolved':findings,'text':draft,'attempts':attempts})
