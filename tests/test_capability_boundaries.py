import unittest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from myink.models import Character,CharacterState,Event,Fact,Foreshadow,PlotThread,Relation
from myink.validation.service import ValidationService

class CapabilityHoldoutTests(unittest.TestCase):
    def check_bound(self,name,ability,current,required,order):
        engine=create_engine('sqlite://')
        for m in (Character,CharacterState,Event,Fact,Foreshadow,PlotThread,Relation):m.__table__.create(engine)
        try:
            with Session(engine) as db:
                project=uuid.uuid4();actor=uuid.uuid4();rule=required+'期才可动用'+ability
                db.add(Character(id=actor,project_id=project,name=name,realm_cap=order[-1],base_attrs={}))
                db.add(CharacterState(project_id=project,character_id=actor,field='realm',new_value=current,chapter_seq=4,source_chapter=4))
                db.add(Fact(project_id=project,content=rule,category='规则',confirm_status='confirmed',source_chapter=1));db.flush()
                draft=name+'不过'+current+'期，竟施展出'+required+'期才可动用的'+ability+'，毫发无伤。'
                fs=[f for f in ValidationService(order).validate(db,project_id=project,chapter_seq=7,candidates=[],draft=draft).findings if f.conflict_type=='power']
                self.assertEqual(len(fs),1);f=fs[0];self.assertEqual((f.severity,f.scope,f.source),('critical','local','L1'))
                self.assertTrue(any(e.chapter==7 and e.quote and e.quote in draft for e in f.evidence))
                self.assertTrue(any(e.chapter==1 and e.quote==rule for e in f.evidence))
                self.assertTrue(any(e.chapter==4 and current in e.quote for e in f.evidence))
        finally:engine.dispose()
    def test_different_registered_actor_and_ability(self):
        self.check_bound('萧炎','镇魂术','筑基','元婴',['炼气','筑基','金丹','元婴','化神'])
    def test_registered_actor_name_is_not_negation(self):
        self.check_bound('不齐','碎星诀','金丹','化神',['炼气','筑基','金丹','元婴','化神'])
    def test_ability_name_is_not_negation(self):
        self.check_bound('林砚','不灭诀','金丹','化神',['炼气','筑基','金丹','元婴','化神'])


class IndependentCapabilityCases(unittest.TestCase):
    def run_case(self,name='若尘',ability='无相诀',rank='筑基',required='紫府',*,others=False,cost=False,negated_rule=False):
        engine=create_engine('sqlite://')
        for model in (Character,CharacterState,Event,Fact,Foreshadow,PlotThread,Relation):model.__table__.create(engine)
        try:
            with Session(engine) as db:
                project=uuid.uuid4();actor=uuid.uuid4();rule=required+'期才可动用'+ability
                db.add(Character(id=actor,project_id=project,name=name,realm_cap='化神',base_attrs={}))
                if others:db.add(Character(project_id=project,name='陆沉',realm_cap='化神',base_attrs={}))
                db.add(CharacterState(project_id=project,character_id=actor,field='realm',new_value=rank,chapter_seq=6,source_chapter=6))
                db.add(Fact(project_id=project,content=('并非' if negated_rule else '')+rule,category='规则',confirm_status='confirmed',source_chapter=2));db.flush()
                tail='他遭到严重反噬' if cost else ('旁观者陆沉遭到严重反噬' if others else '毫发无伤')
                draft=name+'不过'+rank+'期，竟施展出'+required+'期才可动用的'+ability+'，'+tail+'。'
                fs=[f for f in ValidationService(['炼气','筑基','金丹','紫府','化神']).validate(db,project_id=project,chapter_seq=9,candidates=[],draft=draft).findings if f.conflict_type=='power']
                expected=not cost and not negated_rule;self.assertEqual(len(fs),int(expected))
                if expected:
                    f=fs[0];self.assertEqual((f.severity,f.scope,f.source),('critical','local','L1'))
                    self.assertTrue(any(e.chapter==9 and e.quote and e.quote in draft for e in f.evidence))
                    self.assertTrue(any(e.chapter==2 and e.quote==rule for e in f.evidence))
                    self.assertTrue(any(e.chapter==6 and rank in e.quote for e in f.evidence))
        finally:engine.dispose()
    def test_unseen_actor_rank_and_ability(self):self.run_case(name='周玄',ability='照海术')
    def test_registered_conditional_character_name(self):self.run_case(name='若尘',ability='玄照诀')
    def test_negative_character_ability_name(self):self.run_case(name='未明',ability='无相诀')
    def test_other_actors_cost_in_same_sentence_does_not_exempt(self):self.run_case(others=True)
    def test_negated_free_prose_is_not_an_active_rule(self):self.run_case(negated_rule=True)
    def test_named_subject_local_pronoun_cost_with_two_characters(self):self.run_case(others=True,cost=True)

