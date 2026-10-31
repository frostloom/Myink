"""Finite contract slots over the existing Engine API, not a paid-run grant.

The trusted host owns gateway admission, canonical billing, containment and the
whole-run deadline. Returned payloads/receipts are PRIVATE: they contain prose.
"""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from .analysis_trial import GROUPS, legacy_shared_writing_prompt, score_contract_output
from .engine import AdministratorContext
from .provider_config import DEFAULT_MODEL, ANALYSIS_MODELS
from .writing_analysis import (
    _digest, _json, analysis_receipt, build_analysis_request, build_writing_prompt,
    preflight_request,
)


MODEL = DEFAULT_MODEL


def _hash(value):
    return sha256(_json(value).encode('utf-8')).hexdigest()


def _slot(view, report, *, model, cwd, domain, arm, repeat):
    if (model not in ANALYSIS_MODELS or domain not in GROUPS or arm not in ('baseline', 'candidate')
            or type(repeat) is not int or repeat not in (1, 2, 3)):
        raise ValueError('fixed model, group, arm and repetition required')
    cwd = Path(cwd)
    if not cwd.is_absolute() or '..' in cwd.parts:
        raise ValueError('absolute common cwd required')
    prompt = (legacy_shared_writing_prompt(view, report) if arm == 'baseline'
              else build_writing_prompt(view, report, target_domain=domain))
    sizes = preflight_request(prompt, model=model, cwd=cwd)
    request = build_analysis_request(prompt, model=model, cwd=cwd)
    return dict(slot_id=f'r{repeat}:{domain}:{arm}', domain=domain, arm=arm,
        repeat=repeat, view_sha256=_hash(view), report_sha256=_hash(report),
        prompt_sha256=sha256(prompt.encode('utf-8')).hexdigest(),
        system_sha256=_hash(request['system']), request_sha256=_hash(request),
        request_bytes=sizes, request=request)


def prepare_contract_slots(views, report, *, model, cwd):
    """Return all 30 PRIVATE slots in preregistered order, without execution."""
    if not isinstance(views, dict) or set(views) != set(GROUPS):
        raise ValueError('exact five frozen views required')
    result = []
    for repeat in (1, 2, 3):
        arms = ('candidate', 'baseline') if repeat == 2 else ('baseline', 'candidate')
        for domain in GROUPS:
            for arm in arms:
                result.append(_slot(views[domain], report, model=model, cwd=cwd,
                                    domain=domain, arm=arm, repeat=repeat))
    return result


def verify_contract_request(body, slot):
    """Host gateway checks actual normalized SDK body before any forwarding.

    A caller must bind slot from trusted frozen input, not model-controlled data.
    Key order may differ; added fields, Unicode content or numeric types may not.
    This check does not authorize or reserve a paid request.
    """
    if (not isinstance(body, dict) or _hash(body) != slot['request_sha256']
            or _hash(slot['request']) != slot['request_sha256']
            or max(len(_json(body).encode('utf-8')),
                   len(_json(body, ascii=True).encode('utf-8'))) > 65536):
        raise ValueError('actual SDK request differs from frozen slot')
    return slot['request_sha256']


def run_contract_slot(*, slot_index, slot, view, report, engine, session, deadline, model, cwd):
    """Run one fresh no-tool phase once; preserve invalid outputs, never repair.

    Engine/gateway/session and expected slot_index are host-owned. The host
    owns the durable cursor and prevents replay across invocations. No loop, retry, budget scope creation,
    provider transport or release capability is introduced here.
    """
    if type(slot_index) is not int or not 0 <= slot_index < 30:
        raise ValueError('trusted expected slot index required')
    repeat, offset = divmod(slot_index, 10)
    arms = ('candidate', 'baseline') if repeat == 1 else ('baseline', 'candidate')
    expected = _slot(view, report, model=model, cwd=cwd, domain=GROUPS[offset // 2],
                     arm=arms[offset % 2], repeat=repeat + 1)
    if _json(slot) != _json(expected):
        raise ValueError('slot identity or frozen input drift')
    path = Path(session.session_path)
    now = datetime.now(timezone.utc)
    if (session.engine != 'pi' or session.phase != 'analysis' or session.resume
            or session.verified_session_sha256 is not None or not _digest(session.config_hash)
            or not path.is_absolute() or '..' in path.parts or path.exists()
            or any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)()
                   for p in (path, *path.parents))
            or deadline.tzinfo is None or not 0 < (deadline - now).total_seconds() <= 90):
        raise ValueError('fresh session and bounded aware deadline required')
    identity = {k: slot[k] for k in ('slot_id', 'view_sha256', 'report_sha256',
                                    'prompt_sha256', 'system_sha256', 'request_sha256')}
    context = AdministratorContext('local-trial-1', slot['slot_id'], 'local-trial-1', _json(identity))
    receipt = engine.run_phase(phase='analysis', prompt=slot['request']['messages'][0]['content'][0]['text'],
        context=context, session=session, deadline=deadline, tools=[])
    parsed = analysis_receipt(receipt, view, identity)
    valid = False
    failure = 'engine_or_output_invalid'
    if parsed['analysis'] is not None and receipt.evidence.get('config_hash') == session.config_hash:
        try:
            score_contract_output(parsed['analysis'], view, slot['domain'])
            valid, failure = True, None
        except ValueError:
            failure = 'target_scope_invalid'
    return dict(**identity, engine_status=receipt.status, contract_valid=valid,
        failure=failure, evidence=receipt.evidence, analysis=parsed['analysis'],
        semantic_metrics='unknown', automatic_execution=False, release_allowed=False,
        billing_verified=False)
