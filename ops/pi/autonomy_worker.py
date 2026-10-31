"""Fixed ACTUAL phase subprocess; ordinary ubuntu identity and signal cancellation."""
from pathlib import Path
from threading import Event
import os,pwd,signal
from .audit import _path,_plain,require
from .development_inputs import file_hash,read_json

SCHEMAS=dict(manager_audit='pi-autonomy-audit-v1',development_audit='pi-development-audit-v1',candidate_audit='pi-autonomy-audit-v1',candidate_review='pi-candidate-review-v1',investigation='pi-investigation-v1',reproducer='pi-investigation-reproducer-v1',sdk_review='pi-sdk-review-v1',manager_handoff='pi-reviewed-manager-handoff-v1',coordinator_audit='pi-autonomy-audit-v1',coordinator_withdrawal='pi-autonomy-audit-v1')


def _identity():
    require(os.geteuid()==pwd.getpwnam('ubuntu').pw_uid and os.geteuid()!=0,'paid and reproduction kernels require ordinary ubuntu identity')


def run(component,config_path,config_sha256,*,cancel=None):
    require(component in SCHEMAS,'fixed autonomy worker phase required');cp=_path(config_path);_plain(cp)
    require(cp.stat().st_size<=65536 and file_hash(cp)==config_sha256,'phase config pin drift');c=read_json(cp)
    require(c.get('mode')=='ACTUAL' and c.get('schema')==SCHEMAS[component],'ACTUAL fixed phase schema required')
    cancel=cancel if cancel is not None else Event();require(not cancel.is_set(),'phase cancelled before dispatch');_identity()
    previous={}
    def stop(*_):cancel.set()
    try:
        for signum in (signal.SIGINT,signal.SIGTERM):previous[signum]=signal.signal(signum,stop)
        require(not cancel.is_set() and file_hash(cp)==config_sha256,'phase revoked before kernel')
        if component=='investigation':
            from .investigation_launcher import execute
            outcome=execute(cp,expected_config_sha256=config_sha256,cancel=cancel)
        elif component=='development_audit':
            from .development_audit import emit
            outcome=emit(cp,config_sha256)
        elif component=='candidate_review':
            from .candidate_review_launcher import execute
            outcome=execute(cp,expected_config_sha256=config_sha256,cancel=cancel)
        elif component=='sdk_review':
            from .sdk_review_launcher import execute
            outcome=execute(cp,expected_config_sha256=config_sha256,cancel=cancel)
        elif component=='reproducer':
            from .investigation_reproducer import execute
            outcome=execute(cp,config_sha256,cancel=cancel)
        elif component in ('manager_audit','candidate_audit','coordinator_audit','coordinator_withdrawal'):
            from .autonomy_audit import emit
            outcome=emit(cp,config_sha256)
        else:
            from .manager_handoff import publish
            outcome=publish(cp,config_sha256,cancel=cancel)
        count=outcome['new_attempts'] if component in ('investigation','sdk_review','candidate_review') else outcome['model_requests']
        require(type(count) is int and 0<=count<=1,'bounded phase count required')
        status='done'
        if component in ('investigation','sdk_review','candidate_review'):
            status='done' if outcome['verified'] is True else 'failed' if outcome['closed_verified'] is True else 'blocked'
        return dict(schema='pi-autonomy-worker-result-v1',component=component,mode='ACTUAL',status=status,model_requests=count,outcome=outcome)
    finally:
        for signum,handler in previous.items():signal.signal(signum,handler)
