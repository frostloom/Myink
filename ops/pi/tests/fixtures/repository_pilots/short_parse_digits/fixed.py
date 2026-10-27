"""Fixed isolated checks of the real short-draft parser's no-exception contract."""
import unittest
import importlib.util
import sys

# A regular myink package may already be installed in the checker image.
# Bind the actual frozen file, rather than resolving a namespace against site-packages.
spec = importlib.util.spec_from_file_location('frozen_short_parse', '/source/src/myink/workflow/short_parse.py')
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)
parse_short_draft = parser.parse_short_draft
render_short_draft = parser.render_short_draft
find_empty_chapters = parser.find_empty_chapters

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
