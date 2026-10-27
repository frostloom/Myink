import unittest
from task_logic import stable_unique

class OrderingTests(unittest.TestCase):
    def test_empty(self): self.assertEqual(stable_unique([]), [])
    def test_singleton(self): self.assertEqual(stable_unique(['b']), ['b'])
    def test_repeated(self):
        values=['a','a']
        self.assertEqual(stable_unique(values), ['a'])
        self.assertEqual(values, ['a','a'])
    def test_first_occurrence(self):
        values=['b','a','b']
        self.assertEqual(stable_unique(values), ['b','a'])
        self.assertEqual(values, ['b','a','b'])
    def test_distinct_order(self):
        values=['z','x','y']
        self.assertEqual(stable_unique(values), ['z','x','y'])
        self.assertEqual(values, ['z','x','y'])
