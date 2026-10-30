import ast,unittest
from pathlib import Path
p=Path(__file__).with_name('direct-source-symmetric-pipeline.py');t=ast.parse(p.read_text());ns={}
exec(compile(ast.Module(body=[n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='merge_verdicts'],type_ignores=[]),str(p),'exec'),ns)
class SymmetricTests(unittest.TestCase):
 def setUp(self):self.assertTrue('merge_verdicts' in ns,'Missing symmetric all-unit merge')
 def decide(self,a,b):return ns['merge_verdicts']({'status':a},{'status':b})
 def test_supported_first_cannot_bypass_failed_second(self):self.assertEqual(self.decide('supported','violated'),'hold')
 def test_supported_second_does_not_overwrite_failed_first(self):self.assertEqual(self.decide('missing','supported'),'hold')
 def test_both_supported_required_for_pass(self):self.assertEqual(self.decide('supported','supported'),'pass')
 def test_uncertain_never_authorizes_repair_or_pass(self):self.assertEqual(self.decide('missing','uncertain'),'hold')
 def test_two_failed_obligations_allow_only_source_bound_repair(self):self.assertEqual(self.decide('missing','violated'),'repair')
if __name__=='__main__':unittest.main()
