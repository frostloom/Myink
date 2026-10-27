import unittest
from managed_names import normalize_name
class NameTests(unittest.TestCase):
    def test_decomposed(self): self.assertEqual(normalize_name('Cafe\u0301'),'Café')
    def test_hangul(self): self.assertEqual(normalize_name('\u1100\u1161'),'가')
    def test_trim(self): self.assertEqual(normalize_name(' 林砚 '),'林砚')
    def test_composed(self): self.assertEqual(normalize_name('é'),'é')
    def test_empty(self): self.assertEqual(normalize_name(' '),'')
