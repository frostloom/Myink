import ast,json,unittest
from pathlib import Path
from myink.workflow.patches import apply_patches,parse_patches
root=Path(__file__).parent
source=root/'direct-source-transaction-pipeline.py'
tree=ast.parse(source.read_text());ns={'apply_patches':apply_patches}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='stage_patch'],type_ignores=[]),str(source),'exec'),ns)
sample=json.loads((root/'suite-direct-source-pipeline.json').read_text())[0]
rows=[json.loads(l) for l in (root/'patch-thinking-pilot-P05.jsonl').read_text().splitlines()]
patches=parse_patches(next(r['patches'] for r in rows if r.get('event')=='result' and r['applied']))
class TransactionTests(unittest.TestCase):
 def setUp(self):self.assertTrue('stage_patch' in ns,'Missing staged repair gate')
 def test_rejected_target_preserves_original(self):
  actual,accepted,reason=ns['stage_patch'](sample['draft'],patches,lambda candidate:False)
  self.assertFalse(accepted);self.assertEqual(actual,sample['draft'])
 def test_uncertain_truthy_value_cannot_commit(self):
  actual,accepted,reason=ns['stage_patch'](sample['draft'],patches,lambda candidate:'uncertain')
  self.assertFalse(accepted);self.assertEqual(actual,sample['draft'])
 def test_verified_candidate_commits_exact_applied_text(self):
  actual,accepted,reason=ns['stage_patch'](sample['draft'],patches,lambda candidate:True)
  self.assertTrue(accepted);self.assertEqual(actual,apply_patches(sample['draft'],patches).content)
 def test_unapplicable_patch_never_calls_model(self):
  def forbidden(candidate):raise AssertionError('Invalid patch was verified')
  actual,accepted,reason=ns['stage_patch'](sample['draft'],[],forbidden)
  self.assertFalse(accepted);self.assertEqual(actual,sample['draft'])
 def test_checker_failure_cannot_return_candidate(self):
  def unavailable(candidate):raise RuntimeError('Budget exhausted')
  with self.assertRaises(RuntimeError):ns['stage_patch'](sample['draft'],patches,unavailable)
if __name__=='__main__':unittest.main()
