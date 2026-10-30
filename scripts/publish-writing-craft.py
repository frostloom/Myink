"""Explicit, bounded catalog upgrade. Caller supplies reviewed previous definitions.

No general initialization, book updates, private-copy updates or history deletion.
--apply is required for mutation; otherwise only preflight is executed.
"""
from copy import deepcopy
import argparse
import json
from sqlalchemy import select

RETIRE = frozenset('style:' + sid for sid in (
    'xianxia-jiuzhou', 'changan-yexing', 'xingjian-yuanzheng', 'dushi-yiguan'))
UPGRADE = frozenset(('writing-rule:continuity', 'role-prompt:writer', 'role-prompt:planner'))
ADD = frozenset(('genre-rule:craft-realism-suspense', 'style:life-narration',
    'style:light-humor',
    'style:warm-fresh',
    'style:romantic-tension',
    'style:restrained-suspense',
    'style:uncanny-gloom',
    'style:classical-elegance',
    'style:heroic-action',
    'style:rational-realist',
    'style:epic-scope',
    'style:poetic-imagery',
))
FIELDS = ('name', 'kind', 'source', 'body')


def apply_bundle(db, expected, *, apply=False):
    from myink.models.writing_resource import WritingResource
    from myink.writing_resource_seed import builtin_resources
    from myink.writing_resources import create_resource, update_resource, publish

    if set(expected) != RETIRE | UPGRADE:
        raise ValueError('Previous definition scope must match the exact release scope')
    targets = {r['id']: r for r in builtin_resources() if r['id'] in UPGRADE | ADD}
    if set(targets) != UPGRADE | ADD:
        raise ValueError('Candidate bundle incomplete')
    rows = {r.id: r for r in db.scalars(select(WritingResource).where(
        WritingResource.id.in_(RETIRE | UPGRADE | ADD)).with_for_update())}
    changes = []
    # Validate every row before any mutation. Existing admin drafts/publications
    # must exactly match the reviewed previous bundle, never silently replaced.
    for rid in sorted(RETIRE | UPGRADE | ADD):
        row = rows.get(rid)
        if row is None:
            if rid in ADD:
                changes.append((rid, None))
                continue
            if rid in RETIRE:
                continue
            raise ValueError('Missing required existing resource: ' + rid)
        document = {k: deepcopy(getattr(row, k)) for k in FIELDS}
        if row.status != 'published' or not row.current_version:
            raise ValueError('Resource is not a clean publication: ' + rid)
        if any(row.publication.get(k) != document[k] for k in FIELDS):
            raise ValueError('Unpublished administrator edits: ' + rid)
        if rid in UPGRADE | ADD and document == {k: targets[rid][k] for k in FIELDS}:
            continue  # Explicit rerun is harmless, without adding a revision.
        if rid in ADD or document != {k: expected[rid][k] for k in FIELDS}:
            raise ValueError('Administrator definition differs from reviewed baseline: ' + rid)
        changes.append((rid, row.generation))
    report = {'added': [r for r, _ in changes if r in ADD], 'upgraded': [r for r, _ in changes if r in UPGRADE],
              'removed_current_entries': [r for r, _ in changes if r in RETIRE], 'applied': apply}
    if apply:
        for rid, generation in changes:
            if rid in RETIRE:
                db.delete(rows[rid])
            elif rid in ADD:
                row = create_resource(db, {k: deepcopy(targets[rid][k]) for k in FIELDS}, rid=rid)
                publish(db, rid, row.generation, 'Optional writing resource initial publication')
            else:
                data = {k: deepcopy(targets[rid][k]) for k in FIELDS}
                row = update_resource(db, rid, generation, data)
                publish(db, rid, row.generation, 'Tested chapter craft upgrade; prior versions preserved')
        db.flush()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    from myink.db import new_session
    with open(args.expected) as file:
        expected = json.load(file)
    with new_session() as db:
        report = apply_bundle(db, expected, apply=args.apply)
        if args.apply:
            db.commit()
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
