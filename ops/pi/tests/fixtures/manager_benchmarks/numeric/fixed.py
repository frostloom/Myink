import unittest
from task_logic import parse_seconds

class NumericTests(unittest.TestCase):
    def assert_milliseconds(self, value, expected):
        actual=parse_seconds(value)
        self.assertIs(type(actual), int)
        self.assertEqual(actual, expected)
    def test_zero(self): self.assert_milliseconds('0', 0)
    def test_whole(self): self.assert_milliseconds('2', 2000)
    def test_ten(self): self.assert_milliseconds('10', 10000)
    def test_subsecond(self): self.assert_milliseconds('0.125', 125)
    def test_fractional_whole(self): self.assert_milliseconds('1.001', 1001)
