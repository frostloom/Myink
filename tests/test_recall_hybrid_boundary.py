"""Hydrate fused event IDs within the project/chapter before consuming extra slots."""
import unittest
from unittest.mock import patch
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from myink.memory.recall import _hybrid_recall
from myink.models import Alias, Character, Event


class HybridBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://')
        for model in (Alias,Character,Event): model.__table__.create(self.engine)
        self.db=Session(self.engine)
        self.project=uuid.uuid4();self.foreign=uuid.uuid4()

    def tearDown(self):
        self.db.close();self.engine.dispose()

    def event(self,chapter,*,foreign=False,summary='合成向量事件'):
        row=Event(project_id=self.foreign if foreign else self.project,source_chapter=chapter,
                  summary=summary,participants=[])
        self.db.add(row);self.db.flush()
        return row

    def recall(self,hits,*,before=20,participants=None,existing=None):
        out=list(existing or [])
        with patch('myink.memory.recall.get_embedder') as embed, patch(
                'myink.memory.recall.PgvectorStore.search',return_value=[(r.id,.1) for r in hits]):
            embed.return_value.encode.return_value=[[0.0]]
            stats=_hybrid_recall(self.db,self.project,'合成摘要',participants,out,[],before_chapter=before)
        return out,stats

    def test_future_vector_rows_are_excluded_before_hydration(self):
        out,stats=self.recall([self.event(21)])
        self.assertEqual(out,[]);self.assertEqual(stats['fused_total'],0)

    def test_current_vector_rows_are_excluded(self):
        out,_=self.recall([self.event(20)])
        self.assertEqual(out,[])

    def test_future_vector_rows_cannot_spend_keyword_slots(self):
        future=[self.event(i) for i in range(21,26)]
        old=[self.event(i,summary='甲乙历史线索') for i in range(1,6)]
        out,stats=self.recall(future,participants=['甲乙'])
        self.assertEqual({r['event_id'] for r in out},{str(r.id) for r in old})
        self.assertEqual(stats['fused_total'],5)

    def test_foreign_source_id_cannot_hydrate(self):
        out,_=self.recall([self.event(1,foreign=True)])
        self.assertEqual(out,[])

    def test_foreign_ids_cannot_spend_keyword_slots(self):
        foreign=[self.event(i,foreign=True) for i in range(1,6)]
        old=[self.event(i,summary='甲乙本书线索') for i in range(1,6)]
        out,_=self.recall(foreign,participants=['甲乙'])
        self.assertEqual({r['event_id'] for r in out},{str(r.id) for r in old})

    def test_valid_vector_history_is_retained(self):
        row=self.event(19);out,stats=self.recall([row])
        self.assertEqual([r['event_id'] for r in out],[str(row.id)])
        self.assertEqual(stats['vector_status'],'ok')

    def test_unbounded_direct_call_remains_compatible(self):
        row=self.event(21);out,_=self.recall([row],before=None)
        self.assertEqual([r['event_id'] for r in out],[str(row.id)])

    def test_duplicate_vector_ids_are_deduplicated(self):
        row=self.event(1);out,_=self.recall([row,row])
        self.assertEqual(len(out),1)

    def test_existing_history_is_not_duplicated(self):
        row=self.event(1);existing=dict(event_id=str(row.id),chapter=1,summary='已有合成事件')
        out,stats=self.recall([row],existing=[existing])
        self.assertEqual(out,[existing]);self.assertEqual(stats['fused_total'],0)

    def test_keyword_only_history_survives(self):
        row=self.event(1,summary='甲乙线索');out,_=self.recall([],participants=['甲乙'])
        self.assertEqual([r['event_id'] for r in out],[str(row.id)])
