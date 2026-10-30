import ast,json,re
from pathlib import Path
from myink.workflow.action_matrix import Action,resolve_subject_source
root=Path('/private/tmp/myink-proof-eval')
sample=json.loads((root/'suite-matrix-v9.json').read_text())[0]
case=sample['case'];events=[*case['expected_events'],case['must_end'],case['goal']]
namespace={'Action':Action,'resolve_subject_source':resolve_subject_source,'re':re,'case':case,'events':events,'people':sample['participants']}
module=ast.parse((root/'matrix-pipeline-scoped-v10.py').read_text())
functions=[node for node in module.body if isinstance(node,ast.FunctionDef) and node.name in {'inventory_check','normalize_tables','table_batches','table_wire','read_tables_once'}]
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

from myink.workflow.action_matrix import parse_source_matrix,parse_matrix
namespace['json']=json
namespace.update({'parse_source_matrix':parse_source_matrix,'parse_matrix':parse_matrix,'SOURCE_INSTRUCTION':'来源','TABLE_INSTRUCTION':'正文'})
namespace['checked']=lambda messages,check,**kwargs:check(namespace['fake'])
item=namespace['inventory_check'](raw,{0})[0]
assert namespace['table_wire']([item],requirements=True)[0]['source_event_id']==0
assert 'source_event_id' not in namespace['table_wire']([item])[0]
cell={'actor_id':0,'action_id':0,'evidence_ids':[1],'reason':'原文依据','required_individually':True,'required_as_one_of':False,'must_be_absent':False,'uncertain':False}
namespace['fake']={'tables':[{'table_id':0,'cells':[cell]}]}
try:namespace['read_tables_once']([item],events,'requirements',stage='unit')
except ValueError:pass
else:raise AssertionError('Accepted another source event as required evidence')
cell['evidence_ids']=[0]
assert namespace['read_tables_once']([item],events,'requirements',stage='unit')[0].cells[0].status=='required'
print('Source-unit evidence boundary checks passed')
