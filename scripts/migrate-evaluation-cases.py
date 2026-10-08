"""One-time, deterministic migration of existing synthetic constants (never executes scripts)."""
import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def constant(path,name):
    tree=ast.parse((ROOT/path).read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(name)


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8'))==data:return
        raise ValueError(f'refusing to overwrite edited case: {path}')
    path.write_text(text,encoding='utf-8')


def make_case(name,group,positive,category,source,seq,ctx,draft,plan,types,sources,description,adapted=()):
    return {'schema_version':1,'id':f'{source.split("/")[-1].replace("eval-","").replace(".py","")}.{name}',
            'group_id':group,'split':'holdout' if category in ('capability','allegiance') else 'development',
            'mode':'audit','category':category,'polarity':'positive' if positive else 'negative',
            'source':{'path':source,'case_name':name,'adapted_from':list(adapted)},
            'input':{'chapter_seq':seq,'context':ctx,'plan':plan,'draft':draft},
            'expected':{'allowed_verdicts':['rewrite'] if positive else ['pass'],
                'required_issues':[{'id':name,'description':description,'allowed_conflict_types':types,
                    'allowed_severities':['major','critical'],'evidence_sources':sources}] if positive else [],
                'forbidden_issues':[] if positive else [description]},
            'label':{'status':'proposed','review_note':'从既有合成案例迁移；类型别名为暂定允许集合，正式指标前需维护者复核。',
                     'reviewer':None}}


def main():
    logic=constant('scripts/eval-logic.py','cases')
    categories=['visit','item','promise','capability','allegiance']
    types=[['plotline','character','timeline'],['item_rule'],['plotline','foreshadow'],['item_rule','power'],['character_state','faction','character']]
    descriptions=['首次来访与既有经历矛盾；正常重访不得误报','毁坏的旧物直接再现；明确更换新物不得误报',
        '尚未履行却直接认定完成；实际修复后完成承诺不得误报','无供能却正常使用；补足供能条件不得误报',
        '解除身份却直接声称从未解除；外部承包身份不得误报']
    for index,(name,expected_pass,tail,draft,rule) in enumerate(logic):
        group=index//2;ctx={'short_context':[{'kind':'prev_chapter_tail','chapter':1,'tail':tail}],
            'long_term_facts':[{'content':rule,'is_hard':True}] if rule else []}
        sources=[{'chapter':1,'pointer':'/input/context/short_context/0/tail'},{'chapter':2,'pointer':'/input/draft'}]
        c=make_case(name,'logic.'+categories[group],not expected_pass,categories[group],
            'scripts/eval-logic.py',2,ctx,draft,{},types[group],sources,descriptions[group],[f'conflict-samples:{5+group:02d}'])
        save(ROOT/'evals/cases/audit'/f'{c["id"]}.json',c)
    for old in constant('scripts/eval-continuity.py','CASES'):
        name=old['name'];ctx={'short_context':[{'kind':'prev_chapter_tail','chapter':5,'tail':old['tail']}],
            'recent_openings':[{'chapter':4,'text':old['history']}] if old.get('history') else []}
        sources=[{'chapter':5,'pointer':'/input/context/short_context/0/tail'},{'chapter':6,'pointer':'/input/draft'}]
        if old.get('history'):sources[0]={'chapter':4,'pointer':'/input/context/recent_openings/0/text'}
        group='continuity.threat' if name in ('pending_threat_dropped','natural_same_scene_continuation') else 'continuity.'+name
        c=make_case(name,group,old['expected']!='pass','continuity','scripts/eval-continuity.py',6,ctx,
            old['draft'],{'goals':[old['goal']],'expected_events':[old['goal']]},['plotline','timeline','style'],sources,
            '已完成动作不得重演、未解决威胁不得无交代丢弃、开头不得机械重复；合理衔接与恢复不得误报')
        save(ROOT/'evals/cases/audit'/f'{c["id"]}.json',c)
    import re
    spec=(ROOT/'spec/conflict-samples.md').read_text(encoding='utf-8')
    tests=ast.parse((ROOT/'tests/test_conflict_sample_suite.py').read_text(encoding='utf-8'))
    functions={int(m.group(1)):n.name for n in tests.body if isinstance(n,ast.FunctionDef)
               and (m:=re.match(r'test_sample_(\d+)_',n.name))}
    catalog=[]
    for number,title in re.findall(r'^### 样例 (\d+) · (.+)$',spec,re.M):
        n=int(number);note='机制套件；模型/embedding 为替身，未在本轮重跑'
        if n in (5,6,7,8,9):note='xfail 记录检测机制缺口'
        if n in (28,29,30):note='真空阴性：入口未充分覆盖，不算正常放行证据'
        if n==4:note='有相关检出，但类别/严重度与规范不完全一致'
        if n==38:note='名称错配：测试实际覆盖卷规划偏移，不能算文风漂移验证'
        catalog.append({'id':f'conflict-samples:{n:02d}','title':title,
            'polarity':'positive' if n in (*range(1,24),33,34,38) else 'negative','source':'spec/conflict-samples.md',
            'test':{'path':'tests/test_conflict_sample_suite.py','function':functions[n]},
            'coverage':'gap' if n in (5,6,7,8,9,28,29,30,38) else 'implemented',
            'evidence_kind':'mechanism_with_model_stub','note':note})
    save(ROOT/'evals/catalog.json',{'schema_version':1,'cases':catalog})
    print('Migrated 15 audit cases and 40-entry catalog without executing old scripts.')


if __name__=='__main__':main()
