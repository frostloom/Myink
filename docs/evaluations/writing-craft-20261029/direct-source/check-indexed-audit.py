import ast,unittest
from pathlib import Path
p=Path(__file__).with_name('symmetric-audit-indexed.py');t=ast.parse(p.read_text());ns={}
exec(compile(ast.Module(body=[n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='indexed_batch'],type_ignores=[]),str(p),'exec'),ns)
class IndexedTests(unittest.TestCase):
 def setUp(self):
  self.assertTrue('indexed_batch' in ns,'Missing program-owned source binding')
  self.units=[{'id':'A','mode':'obligation','requirement':'甲乙都已签字'}];self.segments={'A':['甲乙均已签字']};self.row={'id':'A','status':'supported','evidence_ids':[0],'reason':'两人已签'}
 def parse(self,row):return ns['indexed_batch']({'units':[row]},self.units,self.segments)
 def test_original_source_is_filled_by_program(self):self.assertEqual(self.parse(self.row)['units'][0]['source_requirement'],'甲乙都已签字')
 def test_body_quote_cannot_impersonate_source(self):
  with self.assertRaises(ValueError):self.parse({**self.row,'source_quote':'甲签过字'})
 def test_unknown_id_rejected(self):
  with self.assertRaises(ValueError):self.parse({**self.row,'id':'B'})
 def test_incomplete_batch_rejected(self):
  with self.assertRaises(ValueError):ns['indexed_batch']({'units':[]},self.units,self.segments)
 def test_boolean_evidence_rejected(self):
  with self.assertRaises(ValueError):self.parse({**self.row,'evidence_ids':[True]})
 def test_unsupported_positive_rejected(self):
  with self.assertRaises(ValueError):self.parse({**self.row,'evidence_ids':[]})
if __name__=='__main__':unittest.main()
