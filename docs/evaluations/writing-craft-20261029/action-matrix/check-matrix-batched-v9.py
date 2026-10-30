import ast,json,re
from pathlib import Path
from myink.workflow.action_matrix import Action,resolve_subject_source
root=Path('/private/tmp/myink-proof-eval')
sample=json.loads((root/'suite-matrix-v9.json').read_text())[0]
case=sample['case'];events=[*case['expected_events'],case['must_end'],case['goal']]
namespace={'Action':Action,'resolve_subject_source':resolve_subject_source,'re':re,'case':case,'events':events,'people':sample['participants']}
module=ast.parse((root/'matrix-pipeline-batched-v9.py').read_text())
functions=[node for node in module.body if isinstance(node,ast.FunctionDef) and node.name in {'inventory_check','normalize_tables','table_batches'}]
exec(compile(ast.Module(body=functions,type_ignores=[]),'batch-functions','exec'),namespace)
raw={'tables':[{'event_index':0,'kind':'person','subject':'秦鹤','members':['秦鹤'],'subject_source_id':1,'source_quote':'仅用一次短风术托起已经在绳套上的药袋越过尖棱','actions':[{'text':'用一次短风术托袋','temporal_scope':'occurrence'}]}]}
assert namespace['inventory_check'](raw,{0})[0]['actors']==['秦鹤']
for bad in [False,999,0,'1',None]:
 invalid=json.loads(json.dumps(raw));invalid['tables'][0]['subject_source_id']=bad
 try:namespace['inventory_check'](invalid,{0})
 except ValueError:pass
 else:raise AssertionError('Invalid subject source accepted: '+repr(bad))
items=[{'actors':['甲','乙'],'actions':list(range(9)),'event_index':3,'source_quote':'原句'}]
normalized=namespace['normalize_tables'](items)
assert [a for table in normalized for a in table['actions']]==list(range(9))
assert all(t['actors']==['甲','乙'] and t['event_index']==3 and t['source_quote']=='原句' for t in normalized)
batches=list(namespace['table_batches'](normalized))
assert [t for _,batch in batches for t in batch]==normalized
assert all(sum(len(t['actors'])*len(t['actions']) for t in batch)<=8 for _,batch in batches)
assert [offset for offset,_ in batches]==[0,1,2]
try:namespace['normalize_tables']([{'actors':list(range(9)),'actions':[0]}])
except ValueError:pass
else:raise AssertionError('Actor alternative group was split')
print('Indexed subject binding and exact batch coverage checks passed')
