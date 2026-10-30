import ast,copy,unittest
from pathlib import Path
p=Path(__file__).with_name('direct-source-confirmed-pipeline.py')
tree=ast.parse(p.read_text())
names={'confirmation_result','confirmation_resolution'}
ns={}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),str(p),'exec'),ns)
class GateTests(unittest.TestCase):
 def setUp(self):
  self.assertTrue(names.issubset(ns),'Missing independent confirmation gate')
  self.source={'text':'甲乙都已签字。','mode':'obligation'}
  self.good={'decision':'confirmed','requirement_status':'not_supported','source_quote':'甲乙都已签字','evidence_ids':[0],'reason':'乙仍未签。'}
 def validate(self,r):return ns['confirmation_result'](r,self.source,['甲签好，乙约定明天签。'])
 def test_actual_omission_is_repairable(self):
  self.assertEqual(ns['confirmation_resolution'](self.validate(self.good)),'repair')
 def test_rejected_criticism_does_not_complete_other_obligations(self):
  r={**self.good,'decision':'rejected'}
  self.assertEqual(ns['confirmation_resolution'](self.validate(r)),'hold')
 def test_uncertain_never_authorizes_edit_or_pass(self):
  r={**self.good,'decision':'uncertain','requirement_status':'supported'}
  self.assertEqual(ns['confirmation_resolution'](self.validate(r)),'hold')
 def test_independently_supported_rejected_finding_clears(self):
  r={**self.good,'decision':'rejected','requirement_status':'supported'}
  self.assertEqual(ns['confirmation_resolution'](self.validate(r)),'clear')
 def test_source_quote_cannot_be_invented(self):
  with self.assertRaises(ValueError):self.validate({**self.good,'source_quote':'甲乙同时签字'})
 def test_confirmation_needs_actual_evidence(self):
  with self.assertRaises(ValueError):self.validate({**self.good,'evidence_ids':[]})
 def test_boolean_is_not_evidence_id(self):
  with self.assertRaises(ValueError):self.validate({**self.good,'evidence_ids':[True]})
 def test_out_of_range_evidence_rejected(self):
  with self.assertRaises(ValueError):self.validate({**self.good,'evidence_ids':[1]})
 def test_confirmation_with_supported_result_rejected(self):
  with self.assertRaises(ValueError):self.validate({**self.good,'requirement_status':'supported'})
 def test_positive_obligation_needs_fulfillment_evidence(self):
  with self.assertRaises(ValueError):self.validate({**self.good,'decision':'rejected','requirement_status':'supported','evidence_ids':[]})
 def test_empty_reason_rejected(self):
  with self.assertRaises(ValueError):self.validate({**self.good,'reason':' '})
if __name__=='__main__':unittest.main()
