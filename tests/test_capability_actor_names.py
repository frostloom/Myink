"""Real ORM/service registered-name regressions; no validator/provider mocks."""
import unittest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from myink.models import Character,CharacterState,Event,Fact,Foreshadow,PlotThread,Relation
from myink.validation.service import ValidationService


CAP_DRAFT = '他不过金丹期，竟施展出化神期才可动用的"碎星诀"，满天星辉坠落，而他却毫发无伤，无半分反噬。'

CAP_NAMED = '林砚不过金丹期，竟施展出化神期才可动用的碎星诀，毫发无伤。'

CAP_ORDER = ['炼气', '筑基', '金丹', '元婴', '化神', '大乘', '渡劫']

class CapabilityRuleTests(unittest.TestCase):

    def setUp(self):
        self.engine = create_engine('sqlite://')
        for m in (Character, CharacterState, Event, Fact, Foreshadow, PlotThread, Relation):
            m.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.project = uuid.uuid4()
        self.foreign = uuid.uuid4()
        self.actor = uuid.uuid4()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def check_case(self, draft=CAP_DRAFT, expected=False, *, rule=None, state=None, characters=None, chapter=8, order=None):
        chars = characters if characters is not None else [dict(id=self.actor, name='林砚', realm_cap='渡劫')]
        for row in chars:
            self.db.add(Character(project_id=self.project, race='人族', origin='test', personality='谨慎', base_attrs={}, **row))
        facts = [dict(content='化神期才可动用碎星诀', category='规则', source_chapter=2, confirm_status='confirmed')] if rule is None else rule
        states = [dict(character_id=self.actor, field='realm', new_value='金丹', chapter_seq=5, source_chapter=5)] if state is None else state
        for row in facts:
            r = dict(row)
            r.setdefault('project_id', self.project)
            self.db.add(Fact(**r))
        for row in states:
            r = dict(row)
            r.setdefault('project_id', self.project)
            self.db.add(CharacterState(**r))
        self.db.flush()
        svc = ValidationService(CAP_ORDER if order is None else order)
        fs = [f for f in svc.validate(self.db, project_id=self.project, chapter_seq=chapter, candidates=[], draft=draft).findings if f.conflict_type == 'power']
        self.assertEqual(len(fs), int(expected), [(f.severity, f.scope) for f in fs])
        if expected:
            f = fs[0]
            self.assertEqual((f.severity, f.scope, f.source), ('critical', 'local', 'L1'))
            self.assertTrue(any((e.chapter == chapter and e.quote and (e.quote in draft) and ('碎星诀' in e.quote) for e in f.evidence)))
            self.assertTrue(any((e.chapter == 2 and e.quote == '化神期才可动用碎星诀' for e in f.evidence)))
            self.assertTrue(any((e.chapter == 5 and '金丹' in e.quote for e in f.evidence)))
            again = [f for f in svc.validate(self.db, project_id=self.project, chapter_seq=chapter, candidates=[], draft=draft).findings if f.conflict_type == 'power']
            self.assertEqual(f.conflict_key, again[0].conflict_key)
        return fs

class RegisteredCapabilityActorTests(unittest.TestCase):
    setUp = CapabilityRuleTests.setUp
    tearDown = CapabilityRuleTests.tearDown
    check_case = CapabilityRuleTests.check_case

    def named(self, name, expected=True, suffix='，毫发无伤。', draft_name=None, duplicate=False):
        chars = [dict(id=self.actor, name=name, realm_cap='渡劫')]
        if duplicate:
            chars.append(dict(id=uuid.uuid4(), name=name, realm_cap='渡劫'))
        self.check_case(draft=(draft_name or name) + '不过金丹期，竟施展出碎星诀' + suffix, expected=expected, characters=chars)

    def test_registered_long_chinese_name_detected(self):
        self.named('天山北境林中客')

    def test_registered_middle_dot_name_detected(self):
        self.named('阿尔·林砚')

    def test_registered_latin_name_detected(self):
        self.named('LinYan')

    def test_registered_regex_metachar_name_detected(self):
        self.named('林(砚)')

    def test_long_name_same_actor_cost_exempts(self):
        self.named('天山北境林中客', False, '，天山北境林中客遭到严重反噬。')

    def test_middle_dot_denied_cost_still_detected(self):
        self.named('阿尔·林砚', True, '，阿尔·林砚没有遭到严重反噬。')

    def test_registered_prefix_extension_quiet(self):
        self.named('阿尔·林砚', False, draft_name='阿尔·林砚甲')

    def test_duplicate_registered_name_quiet(self):
        self.named('阿尔·林砚', False, duplicate=True)

