import unittest
from task_logic import parse_seconds

class NumericTests(unittest.TestCase):
    def test_zero(self): self.assertEqual(parse_seconds('0'), 0)
    def test_whole(self): self.assertEqual(parse_seconds('2'), 2000)
    def test_ten(self): self.assertEqual(parse_seconds('10'), 10000)
    def test_subsecond(self): self.assertEqual(parse_seconds('0.125'), 125)
    def test_fractional_whole(self): self.assertEqual(parse_seconds('1.001'), 1001)
