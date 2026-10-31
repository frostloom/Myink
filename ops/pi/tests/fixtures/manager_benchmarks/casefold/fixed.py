import unittest
from managed_names import normalize_name
class NameTests(unittest.TestCase):
    def test_german(self): self.assertEqual(normalize_name('Straße'),'strasse')
    def test_sigma(self): self.assertEqual(normalize_name('ΟΣ'),'οσ')
    def test_ascii(self): self.assertEqual(normalize_name(' A '),'a')
    def test_chinese(self): self.assertEqual(normalize_name('中文'),'中文')
    def test_empty(self): self.assertEqual(normalize_name(' '),'')
