"""Authenticity is rechecked before any untrusted proposal can be frozen."""
from pathlib import Path
import importlib,pytest
from ops.pi.development_inputs import file_hash,ledger_snapshot,read_json
from ops.pi.tests.test_investigation_launcher import research_config,diagnosis_config,config_file,configured,proof,NOW,write,run_research


@pytest.fixture
def completed_research(research_config,proof,monkeypatch,request):
    result,_,_=run_research(research_config,proof,monkeypatch,getattr(request,'param','task'));assert result['verified'] is True
    return research_config


def api():return importlib.import_module('ops.pi.investigation_evidence')


def test_stopped_session_and_known_charge_revalidated_without_mutation(completed_research):
    cp,c,context,p=completed_research;before={q:q.read_bytes() for q in cp.parent.rglob('*') if q.is_file()}
    value=api().inspect(cp,file_hash(cp),clock=lambda:NOW)
    assert value['proposal']['decision']=='task' and value['fee']['sha256']==ledger_snapshot(c['ledger_path'])['sha256']
    assert value['authority']=='untrusted_proposal' and before=={q:q.read_bytes() for q in cp.parent.rglob('*') if q.is_file()}


@pytest.mark.parametrize('fault',['intent','manifest','initial','frame','request','verification','result','before','after','cleanup','config_pin'])
def test_result_boolean_cannot_replace_full_sdk_and_fee_proof(completed_research,fault):
    cp,c,context,p=completed_research;pin=file_hash(cp)
    if fault=='config_pin':pin='f'*64
    else:
        names={'intent':'intent.json','manifest':'manifest-private.json','initial':'initial-private.json','frame':'worker-frame-private.json','request':'request-private.json','verification':'verification.json','result':'result.json','before':'ledger-before-private.json','after':'ledger-after-private.json','cleanup':'result.json'}
        target=Path(c['root'])/names[fault];value=read_json(target)
        if fault=='cleanup':value['cleanup'][0]['removed']=False
        else:value={}
        write(target,value)
    before=ledger_snapshot(c['ledger_path'])
    with pytest.raises((ValueError,OSError,KeyError,TypeError)):api().inspect(cp,pin,clock=lambda:NOW)
    assert ledger_snapshot(c['ledger_path'])==before
