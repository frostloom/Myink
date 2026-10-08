"""Isolated production recall benchmark; vector fixture is explicitly NOT semantic evaluation."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
import uuid
from unittest.mock import patch

from sqlalchemy import delete, select

from myink.db import new_session, tenant_session
from myink.evaluation.cases import json_text
from myink.evaluation.isolation import require_isolated_database
from myink.evaluation.retrieval import RetrievalCase, retrieval_metrics
from myink.evaluation.runner import provenance
from myink.memory import recall
from myink.memory.vector_store import PgvectorStore
from myink.models import Alias, Chapter, Character, Event, Project, ProjectSettings, User


class LexicalVectorFixture:
    """Deterministic nonzero trigram hashing; tests ranking plumbing, not bge quality."""
    def encode(self, texts):
        result = []
        for value in texts:
            vector = [0.] * 1024
            for i in range(max(1, len(value)-2)):
                vector[int(hashlib.sha256(value[i:i+3].encode()).hexdigest()[:8], 16) % 1024] += 1
            norm = sum(v*v for v in vector)**.5
            result.append([v/norm for v in vector])
        return result


def run(directory, case_path):
    identity = require_isolated_database()
    data = json.loads(case_path.read_text(encoding='utf-8'))
    if data['schema_version'] != 1 or len({c['id'] for c in data['cases']}) != len(data['cases']):
        raise ValueError('invalid retrieval case version or duplicate id')
    data['cases'] = [RetrievalCase.model_validate(case).model_dump() for case in data['cases']]
    directory.mkdir(parents=True, exist_ok=False)
    (directory/'cases.json').write_text(json_text(data), encoding='utf-8')
    rows = []; cleaned = []
    with new_session() as db:
        owner = db.execute(select(User.id).limit(1)).scalar_one()
    for case in data['cases']:
        pid = uuid.uuid4(); foreign = uuid.uuid4(); ids = {}
        with new_session() as db:
            for p in (pid, foreign): db.add(Project(id=p, user_id=owner, title='P1 recall '+case['id']))
            db.commit()
        try:
            for p in (pid, foreign):
                with tenant_session(p) as db:
                    db.add(ProjectSettings(project_id=p, hard_constraints=[]))
                    char = Character(project_id=p, name=case['canonical'], realm_cap='普通人')
                    db.add(char); db.flush()
                    for alias in case['aliases']: db.add(Alias(project_id=p, alias=alias, entity_id=char.id))
                    db.add(Chapter(project_id=p, chapter_seq=29, status='confirmed', content='前章收尾。', summary=case['query']))
                    sources = case['events'] if p == pid else [{'id':'foreign','chapter':1,'summary':case['query']}]
                    for item in sources:
                        eid = uuid.uuid4()
                        if p == pid: ids[item['id']] = str(eid)
                        db.add(Event(id=eid, project_id=p, source_chapter=item['chapter'], summary=item['summary'], participants=[]))
                        db.flush()
                        PgvectorStore().upsert(db, project_id=p, level='event', source_id=eid,
                            source_chapter=item['chapter'], embedding=LexicalVectorFixture().encode([item['summary']])[0], model_version='evaluation-trigram-fixture')
            for variant in ('keyword', 'vector_fixture', 'rrf_fixture'):
                started = time.perf_counter()
                with ExitStack() as stack:
                    if variant == 'keyword':
                        class Disabled:
                            def encode(self, _): raise RuntimeError('evaluation disables vector leg')
                        stack.enter_context(patch.object(recall, 'get_embedder', lambda: Disabled()))
                        stack.enter_context(patch.object(recall, 'settings', replace(recall.settings, embed_enabled=False)))
                    else:
                        stack.enter_context(patch.object(recall, 'get_embedder', lambda: LexicalVectorFixture()))
                        stack.enter_context(patch.object(recall, 'settings', replace(recall.settings, embed_enabled=True)))
                    if variant == 'vector_fixture': stack.enter_context(patch.object(recall, '_keyword_event_leg', lambda *args: []))
                    with tenant_session(pid) as db:
                        ctx = recall.build_context(db, project_id=pid, chapter_seq=30, participants=case['participants'])
                        event_ids = [uuid.UUID(e['event_id']) for e in ctx.mid_term_events]
                        events = db.execute(select(Event).where(Event.id.in_(event_ids))).scalars().all()
                        actual = {str(e.id):str(e.project_id) for e in events}
                        returned = [{**e, 'project_id':actual.get(e['event_id'], 'unknown')} for e in ctx.mid_term_events]
                rows.append({'case_id':case['id'], 'variant':variant, 'embedding_kind':'disabled' if variant=='keyword' else 'lexical_fixture_not_semantic',
                    'metrics':retrieval_metrics([ids[k] for k in case['required']],returned,chapter_seq=30,project_id=str(pid)),
                    'returned':returned, 'stats':ctx.recall_stats, 'wall_ms':round((time.perf_counter()-started)*1000,3)})
        finally:
            for p in (pid, foreign):
                with tenant_session(p) as db: db.execute(delete(Project).where(Project.id==p))
            cleaned.append(case['id'])
        (directory/'results.json').write_text(json_text(rows),encoding='utf-8')
    summary = {}
    for variant in ('keyword','vector_fixture','rrf_fixture'):
        metrics = [r['metrics'] for r in rows if r['variant']==variant]
        eligible = [m for m in metrics if m['required']]
        summary[variant] = {'cases':len(metrics),'required_hits':sum(m['hit'] for m in eligible),'required_total':sum(m['required'] for m in eligible),
            'future_leaks':sum(m['future_leaks'] for m in metrics),'tenant_leaks':sum(m['tenant_leaks'] for m in metrics)}
    (directory/'summary.json').write_text(json_text(summary),encoding='utf-8')
    (directory/'manifest.json').write_text(json_text({'mode':'retrieval','identity':identity,'cleaned_cases':cleaned,
        'cases_sha256':hashlib.sha256(case_path.read_bytes()).hexdigest(),**provenance(Path.cwd()),
        'limits':['8 synthetic tasks, labels proposed','keyword uses production SQL; vectors are deterministic lexical fixtures, not bge semantic quality','measures final production context including 10 recent events; K varies, per-case returned_unique recorded']}),encoding='utf-8')
    print(json_text(summary))


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cases',type=Path,default=Path('evals/cases/retrieval.json'));a=p.parse_args()
    run(a.output,a.cases)
