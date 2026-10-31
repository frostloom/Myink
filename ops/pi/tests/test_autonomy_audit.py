"""Coordinator projections use the audit-only store, never billing authority."""
import importlib
from pathlib import Path
import pytest
from ops.pi.audit import AuditStore,encoded
from ops.pi.development_inputs import file_hash,read_json
from ops.pi.tests.test_autonomy_profile import profile,research_config,diagnosis_config,config_file,configured,proof,write,NOW


def api():return importlib.import_module('ops.pi.autonomy_audit')


def test_fixed_audit_writer_projects_stage_and_controller_version(profile):
    pp,p,c,context=profile;event=dict(kind='plan',status='no_change',run_id='research-source',occurred_at=NOW.isoformat(),summary='Verified source investigation chose no task.',details=dict(reference='autonomy.coordinator.v1',decision='no_task',next_action='none'),version=dict(controller_sha256=p['controller_sha256']),changes=[],evidence=[],followups=[],mode='SIMULATED',evidence_domain='synthetic')
    config=pp.parent/'coordinator-audit.json';write(config,dict(schema='pi-autonomy-audit-v1',mode='SIMULATED',audit_path=p['audit_path'],export_root=p['export_root'],events=[dict(record_key='coordinator-source',event=event)]))
    result=api().emit(config,file_hash(config));assert result['model_requests']==0 and result['records']==1
    assert api().emit(config,file_hash(config))['records']==1 and len(AuditStore(p['audit_path']).events(run_id='research-source'))==1
    assert (Path(p['export_root'])/'manifest.json').exists()


@pytest.mark.parametrize('fault',['mode','count','extra','pin'])
def test_bad_audit_projection_has_no_event_effect(profile,fault):
    pp,p,c,context=profile;config=pp.parent/'bad-audit.json';value=dict(schema='pi-autonomy-audit-v1',mode='SIMULATED',audit_path=p['audit_path'],export_root=p['export_root'],events=[])
    if fault=='mode':value['mode']='ACTUAL'
    elif fault=='count':value['events']=[{}]*3
    elif fault=='extra':value['command']='shell'
    write(config,value);before=AuditStore(p['audit_path']).events()
    with pytest.raises((ValueError,OSError,KeyError)):api().emit(config,'f'*64 if fault=='pin' else file_hash(config))
    assert AuditStore(p['audit_path']).events()==before
