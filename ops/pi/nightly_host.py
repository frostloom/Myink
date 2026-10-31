"""Cheap admission for installed hosts; waiting never imports a model/metric host.

Only an already claimed preparation may run the existing pipeline. An idle gate
requires the single-cycle nightly driver to claim first. Existing timers cannot
start a round themselves. Approval permits publication separately; it never
admits another development or observation tick before verified deployment.
"""
from .audit import require
from .nightly_gate import ApprovalGate,BASE

PREPARATION=frozenset(('observer','product_observer','diagnosis','review_worker','investigation','reproducer','sdk_review','candidate_review','candidate_audit','development_audit','manager_audit','manager_handoff','coordinator_audit','coordinator_withdrawal','autonomy','manager'))
OBSERVATION=frozenset(('observer','product_observer','followup'))


def admission(gate,component):
    require(component in PREPARATION|OBSERVATION,'unknown fixed nightly component')
    state=gate.status();phase=state['phase']
    allowed=phase=='preparing' and component in PREPARATION
    if allowed and gate.rebuild_info(state['cycle_id']) is not None:allowed=False
    if phase=='observing' and component in OBSERVATION:
        gate.require_action(state['cycle_id'],'observe_metrics');allowed=True
    return dict(status='admitted' if allowed else 'waiting_human',allowed=allowed,
                phase=phase,cycle_id=state['cycle_id'],model_requests=0)


def runtime_admission(component):
    # No fallback/initialization: a missing or invalid gate fails closed in entry.
    gate=ApprovalGate(BASE/'state/nightly-approval.sqlite',
                      BASE/'state/actual-manager.sqlite',BASE/'state/ledger.sqlite',mode='ACTUAL')
    return admission(gate,component)


def manager_task(gate):
    state=gate.status();require(state['phase']=='preparing' and state['task_id'] is not None,'one original task must be bound before manager dispatch');return state['task_id']


def runtime_manager_task():
    gate=ApprovalGate(BASE/'state/nightly-approval.sqlite',BASE/'state/actual-manager.sqlite',BASE/'state/ledger.sqlite',mode='ACTUAL')
    return manager_task(gate)
