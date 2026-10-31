"""Registered entity words are names, not negation or modality markers."""
import unittest
import test_first_visit_rule as base


class EntityNameTests(unittest.TestCase):
    setUp=base.FirstVisitTests.setUp
    tearDown=base.FirstVisitTests.tearDown
    character=base.FirstVisitTests.character
    history=base.FirstVisitTests.history
    findings=base.FirstVisitTests.findings
    conflict=base.FirstVisitTests.conflict

    def actor_case(self,name,embedded=False):
        self.actor.name=name;self.db.flush();self.history(text=f'{name}在北境城完成交易')
        self.conflict(base.DRAFT.replace('林砚',name) if embedded else f'{name}第一次来到北境城。')

    def place_case(self,place,embedded=False):
        self.history(text=f'林砚在{place}完成交易')
        self.conflict(base.DRAFT.replace('北境城',place) if embedded else f'林砚第一次来到{place}。')

    def test_actor_buqi_direct(self):self.actor_case('不弃')
    def test_actor_weiyang_direct(self):self.actor_case('未央')
    def test_actor_ruoshui_direct(self):self.actor_case('若水')
    def test_actor_buqi_embedded(self):self.actor_case('不弃',True)
    def test_actor_weiyang_embedded(self):self.actor_case('未央',True)
    def test_actor_ruoshui_embedded(self):self.actor_case('若水',True)
    def test_place_buye_direct(self):self.place_case('不夜城')
    def test_place_ruoshui_direct(self):self.place_case('若水城')
    def test_place_weilai_direct(self):self.place_case('未来城')
    def test_place_huiyi_direct(self):self.place_case('回忆谷')
    def test_place_buye_embedded(self):self.place_case('不夜城',True)
    def test_place_ruoshui_embedded(self):self.place_case('若水城',True)
    def test_place_weilai_embedded(self):self.place_case('未来城',True)
    def test_place_huiyi_embedded(self):self.place_case('回忆谷',True)

    def test_actor_actual_negated_claim_still_quiet(self):
        self.actor.name='不弃';self.db.flush();self.history(text='不弃在北境城完成交易')
        self.assertEqual(self.findings('不弃不是第一次来到北境城。'),[])

    def test_actor_actual_planned_claim_still_quiet(self):
        self.actor.name='未央';self.db.flush();self.history(text='未央在北境城完成交易')
        self.assertEqual(self.findings('未央打算第一次来到北境城。'),[])

    def test_place_actual_hypothesis_still_quiet(self):
        self.history(text='林砚在若水城完成交易')
        self.assertEqual(self.findings('若林砚第一次来到若水城。'),[])

    def test_actor_actual_negated_history_still_quiet(self):
        self.actor.name='不弃';self.db.flush();self.history(text='不弃没有在北境城完成交易')
        self.assertEqual(self.findings('不弃第一次来到北境城。'),[])

    def test_actor_actual_conditional_history_still_quiet(self):
        self.actor.name='不弃';self.db.flush();self.history(text='如果天晴，不弃在北境城完成交易。')
        self.assertEqual(self.findings('不弃第一次来到北境城。'),[])

    def test_actor_actual_embedded_negation_still_quiet(self):
        self.actor.name='不弃';self.db.flush();self.history(text='不弃在北境城完成交易')
        self.assertEqual(self.findings('不弃并未认为这就是北境城，第一次来。'),[])

    def test_single_character_actor_real_embedded_negation(self):
        self.actor.name='未';self.db.flush();self.history(text='未在北境城完成交易')
        self.assertEqual(self.findings('未抬眸，并未认为这就是北境城，第一次来。'),[])

    def test_single_character_actor_real_embedded_condition(self):
        self.actor.name='若';self.db.flush();self.history(text='若在北境城完成交易')
        self.assertEqual(self.findings('若抬眸，心道：若这就是北境城，第一次来。'),[])

    def test_single_character_actor_negated_explanation(self):
        self.actor.name='未';self.db.flush();self.history(text='未在北境城完成交易')
        self.conflict('未未失忆。未第一次来到北境城。')

    def test_hedged_history_prefix_does_not_prove_visit(self):
        self.history(text='几乎可以认为，林砚在北境城完成交易。')
        self.assertEqual(self.findings('林砚第一次来到北境城。'),[])

    def test_near_miss_history_prefix_does_not_prove_visit(self):
        self.history(text='差点可以断言，林砚在北境城完成交易。')
        self.assertEqual(self.findings('林砚第一次来到北境城。'),[])
