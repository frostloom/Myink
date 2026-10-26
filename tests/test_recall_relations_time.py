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


class RecallRelationTimeTests(unittest.TestCase):
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

    def relation(self, *, chapter, valid_from=1, valid_to=None, reverse=False,
                 other_project=False):
        row = Relation(
            project_id=self.other_project if other_project else self.project,
            source_id=self.friend.id if reverse else self.hero.id,
            target_id=self.hero.id if reverse else self.friend.id,
            relation_type='ally', source_chapter=chapter, valid_from=valid_from,
            valid_to=valid_to,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def recalled(self, chapter=3):
        context = build_context(self.db, project_id=self.project,
                                chapter_seq=chapter, participants=['甲'])
        return context.entity_snapshots[0]['relations']

    def test_future_relation_is_not_recalled(self):
        self.relation(chapter=4)
        self.assertEqual(self.recalled(), [])

    def test_current_chapter_old_relation_is_not_recalled(self):
        self.relation(chapter=3)
        self.assertEqual(self.recalled(), [])

    def test_future_effective_relation_is_not_recalled(self):
        self.relation(chapter=1, valid_from=4)
        self.assertEqual(self.recalled(), [])

    def test_historical_outgoing_relation_remains(self):
        self.relation(chapter=2)
        self.assertEqual(self.recalled(), [
            {'target': '乙', 'relation_type': 'ally', 'source_chapter': 2}])

    def test_effective_boundary_is_inclusive(self):
        self.relation(chapter=1, valid_from=3)
        self.assertEqual(len(self.recalled()), 1)

    def test_unknown_effective_start_keeps_historical_relation(self):
        row = self.relation(chapter=1)
        row.valid_from = None
        self.db.flush()
        self.assertEqual(len(self.recalled()), 1)

    def test_closed_relation_is_not_resurrected(self):
        self.relation(chapter=1, valid_to=5)
        self.assertEqual(self.recalled(), [])

    def test_incoming_relation_is_not_reversed(self):
        self.relation(chapter=1, reverse=True)
        self.assertEqual(self.recalled(), [])

    def test_other_project_relation_is_not_recalled(self):
        self.relation(chapter=1, other_project=True)
        self.assertEqual(self.recalled(), [])

    def test_first_chapter_does_not_recall_later_relation(self):
        self.relation(chapter=1)
        self.assertEqual(self.recalled(chapter=1), [])


if __name__ == '__main__':
    unittest.main()
