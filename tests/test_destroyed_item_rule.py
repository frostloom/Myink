"""Actual ORM/service regression for spec samples6/30; no model or validator mocks."""
import unittest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from myink.models import Character, CharacterState, Event, Fact, Foreshadow, PlotThread, Relation
from myink.validation.service import ValidationService

DRAFT='林砚从怀中摸出定水珠，幽蓝光晕流转，映得满室皆蓝。'
REPAIRED='林砚从怀中摸出定水珠，幽蓝光晕流转——那是他以千年寒铁重新淬炼之物。'


class DestroyedItemTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://')
        for model in (Character,CharacterState,Event,Fact,Foreshadow,PlotThread,Relation):model.__table__.create(self.engine)
        self.db=Session(self.engine);self.project=uuid.uuid4();self.foreign=uuid.uuid4()
        self.service=ValidationService(['炼气','筑基','金丹'])

    def tearDown(self):
        self.db.close();self.engine.dispose()

    def event(self,text='定水珠被天劫劈碎',chapter=10,foreign=False):
        self.db.add(Event(project_id=self.foreign if foreign else self.project,summary=text,
                          source_chapter=chapter,participants=[]));self.db.flush()

    def repair(self,text='定水珠以千年寒铁重铸成功',chapter=11,status='confirmed',foreign=False,**kw):
        self.db.add(Fact(project_id=self.foreign if foreign else self.project,content=text,
                         source_chapter=chapter,confirm_status=status,**kw));self.db.flush()

    def findings(self,draft=DRAFT,chapter=11):
        report=self.service.validate(self.db,project_id=self.project,chapter_seq=chapter,candidates=[],draft=draft)
        return [f for f in report.findings if f.conflict_type=='item_rule']

    def expect_conflict(self,draft=DRAFT,chapter=11):
        fs=self.findings(draft,chapter)
        self.assertEqual(len(fs),1)
        f=fs[0];self.assertEqual((f.severity,f.scope,f.source),('critical','local','L1'))
        self.assertTrue(any(e.chapter==chapter and e.quote in draft and '定水珠' in e.quote for e in f.evidence))
        self.assertTrue(any(e.chapter==10 and '定水珠被天劫劈碎' in e.quote for e in f.evidence))
        return f

    def test_sample6_real_service_detects_reappearance(self):
        self.event();self.expect_conflict()

    def test_sample30_confirmed_reforging_is_legal(self):
        self.event();self.repair();self.assertEqual(self.findings(REPAIRED),[])

    def test_missing_draft_never_reports_history_alone(self):
        self.event();self.assertEqual(self.findings(None),[])

    def test_empty_draft_is_quiet(self):
        self.event();self.assertEqual(self.findings(''),[])

    def test_foreign_destruction_is_ignored(self):
        self.event(foreign=True);self.assertEqual(self.findings(),[])

    def test_future_destruction_is_ignored(self):
        self.event(chapter=12);self.assertEqual(self.findings(),[])

    def test_current_destruction_is_not_history(self):
        self.event(chapter=11);self.assertEqual(self.findings(),[])

    def test_mention_is_not_actual_use(self):
        self.event();self.assertEqual(self.findings('林砚提起定水珠，叹息那场天劫。'),[])

    def test_negated_use_is_not_reappearance(self):
        self.event();self.assertEqual(self.findings('林砚没有取出定水珠，只握紧空空的衣袋。'),[])

    def test_recollection_is_not_current_use(self):
        self.event();self.assertEqual(self.findings('林砚想起当年从怀中摸出定水珠的情形。'),[])

    def test_intended_repair_is_not_confirmed_repair(self):
        self.event();self.repair(text='定水珠计划以千年寒铁重铸');self.expect_conflict()

    def test_negated_repair_does_not_exempt(self):
        self.event();self.repair(text='定水珠并未修复，重铸失败');self.expect_conflict()

    def test_pending_repair_does_not_exempt(self):
        self.event();self.repair(status='pending');self.expect_conflict()

    def test_rejected_repair_does_not_exempt(self):
        self.event();self.repair(status='rejected');self.expect_conflict()

    def test_expired_repair_does_not_exempt(self):
        self.event();self.repair(status='expired');self.expect_conflict()

    def test_foreign_repair_does_not_exempt(self):
        self.event();self.repair(foreign=True);self.expect_conflict()

    def test_other_item_repair_does_not_exempt(self):
        self.event();self.repair(text='镇魂铃以千年寒铁重铸成功');self.expect_conflict()

    def test_future_repair_does_not_exempt(self):
        self.event();self.repair(chapter=12);self.expect_conflict()

    def test_repair_before_destruction_does_not_exempt(self):
        self.event();self.repair(chapter=9);self.expect_conflict()

    def test_not_yet_effective_repair_does_not_exempt(self):
        self.event();self.repair(valid_from=12);self.expect_conflict()

    def test_closed_repair_does_not_exempt(self):
        self.event();self.repair(valid_to=10);self.expect_conflict()

    def test_duplicate_destruction_and_use_has_stable_single_finding(self):
        self.event(chapter=9);self.event()
        a=self.expect_conflict(DRAFT+DRAFT);b=self.expect_conflict(DRAFT)
        self.assertEqual(a.conflict_key,b.conflict_key)

    def test_draft_repair_claim_alone_does_not_exempt(self):
        self.event();self.expect_conflict(REPAIRED)

    def test_later_destruction_invalidates_older_repair(self):
        self.event(chapter=8);self.repair(chapter=9);self.event()
        self.expect_conflict()

    def test_fragments_are_not_intact_item_reappearance(self):
        self.event();self.assertEqual(self.findings('林砚从怀中摸出定水珠的残片，碎屑已无灵光。'),[])

    def test_other_item_use_is_not_reappearance(self):
        self.event();self.assertEqual(self.findings('林砚从怀中摸出镇魂铃，铃声清越。'),[])

    def test_negated_destruction_is_not_history(self):
        self.event(text='定水珠未被天劫劈碎');self.assertEqual(self.findings(),[])

    def test_hypothetical_destruction_is_not_history(self):
        self.event(text='若定水珠被天劫劈碎，林砚便会失去庇护');self.assertEqual(self.findings(),[])

    def test_repair_of_other_clause_does_not_exempt(self):
        self.event();self.repair(text='定水珠尚未修复，玄火珠已重铸成功');self.expect_conflict()

    def test_overlapping_item_name_repair_does_not_exempt(self):
        self.event();self.repair(text='小定水珠以千年寒铁重铸成功');self.expect_conflict()

    def test_completed_reforging_without_success_word_is_legal(self):
        self.event();self.repair(text='定水珠以千年寒铁重铸');self.assertEqual(self.findings(REPAIRED),[])

    def test_confirmed_explicit_repair_is_legal(self):
        self.event();self.repair(text='定水珠已修复');self.assertEqual(self.findings(),[])

    def test_confirmed_completed_refining_is_legal(self):
        self.event();self.repair(text='定水珠重新淬炼完成');self.assertEqual(self.findings(),[])

    def test_suffix_item_name_repair_does_not_exempt(self):
        self.event();self.repair(text='定水珠王以千年寒铁重铸成功');self.expect_conflict()

    def test_same_clause_other_item_use_is_not_reappearance(self):
        self.event();self.assertEqual(self.findings('林砚取出镇魂铃并谈起定水珠的往事。'),[])

    def test_intended_use_is_not_reappearance(self):
        self.event();self.assertEqual(self.findings('林砚打算取出定水珠。'),[])

    def test_current_evidence_quotes_use_not_prior_mention(self):
        self.event();draft='林砚想起定水珠。林砚从怀中摸出定水珠。'
        fs=self.findings(draft);self.assertEqual(len(fs),1)
        quotes=[e.quote for e in fs[0].evidence if e.chapter==11]
        self.assertTrue(any('摸出定水珠' in q and q in draft for q in quotes))

    def test_suffix_item_name_use_is_not_reappearance(self):
        self.event();self.assertEqual(self.findings('林砚从怀中摸出定水珠王，光华闪动。'),[])

    def test_generic_second_item_is_detected(self):
        self.event(text='玄火珠被雷霆击碎');draft='沈沧澜祭出玄火珠。'
        fs=self.findings(draft);self.assertEqual(len(fs),1)
        self.assertEqual((fs[0].severity,fs[0].scope),('critical','local'))
        self.assertTrue(any(e.chapter==11 and e.quote in draft and '玄火珠' in e.quote for e in fs[0].evidence))

    def test_plain_no_use_is_not_current_use(self):
        self.event();self.assertEqual(self.findings('林砚不使用定水珠。'),[])

    def test_cannot_use_is_not_current_use(self):
        self.event();self.assertEqual(self.findings('林砚不能取出定水珠。'),[])

    def test_no_longer_use_is_not_current_use(self):
        self.event();self.assertEqual(self.findings('林砚不再催动定水珠。'),[])

    def test_past_use_is_not_current_use(self):
        self.event();self.assertEqual(self.findings('林砚曾经使用定水珠。'),[])

    def test_already_reforged_is_legal(self):
        self.event();self.repair(text='定水珠已重铸成功');self.assertEqual(self.findings(),[])

    def test_explicit_already_reforged_is_legal(self):
        self.event();self.repair(text='定水珠已经重铸成功');self.assertEqual(self.findings(),[])

    def test_complement_like_item_suffix_is_distinct(self):
        self.event();self.assertEqual(self.findings('林砚取出定水珠来福，灵光闪动。'),[])

    def test_second_complement_like_suffix_is_distinct(self):
        self.event();self.assertEqual(self.findings('林砚取出定水珠再生，灵光闪动。'),[])

    def test_long_clause_evidence_includes_actual_use(self):
        self.event();draft='甲'*81+'林砚取出定水珠。'
        fs=self.findings(draft);self.assertEqual(len(fs),1)
        current=[e for e in fs[0].evidence if e.chapter==11]
        self.assertTrue(any('取出定水珠' in e.quote and e.quote in draft for e in current))
