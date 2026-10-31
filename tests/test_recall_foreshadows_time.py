"""Recall foreshadow boundaries using real ORM rows in an isolated SQLite database."""
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from myink.memory.recall import build_context
from myink.models import (
    Alias, Chapter, Character, CharacterState, Entity, Event, Fact, Foreshadow,
    MemoryCandidate, PlotThread, ProjectSettings, Relation, WritingLesson,
)


class RecallForeshadowTimeTests(unittest.TestCase):
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

    def add(self, chapter=1, status='planted', other=False):
        self.db.add(Foreshadow(project_id=self.other_project if other else self.project,
                              description='合成伏笔', planted_chapter=chapter,
                              status=status, trigger={'object': '合成物'}))
        self.db.flush()

    def recalled(self, chapter=3):
        return build_context(self.db, project_id=self.project,
                             chapter_seq=chapter).open_foreshadows

    def test_future_is_excluded(self):
        self.add(chapter=4)
        self.assertEqual(self.recalled(), [])

    def test_current_old_version_is_excluded(self):
        self.add(chapter=3)
        self.assertEqual(self.recalled(), [])

    def test_first_chapter_has_no_current_foreshadow(self):
        self.add(chapter=1)
        self.assertEqual(self.recalled(chapter=1), [])

    def test_historical_planted_is_kept(self):
        self.add(chapter=2)
        self.assertEqual(len(self.recalled()), 1)

    def test_historical_developing_is_kept(self):
        self.add(status='developing')
        self.assertEqual(len(self.recalled()), 1)

    def test_resolved_is_not_resurrected(self):
        self.add(status='resolved')
        self.assertEqual(self.recalled(), [])

    def test_dropped_is_not_resurrected(self):
        self.add(status='dropped')
        self.assertEqual(self.recalled(), [])

    def test_other_project_is_excluded(self):
        self.add(other=True)
        self.assertEqual(self.recalled(), [])

    def test_historical_fields_are_preserved(self):
        self.add(chapter=2)
        row=self.recalled()[0]
        self.assertEqual({k: v for k, v in row.items() if k != 'foreshadow_id'},
                         {'description': '合成伏笔', 'trigger': {'object': '合成物'},
                          'planted_chapter': 2, 'status': 'planted'})

    def test_empty_stays_empty(self):
        self.assertEqual(self.recalled(), [])


if __name__ == '__main__':
    unittest.main()
