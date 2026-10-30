import ast,json,unittest,types
from contextlib import nullcontext
from pathlib import Path
from myink.workflow.patches import apply_patches,parse_patches
root=Path(__file__).parent
path=root/'direct-source-symmetric-pipeline.py';tree=ast.parse(path.read_text())
main=next(n for n in reversed(tree.body) if isinstance(n,ast.Try))
helpers=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in ['stage_patch','checked','IncompleteOutput']]
sample=json.loads((root/'suite-direct-source-pipeline.json').read_text())[0]
rows=[json.loads(l) for l in (root/'patch-thinking-pilot-P05.jsonl').read_text().splitlines()]
patches=parse_patches(next(r['patches'] for r in rows if r.get('event')=='result' and r['applied']))
original=sample['draft'];candidate=apply_patches(original,patches).content
class OrchestrationTests(unittest.TestCase):
 def run_flow(self,final_findings=None,final_holds=None,initial_hold=False,failure=None):
  events=[];calls=[];attempts=[]
  ns={'draft':original,'case':sample['case'],'writer_events':sample['case']['expected_events'],'style':{},'snapshot':{},'attempts':0,'apply_patches':apply_patches,'parse_patches':parse_patches,'bind_resources':lambda _:nullcontext(),'prompts':types.SimpleNamespace(patch_messages=lambda state:[{'role':'system','content':'rules'},{'role':'user','content':state['draft']}]),'emit':events.append}
  exec(compile(ast.Module(body=helpers,type_ignores=[]),str(path),'exec'),ns)
  real_checked=ns['checked']
  def ask(*a,**kw):attempts.append(1);raise ns['IncompleteOutput']('truncated','partial')
  ns['ask']=ask
  def checked(*a,stage,**kw):
   if stage=='patch_candidate':return patches
   return real_checked(*a,stage=stage,**kw)
  ns['checked']=checked
  def inspect(text,phase):
   calls.append((phase,text))
   if phase=='before':return [{'conflict_key':'direct-2'}],([{'source_id':6}] if initial_hold else [])
   if failure=='final_cap':raise RuntimeError('Request cap exhausted')
   if failure=='final_protocol':raise ValueError('Invalid final audit IDs')
   if failure=='final_truncated':return checked([],lambda data:data,stage='truncated-final')
   return final_findings or [],final_holds or []
  def target(text,findings):
   if failure=='target_truncated':return checked([],lambda data:data,stage='truncated-target')
   return True
  ns['inspect']=inspect;ns['inspect_targets']=target
  try:exec(compile(ast.Module(body=[main],type_ignores=[]),str(path),'exec'),ns)
  except SystemExit:pass
  return ns,events,calls,attempts
 def test_final_finding_keeps_original_and_diagnostics_bound_to_candidate(self):
  ns,events,calls,_=self.run_flow(final_findings=[{'conflict_key':'direct-6'}]);final=events[-1]
  self.assertFalse(final['passed']);self.assertEqual(final['text'],original)
  self.assertEqual(final.get('diagnostic_text'),candidate)
 def test_final_hold_keeps_original(self):
  ns,events,calls,_=self.run_flow(final_holds=[{'source_id':6}]);self.assertFalse(events[-1]['passed']);self.assertEqual(ns['draft'],original)
 def test_initial_hold_clears_only_after_full_final_inspection(self):
  ns,events,calls,_=self.run_flow(initial_hold=True);self.assertEqual([p for p,t in calls],['before','final']);self.assertEqual(calls[-1][1],candidate);self.assertTrue(events[-1]['passed']);self.assertEqual(ns['draft'],candidate)
 def test_persisting_initial_hold_blocks_final(self):
  ns,events,calls,_=self.run_flow(initial_hold=True,final_holds=[{'source_id':6}]);self.assertFalse(events[-1]['passed']);self.assertEqual(ns['draft'],original)
 def test_final_cap_or_protocol_failure_preserves_original(self):
  for failure in ['final_cap','final_protocol']:
   with self.subTest(failure=failure):
    ns,events,calls,_=self.run_flow(failure=failure);self.assertEqual(events[-1]['event'],'pipeline_failed');self.assertEqual(ns['draft'],original)
 def test_actual_retry_exhaustion_at_target_or_final_preserves_original(self):
  for failure in ['target_truncated','final_truncated']:
   with self.subTest(failure=failure):
    ns,events,calls,attempts=self.run_flow(failure=failure);self.assertEqual(len(attempts),2);self.assertEqual(events[-1]['event'],'pipeline_failed');self.assertEqual(ns['draft'],original)
if __name__=='__main__':unittest.main()
