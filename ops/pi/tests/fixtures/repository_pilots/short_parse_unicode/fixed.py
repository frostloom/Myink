"""Fixed isolated checks of the real short-draft parser's no-exception contract."""
import unittest
import importlib.util
import sys

# A regular myink package may already be installed in the checker image.
# Bind the actual frozen file, rather than resolving a namespace against site-packages.
spec = importlib.util.spec_from_file_location('frozen_short_parse', '/source/src/myink/workflow/short_parse.py')
parser = importlib.util.module_from_spec(spec)
initial_integer_limit = sys.get_int_max_str_digits()
spec.loader.exec_module(parser)
assert sys.get_int_max_str_digits() == initial_integer_limit, 'Candidate import must not alter integer limits'
def preserve_integer_limit(function, limit=initial_integer_limit):
    def call(*args, **kwargs):
        assert sys.get_int_max_str_digits() == limit, 'integer limit changed before call'
        try:
            return function(*args, **kwargs)
        finally:
            assert sys.get_int_max_str_digits() == limit, 'integer limit changed during call'
    return call

parse_short_draft = preserve_integer_limit(parser.parse_short_draft)
render_short_draft = preserve_integer_limit(parser.render_short_draft)
find_empty_chapters = preserve_integer_limit(parser.find_empty_chapters)

class ShortParseDigits(unittest.TestCase):
    def parse(self, text, n):
        numeric_limit = sys.get_int_max_str_digits()
        try:
            result = parse_short_draft(text, n)
        except Exception as error:
            self.fail('Parser no-exception contract violated: '+type(error).__name__)
        self.assertEqual(sys.get_int_max_str_digits(), numeric_limit, 'Do not alter interpreter numeric limits')
        self.assertEqual(len(result), max(0, n))
        self.assertTrue(all(type(part) is str for part in result))
        return result

    def malformed(self, heading):
        parts = self.parse(heading+'\n渡船靠岸。\n\n=== CHAPTER 2 CONTENT ===\n江面起雾。', 2)
        joined = '\n\n'.join(parts)
        self.assertEqual(joined.count('渡船靠岸。'), 1)
        self.assertEqual(joined.count('江面起雾。'), 1)
        self.assertLess(joined.index('渡船靠岸。'), joined.index('江面起雾。'))

    def test_tagged_oversized_ascii(self):
        self.malformed('=== CHAPTER '+'9'*5000+' CONTENT ===')

    def test_tagged_oversized_chinese(self):
        self.malformed('=== 第 '+'9'*5000+' 章 ===')

    def test_tagged_oversized_unicode(self):
        self.malformed('=== CHAPTER '+'٩'*5000+' CONTENT ===')

    def test_markdown_oversized(self):
        parts=self.parse('## CHAPTER '+'9'*5000+'\n渡船靠岸。\n\n## CHAPTER 2\n江面起雾。', 2)
        joined='\n\n'.join(parts)
        self.assertEqual(joined.count('渡船靠岸。'),1)
        self.assertEqual(joined.count('江面起雾。'),1)

    def test_large_zero_padded_valid_sequence(self):
        text='=== CHAPTER '+'0'*5000+'2 CONTENT ===\n第二章。\n\n=== CHAPTER 1 CONTENT ===\n第一章。'
        self.assertEqual(self.parse(text,2),['第一章。','第二章。'])

    def test_zero_padded_unicode_sequence(self):
        text='## 第 '+'٠'*5000+'٢ 章\n第二章。\n\n## 第 1 章\n第一章。'
        self.assertEqual(self.parse(text,2),['第一章。','第二章。'])

    def test_normal_tagged_gap(self):
        self.assertEqual(self.parse('=== CHAPTER 1 CONTENT ===\n一\n=== CHAPTER 3 CONTENT ===\n三',3),['一','','三'])

    def test_duplicate_document_order(self):
        self.assertEqual(self.parse('=== CHAPTER 1 CONTENT ===\n一\n=== CHAPTER 1 CONTENT ===\n二',2),['一','二'])

    def test_excess_blocks_preserve_paid_tail(self):
        self.assertEqual(self.parse('=== CHAPTER 1 CONTENT ===\n一\n=== CHAPTER 2 CONTENT ===\n二\n=== CHAPTER 3 CONTENT ===\n三',2),['一','二\n\n三'])

    def test_no_marker_paragraph_fallback(self):
        self.assertEqual(self.parse('渡船靠岸。\n\n江面起雾。',2),['渡船靠岸。','江面起雾。'])

    def test_render_empty_and_gaps(self):
        self.assertEqual(self.parse(render_short_draft(['一','','三']),3),['一','','三'])
        self.assertEqual(find_empty_chapters(['一','  ','三']),[2])

    def test_empty_and_nonpositive_count(self):
        self.assertEqual(self.parse('',2),['',''])
        self.assertEqual(self.parse('正文',0),[])


# Ordinary Unicode numbering remains part of this new immutable contract.
class OrdinaryUnicodeNumbers(unittest.TestCase):
    def check_order(self, two, one):
        text='=== CHAPTER '+two+' CONTENT ===\n第二章。\n\n=== CHAPTER '+one+' CONTENT ===\n第一章。'
        self.assertEqual(parse_short_draft(text,2),['第一章。','第二章。'])

    def test_arabic_indic_nonzero_digits(self): self.check_order('٢','١')
    def test_extended_arabic_indic_nonzero_digits(self): self.check_order('۲','۱')
    def test_devanagari_nonzero_digits(self): self.check_order('२','१')
    def test_fullwidth_nonzero_digits(self): self.check_order('２','１')


DECIMAL_ZEROS = (48, 1632, 1776, 1984, 2406, 2534, 2662, 2790, 2918, 3046, 3174, 3302, 3430, 3558, 3664, 3792, 3872, 4160, 4240, 6112, 6160, 6470, 6608, 6784, 6800, 6992, 7088, 7232, 7248, 42528, 43216, 43264, 43472, 43504, 43600, 44016, 65296, 66720, 68912, 69734, 69872, 69942, 70096, 70384, 70736, 70864, 71248, 71360, 71472, 71904, 72016, 72784, 73040, 73120, 73552, 92768, 92864, 93008, 120782, 120792, 120802, 120812, 120822, 123200, 123632, 124144, 125264, 130032)

class AllDecimalScripts(unittest.TestCase):
    def test_all_decimal_zero_prefixes_preserve_numbering(self):
        for cp in DECIMAL_ZEROS:
            zero = chr(cp)
            text = '=== CHAPTER '+zero*5000+'2 CONTENT ===\n第二章。\n\n=== CHAPTER 1 CONTENT ===\n第一章。'
            before = sys.get_int_max_str_digits()
            try:
                parts = parse_short_draft(text, 2)
            except Exception as error:
                self.fail('No-exception contract for decimal zero '+hex(cp)+': '+type(error).__name__)
            self.assertEqual(sys.get_int_max_str_digits(), before)
            self.assertEqual(parts, ['第一章。','第二章。'], 'Decimal zero '+hex(cp))

    def test_nonzero_decimal_digits_never_strip_to_invalid_zero(self):
        for cp in DECIMAL_ZEROS:
            one, two = chr(cp+1), chr(cp+2)
            text = '=== CHAPTER '+two+' CONTENT ===\n第二章。\n\n=== CHAPTER '+one+' CONTENT ===\n第一章。'
            self.assertEqual(parse_short_draft(text, 2), ['第一章。','第二章。'], 'Decimal group '+hex(cp))
