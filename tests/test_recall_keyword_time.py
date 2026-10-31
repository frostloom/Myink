"""Recall relation boundaries using real ORM rows in an isolated SQLite database."""
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from myink.memory.recall import build_context
from myink.models import (
    Alias, Chapter, Character, CharacterState, Entity, Event, Fact, Foreshadow,
    MemoryCandidate, PlotThread, ProjectSettings, Relation, WritingLesson,
)


class RecallKeywordTimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        for model in (Alias, Chapter, Character, CharacterState, Entity, Event, Fact,
                      Foreshadow, MemoryCandidate, PlotThread, ProjectSettings,
                      Relation, WritingLesson):
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.project = uuid.uuid4()
        self.other_project = uuid.uuid4()
        self.hero = Character(project_id=self.project, name='甲', realm_cap='凡人')
        self.friend = Character(project_id=self.project, name='乙', realm_cap='凡人')
        self.db.add_all([self.hero, self.friend])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def scenario(self, blockers=(), other=False, terms=True):
        self.db.add(Chapter(project_id=self.project, chapter_seq=19, summary='合成前情'))
        old = Event(project_id=self.project, source_chapter=1, summary='甲乙发现合成线索', participants=[])
        self.db.add(old)
        for chapter in range(10, 20):
            self.db.add(Event(project_id=self.project, source_chapter=chapter,
                              summary='无关的合成事件', participants=[]))
        for chapter in blockers:
            self.db.add(Event(project_id=self.other_project if other else self.project,
                              source_chapter=chapter, summary='甲乙的后续合成事件', participants=[]))
        self.db.flush()
        context = build_context(self.db, project_id=self.project, chapter_seq=20,
                                participants=['甲乙'] if terms else [])
        return str(old.id), context

    def test_future_rows_do_not_starve_history(self):
        old, ctx = self.scenario(range(21, 26))
        self.assertIn(old, [e['event_id'] for e in ctx.mid_term_events])

    def test_current_old_rows_do_not_starve_history(self):
        old, ctx = self.scenario([20]*5)
        self.assertIn(old, [e['event_id'] for e in ctx.mid_term_events])

    def test_mixed_unavailable_rows_do_not_starve_history(self):
        old, ctx = self.scenario([20,21,22,23,24])
        self.assertIn(old, [e['event_id'] for e in ctx.mid_term_events])

    def test_many_future_rows_do_not_starve_history(self):
        old, ctx = self.scenario(range(21, 36))
        self.assertIn(old, [e['event_id'] for e in ctx.mid_term_events])

    def test_history_is_recalled_without_blockers(self):
        old, ctx = self.scenario()
        self.assertIn(old, [e['event_id'] for e in ctx.mid_term_events])

    def test_foreign_project_does_not_fill_slots(self):
        old, ctx = self.scenario(range(21,26), other=True)
        self.assertIn(old, [e['event_id'] for e in ctx.mid_term_events])

    def test_future_rows_are_never_output(self):
        _, ctx = self.scenario(range(21,26))
        self.assertTrue(all(e['chapter'] < 20 for e in ctx.mid_term_events))

    def test_current_rows_are_never_output(self):
        _, ctx = self.scenario([20]*5)
        self.assertTrue(all(e['chapter'] < 20 for e in ctx.mid_term_events))

    def test_missing_terms_does_not_invent_keyword_hits(self):
        old, ctx = self.scenario(terms=False)
        self.assertNotIn(old, [e['event_id'] for e in ctx.mid_term_events])

    def test_recalled_event_keeps_source_and_summary(self):
        old, ctx = self.scenario()
        row=next(e for e in ctx.mid_term_events if e['event_id']==old)
        self.assertEqual(row['chapter'],1)
        self.assertEqual(row['summary'],'甲乙发现合成线索')


if __name__ == '__main__':
    unittest.main()
