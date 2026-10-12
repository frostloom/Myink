"""Consumes root-launched real Pi proof; ordinary unit doubles do not satisfy it."""
import hashlib
import json
import os
from pathlib import Path
import pytest

pytestmark=pytest.mark.pi_lab


def test_installed_pi_controlled_tool_roundtrip_and_denials(lab_identity):
    raw_path=os.environ.get('MYINK_PI_TOOL_MOCK_RECEIPT')
    assert raw_path,'root-launched accepted lightweight tool mock receipt required'
    path=Path(raw_path)
    assert path.is_absolute() and not path.is_symlink() and path.stat().st_size<=65536
    proof=json.loads(path.read_text())
    assert proof['status']=='done' and proof['installed_pi_version']=='1.1.0'
    assert proof['mock_only'] and proof['simulated_authority'] and proof['production_ready'] is False
    assert proof['paid_http_requests']==0 and proof['mock_model_attempts']==8
    assert [r['status'] for r in proof['tools']]==['done','blocked','blocked','blocked','done','blocked','done']
    e=proof['receipt']['evidence']
    assert proof['receipt']['status']=='done' and e['session_valid'] and e['settled'] and e['process_exited']
    assert e['returncode']==0 and len(e['verified_tool_calls'])==7 and e['pending_tool_calls']==[]
    assert proof['candidate_sha256']==hashlib.sha256(b'value = 2\n').hexdigest()
    assert proof['envelope']['uid']==65534 and proof['envelope']['no_new_privs'] and proof['envelope']['no_capabilities']
    assert proof['envelope']['memory.max']=='402653184' and proof['envelope']['memory.swap.max']=='0'
    assert proof['isolated_check_gate'].startswith('blocked')
    session=Path(e['session_path']);assert hashlib.sha256(session.read_bytes()).hexdigest()==e['session_sha256']
