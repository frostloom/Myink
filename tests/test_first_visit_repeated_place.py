"""Repeated-place first-visit assertions preserve external mood guards."""
import unittest
import test_first_visit_rule as base

class RepeatedPlaceTests(unittest.TestCase):
    setUp=base.FirstVisitTests.setUp
    tearDown=base.FirstVisitTests.tearDown
    character=base.FirstVisitTests.character
    history=base.FirstVisitTests.history
    findings=base.FirstVisitTests.findings
    conflict=base.FirstVisitTests.conflict

    def place_claim(self,place):
        self.history(text=f'林砚在{place}完成交易')
        self.conflict(f'林砚望着{place}的城墙，心道：这就是{place}，第一次来。')
    def test_buye_repeated(self):self.place_claim('不夜城')
    def test_ruoshui_repeated(self):self.place_claim('若水城')
    def test_weilai_repeated(self):self.place_claim('未来城')
    def test_huiyi_repeated(self):self.place_claim('回忆谷')
    def test_external_negation_stays_quiet(self):
        self.history(text='林砚在不夜城完成交易')
        self.assertEqual(self.findings('林砚望着不夜城的城墙，并未认为这就是不夜城，第一次来。'),[])
    def test_external_condition_stays_quiet(self):
        self.history(text='林砚在若水城完成交易')
        self.assertEqual(self.findings('林砚望着若水城的城墙，若这就是若水城，第一次来。'),[])
    def test_external_plan_stays_quiet(self):
        self.history(text='林砚在未来城完成交易')
        self.assertEqual(self.findings('林砚望着未来城的城墙，打算认为这就是未来城，第一次来。'),[])
    def test_external_recollection_stays_quiet(self):
        self.history(text='林砚在回忆谷完成交易')
        self.assertEqual(self.findings('林砚望着回忆谷的城墙，回忆当年这就是回忆谷，第一次来。'),[])
