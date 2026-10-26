"""Real SQLite ORM/service checks for explicit first-visit contradictions, samples5/29."""
import unittest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from myink.models import Character, CharacterState, Event, Fact, Foreshadow, PlotThread, Relation
from myink.validation.service import ValidationService

DRAFT='林砚抬眸，望着眼前高耸的城墙，心道：这就是北境城，第一次来。'
REVISIT='林砚望着北境城城墙，心道：故地重游，上一次来还是三年前。'


class FirstVisitTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://')
        for model in (Character,CharacterState,Event,Fact,Foreshadow,PlotThread,Relation):model.__table__.create(self.engine)
        self.db=Session(self.engine);self.project=uuid.uuid4();self.foreign=uuid.uuid4()
        self.actor=self.character()
        self.service=ValidationService(['炼气','筑基','金丹'])

    def tearDown(self):
        self.db.close();self.engine.dispose()

    def character(self,name='林砚',foreign=False):
        value=Character(project_id=self.foreign if foreign else self.project,name=name,realm_cap='金丹')
        self.db.add(value);self.db.flush();return value

    def history(self,text='林砚在北境城完成交易',chapter=8,foreign=False,participants=None):
        self.db.add(Event(project_id=self.foreign if foreign else self.project,summary=text,
                          source_chapter=chapter,participants=[] if participants is None else participants));self.db.flush()

    def findings(self,draft=DRAFT,chapter=12):
        report=self.service.validate(self.db,project_id=self.project,chapter_seq=chapter,candidates=[],draft=draft)
        return [f for f in report.findings if f.conflict_type=='character' and f.source=='L1']

    def conflict(self,draft=DRAFT,chapter=12):
        fs=self.findings(draft,chapter);self.assertEqual(len(fs),1)
        self.assertEqual((fs[0].severity,fs[0].scope,fs[0].source),('major','local','L1'))
        self.assertTrue(any(e.chapter==chapter and e.quote in draft and '第一次' in e.quote for e in fs[0].evidence))
        return fs[0]

    def test_spec5_real_service(self):
        self.history();f=self.conflict();self.assertTrue(any(e.chapter==8 and e.quote=='林砚在北境城完成交易' for e in f.evidence))

    def test_spec29_revisit_legal(self):
        self.history();self.assertEqual(self.findings(REVISIT),[])

    def test_direct_first_arrival(self):
        self.history();self.conflict('林砚第一次来到北境城。')

    def test_no_history(self):
        self.assertEqual(self.findings(),[])

    def test_empty_draft(self):
        self.history();self.assertEqual(self.findings(''),[])

    def test_no_draft(self):
        self.history();self.assertEqual(self.findings(None),[])

    def test_foreign_event(self):
        self.history(foreign=True);self.assertEqual(self.findings(),[])

    def test_current_event(self):
        self.history(chapter=12);self.assertEqual(self.findings(),[])

    def test_future_event(self):
        self.history(chapter=13);self.assertEqual(self.findings(),[])

    def test_other_actor_history(self):
        self.character('顾行');self.history(text='顾行在北境城完成交易');self.assertEqual(self.findings(),[])

    def test_other_location(self):
        self.history(text='林砚在南陵城完成交易');self.assertEqual(self.findings(),[])

    def test_event_actor_prefix_collision(self):
        self.history(text='小林砚在北境城完成交易');self.assertEqual(self.findings(),[])

    def test_event_actor_suffix_collision(self):
        self.history(text='林砚王在北境城完成交易');self.assertEqual(self.findings(),[])

    def test_event_location_prefix_collision(self):
        self.history(text='林砚在小北境城完成交易');self.assertEqual(self.findings(),[])

    def test_event_location_suffix_collision(self):
        self.history(text='林砚在北境城外完成交易');self.assertEqual(self.findings(),[])

    def test_draft_actor_prefix_collision(self):
        self.history();self.assertEqual(self.findings('小林砚第一次来到北境城。'),[])

    def test_draft_actor_suffix_collision(self):
        self.history();self.assertEqual(self.findings('林砚王第一次来到北境城。'),[])

    def test_draft_location_suffix_collision(self):
        self.history();self.assertEqual(self.findings('林砚第一次来到北境城外。'),[])

    def test_draft_location_prefix_collision(self):
        self.history();self.assertEqual(self.findings('林砚第一次来到小北境城。'),[])

    def test_negated_event(self):
        self.history(text='林砚未在北境城完成交易');self.assertEqual(self.findings(),[])

    def test_negated_completion_event(self):
        self.history(text='林砚在北境城没有完成交易');self.assertEqual(self.findings(),[])

    def test_hypothetical_event(self):
        self.history(text='若林砚在北境城完成交易');self.assertEqual(self.findings(),[])

    def test_planned_event(self):
        self.history(text='林砚计划在北境城完成交易');self.assertEqual(self.findings(),[])

    def test_negated_first_visit(self):
        self.history();self.assertEqual(self.findings('林砚不是第一次来到北境城。'),[])

    def test_conditional_first_visit(self):
        self.history();self.assertEqual(self.findings('若林砚第一次来到北境城。'),[])

    def test_planned_first_visit(self):
        self.history();self.assertEqual(self.findings('林砚打算第一次来到北境城。'),[])

    def test_recollection_first_visit(self):
        self.history();self.assertEqual(self.findings('林砚想起当年第一次来到北境城。'),[])

    def test_first_transaction_is_not_first_visit(self):
        self.history();self.assertEqual(self.findings('林砚在北境城第一次完成交易。'),[])

    def test_mere_location_mention(self):
        self.history();self.assertEqual(self.findings('林砚望着北境城城墙，默默无言。'),[])

    def test_explicit_memory_loss(self):
        self.history();self.assertEqual(self.findings('林砚已经失忆。'+DRAFT),[])

    def test_explicit_revisit_explanation(self):
        self.history();self.assertEqual(self.findings('林砚旧地重游。'+DRAFT),[])

    def test_foreign_paragraph_explanation_does_not_exempt(self):
        self.history();self.conflict('林砚已经失忆。\n'+DRAFT)

    def test_mixed_actor_ambiguous_claim(self):
        self.character('顾行');self.history();self.assertEqual(self.findings('林砚看着顾行说道：这就是北境城，第一次来。'),[])

    def test_foreign_character_not_attributed(self):
        self.db.delete(self.actor);self.db.flush();self.character(foreign=True);self.history();self.assertEqual(self.findings(),[])

    def test_participant_mismatch(self):
        other=self.character('顾行');self.history(participants=[str(other.id)]);self.assertEqual(self.findings(),[])

    def test_participant_match(self):
        self.history(participants=[str(self.actor.id)]);self.conflict()

    def test_generic_actor_and_location(self):
        self.character('顾行');self.history(text='顾行在南陵城完成交易');f=self.conflict('顾行第一次来到南陵城。');self.assertTrue(any('顾行' in e.quote for e in f.evidence))

    def test_duplicate_history_stable_single_finding(self):
        self.history();self.history();a=self.conflict();b=self.conflict();self.assertEqual(a.conflict_key,b.conflict_key)

    def test_latest_history_evidence(self):
        self.history();self.history(text='林砚在北境城完成交易。',chapter=9);f=self.conflict();self.assertTrue(any(e.chapter==9 and e.quote=='林砚在北境城完成交易。' for e in f.evidence))

    def test_long_quote_contains_actor_and_assertion(self):
        self.history();draft='林砚'+'抬眸'*50+'，这就是北境城，第一次来。';f=self.conflict(draft);self.assertTrue(any(e.chapter==12 and '林砚' in e.quote and '第一次来' in e.quote and e.quote in draft for e in f.evidence))

    def test_previous_destroyed_item_check_preserved(self):
        self.history(text='定水珠被天劫劈碎');r=self.service.validate(self.db,project_id=self.project,chapter_seq=12,candidates=[],draft='林砚取出定水珠。');self.assertTrue(any(f.conflict_type=='item_rule' and f.severity=='critical' for f in r.findings))

    def test_embedded_actor_prefix_collision(self):
        self.history();self.assertEqual(self.findings(DRAFT.replace('林砚','小林砚')),[])

    def test_embedded_actor_suffix_collision(self):
        self.history();self.assertEqual(self.findings(DRAFT.replace('林砚','林砚王')),[])

    def test_embedded_recollection_is_not_claim(self):
        self.history();self.assertEqual(self.findings('林砚想起当年：这就是北境城，第一次来。'),[])

    def test_embedded_hypothesis_is_not_claim(self):
        self.history();self.assertEqual(self.findings('林砚心想，若这就是北境城，第一次来。'),[])

    def test_embedded_plan_is_not_claim(self):
        self.history();self.assertEqual(self.findings('林砚打算自称这就是北境城，第一次来。'),[])

    def test_embedded_negation_is_not_claim(self):
        self.history();self.assertEqual(self.findings('林砚并未认为这就是北境城，第一次来。'),[])

    def test_other_actor_memory_loss_does_not_exempt(self):
        self.character('顾行');self.history();self.conflict('顾行已经失忆。'+DRAFT)

    def test_negated_memory_loss_does_not_exempt(self):
        self.history();self.conflict('林砚并未失忆。'+DRAFT)

    def test_uncertain_memory_loss_does_not_exempt(self):
        self.history();self.conflict('林砚也许已经失忆。'+DRAFT)

    def test_planned_memory_loss_does_not_exempt(self):
        self.history();self.conflict('林砚打算假装失忆。'+DRAFT)

    def test_two_actor_location_pairs_have_distinct_stable_keys(self):
        self.character('顾行');self.history();self.history(text='顾行在南陵城完成交易',chapter=9)
        draft='林砚第一次来到北境城。顾行第一次来到南陵城。'
        fs=self.findings(draft);self.assertEqual(len(fs),2)
        keys={f.conflict_key for f in fs};self.assertEqual(len(keys),2)
        self.assertEqual(keys,{f.conflict_key for f in self.findings(draft)})

    def test_registered_short_actor_does_not_hide_long_direct_claim(self):
        self.character('林砚王');self.history(text='林砚王在北境城完成交易')
        self.conflict('林砚王第一次来到北境城。')

    def test_registered_short_actor_does_not_hide_long_embedded_claim(self):
        self.character('林砚王');self.history(text='林砚王在北境城完成交易')
        self.conflict(DRAFT.replace('林砚','林砚王'))

    def test_conditional_history_prefix_across_comma_is_not_fact(self):
        self.history(text='如果天晴，林砚在北境城完成交易。');self.assertEqual(self.findings('林砚第一次来到北境城。'),[])

    def test_conditional_history_prefix_across_semicolon_is_not_fact(self):
        self.history(text='若天晴；林砚在北境城完成交易。');self.assertEqual(self.findings(),[])

    def test_planned_history_prefix_across_comma_is_not_fact(self):
        self.history(text='计划明天，林砚在北境城完成交易。');self.assertEqual(self.findings(),[])

    def test_previous_conditional_sentence_does_not_hide_affirmative_history(self):
        self.history(text='如果天晴就启程。林砚在北境城完成交易。');self.conflict()
