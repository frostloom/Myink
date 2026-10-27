import unittest
from task_logic import parse_assignment

class ParsingTests(unittest.TestCase):
    def test_simple(self): self.assertEqual(parse_assignment('a=b'), ('a','b'))
    def test_trim(self): self.assertEqual(parse_assignment(' x = y '), ('x','y'))
    def test_empty_value(self): self.assertEqual(parse_assignment('flag='), ('flag',''))
    def test_embedded_equals(self): self.assertEqual(parse_assignment('url=left=right'), ('url','left=right'))
    def test_multiple_equals(self): self.assertEqual(parse_assignment('expr=a=b=c'), ('expr','a=b=c'))
