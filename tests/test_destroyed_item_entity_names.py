import unittest
from myink.models import Character
import test_destroyed_item_rule as base


class ItemNameUseTests(unittest.TestCase):
    setUp=base.DestroyedItemTests.setUp
    tearDown=base.DestroyedItemTests.tearDown
    event=base.DestroyedItemTests.event
    repair=base.DestroyedItemTests.repair
    findings=base.DestroyedItemTests.findings
    def positive(self,item):
        self.event(text=f'{item}被天劫劈碎')
        draft=f'林砚使用{item}。'
        fs=self.findings(draft);self.assertEqual(len(fs),1)
        self.assertEqual((fs[0].severity,fs[0].source),('critical','L1'))
        self.assertTrue(any(e.chapter==11 and e.quote in draft and item in e.quote for e in fs[0].evidence))
    def test_bumie_item_use(self):self.positive('不灭珠')
    def test_buxiu_item_use(self):self.positive('不朽剑')
    def test_bubai_item_use(self):self.positive('不败铃')
    def test_actual_negation_remains_quiet(self):
        self.event(text='不灭珠被天劫劈碎');self.assertEqual(self.findings('林砚不使用不灭珠。'),[])
    def test_actual_condition_remains_quiet(self):
        self.event(text='不灭珠被天劫劈碎');self.assertEqual(self.findings('若林砚使用不灭珠。'),[])
    def test_actual_plan_remains_quiet(self):
        self.event(text='不灭珠被天劫劈碎');self.assertEqual(self.findings('林砚打算使用不灭珠。'),[])
    def test_actual_memory_remains_quiet(self):
        self.event(text='不灭珠被天劫劈碎');self.assertEqual(self.findings('林砚回忆使用不灭珠。'),[])
    def test_longer_item_not_selected(self):
        self.event(text='不灭珠被天劫劈碎');self.assertEqual(self.findings('林砚使用不灭珠王。'),[])
    def test_other_clause_still_detected(self):
        self.event(text='不灭珠被天劫劈碎');fs=self.findings('林砚不使用不灭珠。林砚使用不灭珠。');self.assertEqual(len(fs),1)
    def test_confirmed_repair_still_exempts(self):
        self.event(text='不灭珠被天劫劈碎');self.repair(text='不灭珠已重铸成功');self.assertEqual(self.findings('林砚使用不灭珠。'),[])

    def test_long_prior_sentence_does_not_shift_evidence(self):
        self.event(text='不灭珠被天劫劈碎');draft='晨光照着长街'*20+'。林砚使用不灭珠。';fs=self.findings(draft)
        self.assertEqual(len(fs),1);self.assertTrue(any(e.chapter==11 and '使用不灭珠' in e.quote and e.quote in draft for e in fs[0].evidence))
    def test_earlier_longer_item_prefix_does_not_hide_use(self):
        self.event(text='不灭珠被天劫劈碎');draft='林砚使用不灭珠王。林砚使用不灭珠。';fs=self.findings(draft)
        self.assertEqual(len(fs),1);self.assertTrue(any(e.chapter==11 and e.quote in draft and '使用不灭珠' in e.quote for e in fs[0].evidence))
    def test_same_clause_fragment_guard_kept_on_original_text(self):
        self.event();self.assertEqual(self.findings('定水珠的碎片旁林砚使用定水珠。'),[])