class CapabilityStateBoundaryTests(unittest.TestCase):
    def check_boundary(self,*,injury=False,duplicate=False):
        engine=create_engine('sqlite://')
        for model in (Character,CharacterState,Event,Fact,Foreshadow,PlotThread,Relation):model.__table__.create(engine)
        try:
            with Session(engine) as db:
                project=uuid.uuid4();actor=uuid.uuid4();rule='化神期才可动用碎星诀'
                db.add(Character(id=actor,project_id=project,name='林砚',realm_cap='渡劫',base_attrs={}))
                if duplicate:db.add(Character(project_id=project,name='林砚',realm_cap='渡劫',base_attrs={}))
                db.add(CharacterState(project_id=project,character_id=actor,field='realm',new_value='金丹',chapter_seq=6,source_chapter=3))
                if injury:db.add(CharacterState(project_id=project,character_id=actor,field='injury',new_value='濒死',chapter_seq=7,source_chapter=7))
                db.add(Fact(project_id=project,content=rule,category='规则',confirm_status='confirmed',source_chapter=2));db.flush()
                draft='林砚不过金丹期，竟施展出化神期才可动用的碎星诀，毫发无伤。'
                fs=[f for f in ValidationService(['炼气','筑基','金丹','元婴','化神','渡劫']).validate(db,project_id=project,chapter_seq=9,candidates=[],draft=draft).findings if f.conflict_type=='power']
                self.assertEqual(len(fs),0 if duplicate else 1)
                if not duplicate:
                    f=fs[0];self.assertEqual((f.severity,f.scope,f.source),('critical','local','L1'))
                    self.assertTrue(any(e.chapter==3 and '金丹' in e.quote for e in f.evidence))
                    self.assertTrue(any(e.chapter==2 and e.quote==rule for e in f.evidence))
                    self.assertTrue(any(e.chapter==9 and e.quote and e.quote in draft for e in f.evidence))
        finally:engine.dispose()
    def test_nonrealm_newer_state_does_not_mask_realm(self):self.check_boundary(injury=True)
    def test_realm_evidence_uses_source_chapter(self):self.check_boundary()
    def test_duplicate_character_name_is_ambiguous(self):self.check_boundary(duplicate=True)
import unittest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from myink.models import Character, CharacterState, Event, Fact, Foreshadow, PlotThread, Relation
from myink.validation.service import ValidationService

