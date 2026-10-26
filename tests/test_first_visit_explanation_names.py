import unittest
import test_first_visit_rule as base

class ExplanationNameTests(unittest.TestCase):
    setUp=base.FirstVisitTests.setUp
    tearDown=base.FirstVisitTests.tearDown
    character=base.FirstVisitTests.character
    history=base.FirstVisitTests.history
    findings=base.FirstVisitTests.findings
    conflict=base.FirstVisitTests.conflict

    def explained(self,name,explanation):
        self.actor.name=name;self.db.flush();self.history(text=f'{name}在北境城完成交易')
        self.assertEqual(self.findings(f'{name}{explanation}。{name}第一次来到北境城。'),[])
    def test_buceng_confirmed_amnesia(self):self.explained('不曾','已失忆')
    def test_weiceng_confirmed_amnesia(self):self.explained('未曾','已失忆')
    def test_bingzhou_confirmed_amnesia(self):self.explained('并州','已失忆')
    def test_buceng_confirmed_revisit(self):self.explained('不曾','旧地重游')
    def test_weiceng_confirmed_revisit(self):self.explained('未曾','旧地重游')
    def test_bingzhou_confirmed_revisit(self):self.explained('并州','旧地重游')
    def test_real_negated_explanation_does_not_exempt(self):
        self.actor.name='不曾';self.db.flush();self.history(text='不曾在北境城完成交易')
        self.conflict('不曾并未失忆。不曾第一次来到北境城。')
    def test_real_uncertain_explanation_does_not_exempt(self):
        self.actor.name='并州';self.db.flush();self.history(text='并州在北境城完成交易')
        self.conflict('并州也许失忆。并州第一次来到北境城。')
    def test_similar_actor_explanation_does_not_exempt(self):
        self.actor.name='未曾';self.db.flush();self.character('未曾王');self.history(text='未曾在北境城完成交易')
        self.conflict('未曾王已失忆。未曾第一次来到北境城。')
    def test_other_actor_explanation_does_not_exempt(self):
        self.actor.name='不曾';self.db.flush();self.character('林砚');self.history(text='不曾在北境城完成交易')
        self.conflict('林砚已失忆。不曾第一次来到北境城。')
