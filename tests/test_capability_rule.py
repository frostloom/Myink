"""Actual ORM/service capability-rule scope; deterministic fixtures, no provider mocks."""
import unittest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from myink.models import Character, CharacterState, Event, Fact, Foreshadow, PlotThread, Relation
from myink.validation.service import ValidationService

CAP_DRAFT='他不过金丹期，竟施展出化神期才可动用的"碎星诀"，满天星辉坠落，而他却毫发无伤，无半分反噬。'
CAP_NAMED='林砚不过金丹期，竟施展出化神期才可动用的碎星诀，毫发无伤。'
CAP_ORDER=['炼气','筑基','金丹','元婴','化神','大乘','渡劫']

class CapabilityRuleTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://')
        for m in (Character,CharacterState,Event,Fact,Foreshadow,PlotThread,Relation):m.__table__.create(self.engine)
        self.db=Session(self.engine);self.project=uuid.uuid4();self.foreign=uuid.uuid4();self.actor=uuid.uuid4()
    def tearDown(self):self.db.close();self.engine.dispose()
    def check_case(self,draft=CAP_DRAFT,expected=False,*,rule=None,state=None,characters=None,chapter=8,order=None):
        chars=characters if characters is not None else [dict(id=self.actor,name='林砚',realm_cap='渡劫')]
        for row in chars:self.db.add(Character(project_id=self.project,race='人族',origin='test',personality='谨慎',base_attrs={},**row))
        facts=[dict(content='化神期才可动用碎星诀',category='规则',source_chapter=2,confirm_status='confirmed')] if rule is None else rule
        states=[dict(character_id=self.actor,field='realm',new_value='金丹',chapter_seq=5,source_chapter=5)] if state is None else state
        for row in facts:
            r=dict(row);r.setdefault('project_id',self.project);self.db.add(Fact(**r))
        for row in states:
            r=dict(row);r.setdefault('project_id',self.project);self.db.add(CharacterState(**r))
        self.db.flush();svc=ValidationService(CAP_ORDER if order is None else order)
        fs=[f for f in svc.validate(self.db,project_id=self.project,chapter_seq=chapter,candidates=[],draft=draft).findings if f.conflict_type=='power']
        self.assertEqual(len(fs),int(expected),[(f.severity,f.scope) for f in fs])
        if expected:
            f=fs[0];self.assertEqual((f.severity,f.scope,f.source),('critical','local','L1'))
            self.assertTrue(any(e.chapter==chapter and e.quote and e.quote in draft and '碎星诀' in e.quote for e in f.evidence))
            self.assertTrue(any(e.chapter==2 and e.quote=='化神期才可动用碎星诀' for e in f.evidence))
            self.assertTrue(any(e.chapter==5 and '金丹' in e.quote for e in f.evidence))
            again=[f for f in svc.validate(self.db,project_id=self.project,chapter_seq=chapter,candidates=[],draft=draft).findings if f.conflict_type=='power']
            self.assertEqual(f.conflict_key,again[0].conflict_key)
        return fs

    def test_sample08_original(self):
        self.check_case(expected=True)

    def test_named_actor(self):
        self.check_case(CAP_NAMED,True)

    def test_negated_backlash_is_no_cost(self):
        self.check_case(CAP_NAMED+'没有付出任何代价，未遭反噬。',True)

    def test_repeated_use_deduplicates(self):
        self.check_case(CAP_NAMED+CAP_NAMED,True)

    def test_unrelated_cost_not_exemption(self):
        self.check_case(CAP_NAMED+'旁观者萧炎遭到严重反噬。',True)

    def test_future_high_realm_does_not_override(self):
        self.check_case(expected=True,state=[dict(character_id=self.actor,field='realm',new_value='金丹',chapter_seq=5,source_chapter=5),dict(character_id=self.actor,field='realm',new_value='化神',chapter_seq=9,source_chapter=9)])

    def test_no_rule(self):
        self.check_case(rule=[])

    def test_pending_rule(self):
        self.check_case(rule=[dict(content='化神期才可动用碎星诀',category='规则',source_chapter=2,confirm_status='pending')])

    def test_foreign_rule(self):
        self.check_case(rule=[dict(project_id=self.foreign,content='化神期才可动用碎星诀',category='规则',source_chapter=2,confirm_status='confirmed')])

    def test_future_rule(self):
        self.check_case(rule=[dict(content='化神期才可动用碎星诀',category='规则',source_chapter=9,confirm_status='confirmed')])

    def test_expired_rule(self):
        self.check_case(rule=[dict(content='化神期才可动用碎星诀',category='规则',source_chapter=2,confirm_status='confirmed',valid_to=7)])

    def test_not_yet_rule(self):
        self.check_case(rule=[dict(content='化神期才可动用碎星诀',category='规则',source_chapter=2,confirm_status='confirmed',valid_from=9)])

    def test_rejected_rule(self):
        self.check_case(rule=[dict(content='化神期才可动用碎星诀',category='规则',source_chapter=2,confirm_status='rejected')])

    def test_category_identity_not_rule(self):
        self.check_case(rule=[dict(content='化神期才可动用碎星诀',category='身份',source_chapter=2,confirm_status='confirmed')])

    def test_different_ability(self):
        self.check_case(rule=[dict(content='化神期才可动用镇魂术',category='规则',source_chapter=2,confirm_status='confirmed')])

    def test_unknown_required_realm(self):
        self.check_case(rule=[dict(content='神明期才可动用碎星诀',category='规则',source_chapter=2,confirm_status='confirmed')])

    def test_missing_state(self):
        self.check_case(state=[])

    def test_foreign_state(self):
        self.check_case(state=[dict(project_id=self.foreign,character_id=self.actor,field='realm',new_value='金丹',chapter_seq=5,source_chapter=5)])

    def test_future_state(self):
        self.check_case(state=[dict(character_id=self.actor,field='realm',new_value='金丹',chapter_seq=9,source_chapter=9)])

    def test_expired_state(self):
        self.check_case(state=[dict(character_id=self.actor,field='realm',new_value='金丹',chapter_seq=5,source_chapter=5,valid_to=7)])

    def test_not_yet_state(self):
        self.check_case(state=[dict(character_id=self.actor,field='realm',new_value='金丹',chapter_seq=5,source_chapter=5,valid_from=9)])

    def test_unknown_state(self):
        self.check_case(state=[dict(character_id=self.actor,field='realm',new_value='未知',chapter_seq=5,source_chapter=5)])

    def test_mismatched_draft_rank(self):
        self.check_case(state=[dict(character_id=self.actor,field='realm',new_value='化神',chapter_seq=5,source_chapter=5)])

    def test_latest_upgrade_not_old_rank(self):
        self.check_case(state=[dict(character_id=self.actor,field='realm',new_value='金丹',chapter_seq=4,source_chapter=4),dict(character_id=self.actor,field='realm',new_value='化神',chapter_seq=5,source_chapter=5)])

    def test_qualified_rank(self):
        self.check_case(CAP_DRAFT.replace('金丹','化神'),state=[dict(character_id=self.actor,field='realm',new_value='化神',chapter_seq=5,source_chapter=5)])

    def test_empty_draft(self):
        self.check_case('')

    def test_missing_draft(self):
        self.check_case(None)

    def test_mere_mention(self):
        self.check_case('林砚不过金丹期，听人提起化神期才可动用的碎星诀。')

    def test_negated_use(self):
        self.check_case(CAP_NAMED.replace('竟施展出','没有施展出'))

    def test_conditional_use(self):
        self.check_case(CAP_NAMED.replace('竟施展出','若施展出'))

    def test_planned_use(self):
        self.check_case(CAP_NAMED.replace('竟施展出','打算施展出'))

    def test_recollection(self):
        self.check_case('林砚想起当年：'+CAP_NAMED)

    def test_actual_lifespan_cost(self):
        self.check_case(CAP_NAMED.replace('毫发无伤','他以十年寿元为代价'))

    def test_actual_backlash(self):
        self.check_case(CAP_NAMED.replace('毫发无伤','他遭到严重反噬'))

    def test_ability_prefix_collision(self):
        self.check_case(CAP_NAMED.replace('碎星诀','碎星诀残卷'))

    def test_actor_prefix_collision(self):
        self.check_case(CAP_NAMED.replace('林砚','林砚舟'))

    def test_no_actor(self):
        self.check_case(characters=[])

    def test_ambiguous_pronoun(self):
        self.check_case(characters=[dict(id=self.actor,name='林砚',realm_cap='渡劫'),dict(id=uuid.uuid4(),name='萧炎',realm_cap='渡劫')])

    def test_named_actor_with_others(self):
        self.check_case(CAP_NAMED,True,characters=[dict(id=self.actor,name='林砚',realm_cap='渡劫'),dict(id=uuid.uuid4(),name='萧炎',realm_cap='渡劫')])

    def test_missing_realm_order(self):
        self.check_case(order=[])

    def test_ambiguous_same_chapter(self):
        self.check_case(state=[dict(character_id=self.actor,field='realm',new_value='金丹',chapter_seq=5,source_chapter=5),dict(character_id=self.actor,field='realm',new_value='元婴',chapter_seq=5,source_chapter=5)])

    def test_ambiguous_same_chapter_reversed(self):
        self.check_case(state=[dict(character_id=self.actor,field='realm',new_value='元婴',chapter_seq=5,source_chapter=5),dict(character_id=self.actor,field='realm',new_value='金丹',chapter_seq=5,source_chapter=5)])

    def test_latest_unknown_does_not_revive_old(self):
        self.check_case(state=[dict(character_id=self.actor,field='realm',new_value='金丹',chapter_seq=5,source_chapter=5),dict(character_id=self.actor,field='realm',new_value='未知',chapter_seq=6,source_chapter=6)])

    def test_future_source_old_chapter_state(self):
        self.check_case(state=[dict(character_id=self.actor,field='realm',new_value='金丹',chapter_seq=5,source_chapter=9)])

    def test_other_actor_state_not_mine(self):
        self.check_case(state=[dict(character_id=uuid.uuid4(),field='realm',new_value='金丹',chapter_seq=5,source_chapter=5)])

    def test_cross_actor_action_not_mine(self):
        self.check_case('林砚不过金丹期，萧炎竟施展出化神期才可动用的碎星诀，毫发无伤。',characters=[dict(id=self.actor,name='林砚',realm_cap='渡劫'),dict(id=uuid.uuid4(),name='萧炎',realm_cap='渡劫')])

    def test_other_day_other_ability_cost_not_exemption(self):
        self.check_case(CAP_NAMED+'翌日林砚施展镇魂术，他遭到严重反噬。',True)

    def test_denied_cost_not_exemption(self):
        self.check_case(CAP_NAMED.replace('毫发无伤','他没有遭到严重反噬'),True)

    def test_conditional_cost_not_exemption(self):
        self.check_case(CAP_NAMED.replace('毫发无伤','他若遭到严重反噬'),True)

    def test_recalled_cost_not_exemption(self):
        self.check_case(CAP_NAMED.replace('毫发无伤','他想起当年遭到严重反噬'),True)

    def test_valid_to_inclusive_current(self):
        self.check_case(expected=True,state=[dict(character_id=self.actor,field='realm',new_value='金丹',chapter_seq=5,source_chapter=5,valid_to=8)])

    def test_valid_from_inclusive_current(self):
        self.check_case(expected=True,state=[dict(character_id=self.actor,field='realm',new_value='金丹',chapter_seq=5,source_chapter=5,valid_from=8)])