class LiteralAbilityCostTests(unittest.TestCase):
    def check_cost(self, ability, cost, expected, other=False):
        engine = create_engine('sqlite://')
        for model in (Character, CharacterState, Event, Fact, Foreshadow, PlotThread, Relation):
            model.__table__.create(engine)
        try:
            with Session(engine) as db:
                project, actor = uuid.uuid4(), uuid.uuid4()
                db.add(Character(id=actor, project_id=project, name='林砚', realm_cap='化神', base_attrs={}))
                if other: db.add(Character(project_id=project, name='陆沉', realm_cap='化神', base_attrs={}))
                db.add(CharacterState(project_id=project, character_id=actor, field='realm', new_value='金丹', chapter_seq=5, source_chapter=5))
                db.add(Fact(project_id=project, category='规则', content='化神期才可动用'+ability, confirm_status='confirmed', source_chapter=2))
                db.flush()
                draft='林砚不过金丹期，竟施展出化神期才可动用的'+ability+'，'+cost+'。'
                found=[f for f in ValidationService(['炼气','筑基','金丹','元婴','化神']).validate(db, project_id=project, chapter_seq=8, candidates=[], draft=draft).findings if f.conflict_type=='power']
                self.assertEqual(len(found), expected)
        finally:
            engine.dispose()
    def test_neutral_ability_actual_backlash_exempt(self): self.check_cost('碎星诀', '他遭到严重反噬', 0)
    def test_literal_ruo_ability_actual_backlash_exempt(self): self.check_cost('若水诀', '他遭到严重反噬', 0)
    def test_literal_ruo_ability_actual_lifespan_exempt(self): self.check_cost('若水诀', '他以十年寿元为代价', 0)
    def test_literal_ruo_ability_without_cost_reports(self): self.check_cost('若水诀', '毫发无伤', 1)
    def test_literal_ruo_ability_denied_cost_reports(self): self.check_cost('若水诀', '他没有遭到严重反噬', 1)
    def test_literal_ability_is_not_other_named_actor(self): self.check_cost('陆沉诀', '他遭到严重反噬', 0, other=True)
    def test_other_actor_actual_cost_still_reports(self): self.check_cost('碎星诀', '陆沉遭到严重反噬', 1, other=True)
    def test_explicit_actor_actual_cost_with_literal_other_name_exempt(self): self.check_cost('陆沉诀', '林砚遭到严重反噬', 0, other=True)
    def same_realm_distinct_source(self, reverse=False):
        engine = create_engine('sqlite://')
        for model in (Character, CharacterState, Event, Fact, Foreshadow, PlotThread, Relation):
            model.__table__.create(engine)
        try:
            with Session(engine) as db:
                project, actor = uuid.uuid4(), uuid.uuid4()
                db.add(Character(id=actor, project_id=project, name='林砚', realm_cap='化神', base_attrs={}))
                for source in ([4,3] if reverse else [3,4]):
                    db.add(CharacterState(project_id=project, character_id=actor, field='realm', new_value='金丹', chapter_seq=6, source_chapter=source))
                db.add(Fact(project_id=project, category='规则', content='化神期才可动用碎星诀', confirm_status='confirmed', source_chapter=2))
                db.flush()
                draft='林砚不过金丹期，竟施展出化神期才可动用的碎星诀，毫发无伤。'
                found=[f for f in ValidationService(['炼气','筑基','金丹','元婴','化神']).validate(db, project_id=project, chapter_seq=8, candidates=[], draft=draft).findings if f.conflict_type=='power']
                self.assertEqual(len(found), 1)
                self.assertTrue(any(e.chapter in (3,4) and '金丹' in e.quote for e in found[0].evidence))
        finally:
            engine.dispose()
    def test_equal_latest_realm_distinct_sources(self): self.same_realm_distinct_source()
    def test_equal_latest_realm_distinct_sources_reversed(self): self.same_realm_distinct_source(True)

class LiteralWhitespaceCostTests(unittest.TestCase):
    def test_leading_whitespace_literal_ability_actual_cost_exempt(self):
        engine=create_engine('sqlite://')
        for model in (Character,CharacterState,Event,Fact,Foreshadow,PlotThread,Relation):model.__table__.create(engine)
        try:
            with Session(engine) as db:
                project,actor=uuid.uuid4(),uuid.uuid4()
                db.add(Character(id=actor,project_id=project,name='林砚',realm_cap='化神',base_attrs={}))
                db.add(CharacterState(project_id=project,character_id=actor,field='realm',new_value='金丹',chapter_seq=5,source_chapter=5))
                db.add(Fact(project_id=project,category='规则',content='化神期才可动用若水诀',confirm_status='confirmed',source_chapter=2));db.flush()
                draft='   林砚不过金丹期，竟施展出化神期才可动用的若水诀，他遭到严重反噬。'
                fs=[f for f in ValidationService(['炼气','筑基','金丹','元婴','化神']).validate(db,project_id=project,chapter_seq=8,candidates=[],draft=draft).findings if f.conflict_type=='power']
                self.assertEqual(len(fs),0)
        finally:engine.dispose()

class LiteralCostSubjectReturnTests(unittest.TestCase):
    def test_real_other_subject_after_ability_name_still_blocks_local_pronoun(self):
        LiteralAbilityCostTests.check_cost(self, '陆沉诀', '陆沉遭到严重反噬，他遭到严重反噬', 1, other=True)
