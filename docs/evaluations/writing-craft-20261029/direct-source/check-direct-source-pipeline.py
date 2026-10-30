import ast,json
from pathlib import Path
root=Path('/private/tmp/myink-proof-eval');payload=json.loads((root/'suite-direct-source-pipeline.json').read_text())[0]
text=(root/'direct-source-pipeline.py').read_text();tree=ast.parse(text)
ns={'people':payload['participants']}
functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'frame_supported','parse_specs','direct_result','finding'}]
exec(compile(ast.Module(body=functions,type_ignores=[]),'pipeline-helpers','exec'),ns)
items=[{'id':0,'text':payload['case']['expected_events'][0]}]
none={'units':[{'unit_id':0,'status':'none','frames':[],'reason':'不属于两类专门核对'}]}
assert ns['parse_specs'](none,items)==[]
for broken in [{'units':[]},{'units':[{'unit_id':False,'status':'none','frames':[],'reason':'x'}]}, {'units':[{'unit_id':0,'status':'framed','frames':[{'kind':'route_identity','actors':['陌生人'],'source_quote':items[0]['text']}],'reason':'x'}]}]:
 try:ns['parse_specs'](broken,items)
 except ValueError:pass
 else:raise AssertionError('Invalid source specs accepted')
uncertain={'units':[{'unit_id':0,'status':'uncertain','frames':[],'reason':'不能确定主体'}]}
try:ns['parse_specs'](uncertain,items)
except RuntimeError:pass
else:raise AssertionError('Uncertain source treated as complete')
segments=['正文']*8
assert ns['direct_result']({'status':'supported','evidence_ids':[],'reason':'没有相反事实'},segments,'consistency')['status']=='supported'
assert len(ns['direct_result']({'status':'supported','evidence_ids':list(range(8)),'reason':'完整证据'},segments,'obligation')['evidence_ids'])==8
for ids in [[],[False],[8],[0.0],list(range(9))]:
 try:ns['direct_result']({'status':'supported','evidence_ids':ids,'reason':'x'},segments,'obligation')
 except ValueError:pass
 else:raise AssertionError('Invalid fulfillment evidence accepted')
controls=json.loads((root/'source-frame-calibration.json').read_text())['cases'];cases={c['id']:c for c in controls}
for line in (root/'source-frame-calibration.jsonl').read_text().splitlines():
 r=json.loads(line)
 if r['event']=='result':
  case=cases[r['id']]
  from myink.workflow.chapter_checks import draft_segments
  assert ns['frame_supported'](r['result'],case,draft_segments(case['text']))==case['expected_supported']
source={'id':0,'text':'人物已坐下'};result=ns['finding'](source,'没有依据',[0],['实际原文'],actor='甲')
assert result['scope']=='unknown' and result['evidence'][0]['quote']=='实际原文'
print('Composite source inventory/evidence/actor protocols verified; archived 8 frame outputs retain labels')
