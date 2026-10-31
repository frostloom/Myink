import unittest
from myink.models import Character
import test_destroyed_item_rule as base


class ActorNameUseTests(unittest.TestCase):
    setUp=base.DestroyedItemTests.setUp
    tearDown=base.DestroyedItemTests.tearDown
    event=base.DestroyedItemTests.event
    findings=base.DestroyedItemTests.findings
    def actor(self,name):
        self.db.add(Character(project_id=self.project,name=name,realm_cap='金丹'));self.db.flush()
    def positive(self,name):
        self.actor(name);self.event();draft=f'{name}使用定水珠。';fs=self.findings(draft)
        self.assertEqual(len(fs),1)
        self.assertTrue(any(e.chapter==11 and e.quote in draft for e in fs[0].evidence))
    def test_buqi_actor(self):self.positive('不齐')
    def test_buhui_actor(self):self.positive('不悔')
    def test_ruoshui_actor(self):self.positive('若水')
    def test_weiyang_actor(self):self.positive('未央')
    def test_named_actor_negated_action_still_quiet(self):
        self.actor('不齐');self.event();self.assertEqual(self.findings('不齐不使用定水珠。'),[])
    def test_named_actor_conditional_action_still_quiet(self):
        self.actor('若水');self.event();self.assertEqual(self.findings('若水若使用定水珠。'),[])
    def test_unregistered_text_does_not_exempt_guard(self):
        self.event();self.assertEqual(self.findings('不齐使用定水珠。'),[])
    def test_other_name_mention_does_not_remove_guard(self):
        self.actor('不齐');self.event();self.assertEqual(self.findings('林砚不使用定水珠而想起不齐。'),[])
    def test_named_actor_planned_action_still_quiet(self):
        self.actor('不齐');self.event();self.assertEqual(self.findings('不齐打算使用定水珠。'),[])
    def test_named_actor_past_action_still_quiet(self):
        self.actor('不齐');self.event();self.assertEqual(self.findings('不齐曾经使用定水珠。'),[])
    def test_prefix_collision_does_not_exempt_guard(self):
        self.actor('不');self.event();self.assertEqual(self.findings('不齐使用定水珠。'),[])
    def test_combined_item_actor_names(self):
        self.actor('若水');self.event(text='不灭珠被天劫劈碎');fs=self.findings('若水使用不灭珠。');self.assertEqual(len(fs),1)
