"""Offline checks for the fixed readonly-preview fence in the canonical ledger."""
import httpx

from ops.pi.budget import reserve, totals
from ops.pi.ledger import Ledger
from ops.pi.model_gateway import forward_messages
from ops.pi.tests.test_budget import ledger, policy, request
from ops.pi.lab.preview_gateway import ensure_preview_fence, make_preview_transport


def test_preview_restart_keeps_original_canonical_baseline(ledger, policy):
    reserve(ledger, 'local-trial-1', request(), policy)
    reserve(ledger, 'local-trial-1', request(), policy)
    assert ensure_preview_fence(ledger) == {'scope_id': 'local-trial-1', 'baseline_attempts': 2, 'max_preview_attempts': 6}
    reserve(ledger, 'local-trial-1', request(), policy)
    restarted = Ledger(ledger.path)
    assert ensure_preview_fence(restarted) == {'scope_id': 'local-trial-1', 'baseline_attempts': 2, 'max_preview_attempts': 6}
    assert totals(restarted, 'local-trial-1') == (3, 30000)


def test_preview_six_actual_forwards_then_restart_blocks_send_after_reservation(ledger, policy):
    calls = []
    def provider(req):
        calls.append(req)
        assert req.url.path == '/v1/messages' and req.url.query == b''
        return httpx.Response(200, json=dict(id='synthetic-id', usage=dict(input_tokens=1, output_tokens=1,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0)))
    credentials = {'PLATFORM_MODEL_API_KEY': 'synthetic-upstream-key'}
    with httpx.Client(transport=httpx.MockTransport(provider), trust_env=False, follow_redirects=False) as client:
        send = make_preview_transport(ledger, policy, client, credentials)
        for _ in range(6):
            assert forward_messages(request(), 'local-trial-1', ledger=ledger, policy=policy,
                                    transport=send).status_code == 200
        assert len(calls) == 6
        assert totals(ledger, 'local-trial-1') == (6, 60)
        restarted = Ledger(ledger.path)
        restarted_send = make_preview_transport(restarted, policy, client, credentials)
        blocked = forward_messages(request(), 'local-trial-1', ledger=restarted, policy=policy,
                                   transport=restarted_send)
        assert blocked.status_code == 502
        assert len(calls) == 6
        assert restarted.get(blocked.attempt_id)['status'] == 'uncertain'
        assert totals(restarted, 'local-trial-1') == (7, 10060)
