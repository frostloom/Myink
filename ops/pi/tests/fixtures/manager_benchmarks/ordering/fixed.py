import unittest
from task_logic import stable_unique

class OrderingTests(unittest.TestCase):
    def test_empty(self): self.assertEqual(stable_unique([]), [])
    def test_singleton(self): self.assertEqual(stable_unique(['b']), ['b'])
    def test_repeated(self):
        values=['a','a']
        self.assertEqual(stable_unique(values), ['a'])
        self.assertEqual(values, ['a','a'])
    def test_first_occurrence(self): self.assertEqual(stable_unique(['b','a','b']), ['b','a'])
    def test_distinct_order(self): self.assertEqual(stable_unique(['z','x','y']), ['z','x','y'])