class RegisteredNameHoldout(unittest.TestCase):

    def case(self, name, expected=1, tail='毫发无伤', others=(), draft_name=None, duplicate=False):
        engine = create_engine('sqlite://')
        for model in (Character, CharacterState, Event, Fact, Foreshadow, PlotThread, Relation):
            model.__table__.create(engine)
        try:
            with Session(engine) as db:
                project = uuid.uuid4()
                actor = uuid.uuid4()
                db.add(Character(id=actor, project_id=project, name=name, realm_cap='化神', base_attrs={}))
                for other in (*others, *((name,) if duplicate else ())):
                    db.add(Character(project_id=project, name=other, realm_cap='化神', base_attrs={}))
                db.add(CharacterState(project_id=project, character_id=actor, field='realm', new_value='筑基', chapter_seq=4, source_chapter=4))
                rule = '元婴期才可动用镇魂术'
                db.add(Fact(project_id=project, content=rule, category='规则', confirm_status='confirmed', source_chapter=1))
                db.flush()
                draft = (name if draft_name is None else draft_name) + '仍为筑基期，施展镇魂术，' + tail + '。'
                fs = [f for f in ValidationService(['炼气', '筑基', '金丹', '元婴', '化神']).validate(db, project_id=project, chapter_seq=7, candidates=[], draft=draft).findings if f.conflict_type == 'power']
                self.assertEqual(len(fs), expected)
                if expected:
                    self.assertTrue(any((e.chapter == 7 and e.quote in draft for e in fs[0].evidence)))
                    self.assertTrue(any((e.chapter == 1 and e.quote == rule for e in fs[0].evidence)))
                    self.assertTrue(any((e.chapter == 4 and '筑基' in e.quote for e in fs[0].evidence)))
        finally:
            engine.dispose()

    def test_hyphenated_registered_actor(self):
        self.case('Lin-Yan')

    def test_regex_characters_are_literal(self):
        self.case('[林].*')

    def test_regex_alternation_is_literal(self):
        self.case('林砚+|陆沉')

    def test_middle_dot_same_actor_cost(self):
        self.case('阿尔·林砚', 0, '阿尔·林砚遭到严重反噬')

    def test_long_actor_denied_cost(self):
        self.case('天山南境白衣客', 1, '天山南境白衣客未遭反噬')

    def test_other_registered_actor_cost(self):
        self.case('阿尔·林砚', 1, '林砚遭到严重反噬', others=('林砚',))

    def test_longer_unregistered_actor_quiet(self):
        self.case('Lin-Yan', 0, draft_name='Lin-YanII')

    def test_duplicate_literal_name_quiet(self):
        self.case('Lin-Yan', 0, duplicate=True)

class ExactCostActorBoundaryTests(unittest.TestCase):
    setUp = CapabilityRuleTests.setUp
    tearDown = CapabilityRuleTests.tearDown
    check_case = CapabilityRuleTests.check_case

    def test_unknown_longer_cjk_cost_actor_does_not_exempt(self):
        self.check_case(draft='林砚不过金丹期，施展碎星诀，老林砚遭到严重反噬。', expected=True)

    def test_unknown_latin_prefix_cost_actor_does_not_exempt(self):
        self.check_case(draft='LinYan不过金丹期，施展碎星诀，XLinYan遭到严重反噬。', expected=True, characters=[dict(id=self.actor, name='LinYan', realm_cap='渡劫')])

    def test_exact_named_cost_after_comma_still_exempts(self):
        self.check_case(draft='林砚不过金丹期，施展碎星诀，林砚遭到严重反噬。', expected=False)

    def test_exact_pronoun_cost_after_comma_still_exempts(self):
        self.check_case(draft='林砚不过金丹期，施展碎星诀，他遭到严重反噬。', expected=False)

    def test_unknown_pronoun_suffix_actor_does_not_exempt(self):
        self.check_case(draft='林砚不过金丹期，施展碎星诀，其他遭到严重反噬。', expected=True)

    def test_registered_other_longer_actor_cost_does_not_exempt(self):
        self.check_case(draft='林砚不过金丹期，施展碎星诀，老林砚遭到严重反噬。', expected=True, characters=[dict(id=self.actor, name='林砚', realm_cap='渡劫'), dict(id=uuid.uuid4(), name='老林砚', realm_cap='渡劫')])

class AdditionalCostBoundaryHoldout(unittest.TestCase):
    case = RegisteredNameHoldout.case

    def test_unicode_prefix_cost_actor_does_not_exempt(self):
        self.case('沈白', 1, 'α沈白遭到严重反噬')

    def test_digit_prefix_cost_actor_does_not_exempt(self):
        self.case('明川', 1, '2明川遭到严重反噬')

    def test_named_cost_after_semicolon_exempts(self):
        self.case('沈白', 0, '；沈白遭到严重反噬')

    def test_named_cost_after_whitespace_exempts(self):
        self.case('明川', 0, '  明川遭到严重反噬')

class CostDelimiterCompatibilityTests(unittest.TestCase):
    setUp = CapabilityRuleTests.setUp
    tearDown = CapabilityRuleTests.tearDown
    check_case = CapabilityRuleTests.check_case

    def test_ascii_comma_exact_named_cost_exempts(self):
        self.check_case(draft='林砚不过金丹期，施展碎星诀,林砚遭到严重反噬。', expected=False)

    def test_nbsp_exact_named_cost_exempts(self):
        self.check_case(draft='林砚不过金丹期，施展碎星诀，\xa0林砚遭到严重反噬。', expected=False)

class CostDelimiterHoldout(unittest.TestCase):
    case = RegisteredNameHoldout.case

    def test_ascii_comma_pronoun_cost_exempts(self):
        self.case('白衡', 0, ',他遭到严重反噬')

    def test_thin_space_named_cost_exempts(self):
        self.case('楚河', 0, '\u2009楚河遭到严重反噬')
