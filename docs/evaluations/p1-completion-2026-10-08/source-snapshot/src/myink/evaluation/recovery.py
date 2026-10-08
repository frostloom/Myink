"""Offline assertions over exported synthetic recovery evidence, not a new live run."""
import hashlib
import json
from pathlib import Path


def check_recovery(source:Path) -> dict:
    raw=source.read_bytes();report=json.loads(raw);a=report['artifacts']
    initial=a['initial'];final=a['final'];db=a['database'];feedback=a['human_feedback']
    nodes=[r['node'] for r in report['runs']]
    revision_index=nodes.index('revise') if 'revise' in nodes else -1
    after=nodes[revision_index:] if revision_index>=0 else []
    checks={
        'full_drafts_present':bool(initial.get('draft') and final.get('draft') and feedback.get('rejected_draft')),
        'fault_not_in_original':feedback['injected_sentence'] not in (initial.get('draft') or ''),
        'fault_in_revision_input':feedback['injected_sentence'] in feedback['rejected_draft'],
        'fault_removed':feedback['injected_sentence'] not in (final.get('draft') or ''),
        'no_final_error':not report.get('error') and not final.get('error'),
        'review_completed':final.get('needs_review') is False,
        'audit_pass':(final.get('audit_verdict') or {}).get('verdict')=='pass',
        'revision_pipeline_exercised':all(n in after for n in ('revise','extract','validate','audit','persist')),
        'chapter_equals_final':any(c.get('content')==final.get('draft') for c in db['chapters']),
        'initial_version_retained':any(c.get('content')==initial.get('draft') for c in db['chapter_versions']),
        'rejection_applied':any(c.get('status')=='rejected' and (c.get('review') or {}).get('applied')
                                 for c in db['memory_candidates'])}
    return {'mode':'recovery_saved_evidence','source':source.as_posix(),
            'source_sha256':hashlib.sha256(raw).hexdigest(),'checks':checks,'deterministic_pass':all(checks.values()),
            'semantic_review':'pending','memory_invalidation':'inspect valid/expired rows individually; not inferred from counts',
            'note':'Rechecks a saved live run; does not execute a model, prove natural-error frequency or test provider/worker outages.'}
