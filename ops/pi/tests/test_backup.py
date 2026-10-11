"""Backup safety contract; real SQLite/files, finite artifact boundary doubles."""
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import gzip
import importlib.util
import json
from pathlib import Path
import threading
import pytest
from ops.pi.contracts import Identity
from ops.pi.ledger import Ledger


def api():
    assert importlib.util.find_spec('ops.pi.backup'), 'paired backup implementation missing'
    from ops.pi import backup
    return backup


@pytest.fixture
def case(tmp_path):
    ledger=Ledger(tmp_path/'ledger.sqlite')
    identity=Identity('old',1,'trusted',{'worker':'sha256:old'},commit_sha='frozen')
    pair={'release_pair_id':'release-1','pre_identity':asdict(identity),
          'post_identity':asdict(Identity('new',2,'trusted',{'worker':'sha256:new'},commit_sha='candidate')),
          'plan_hash':'a'*64}
    return ledger,identity,pair,tmp_path/'backups'


def artifacts(action, context):
    if action=='verify_identity':return {'verified':True,'consistency_id':'closed-epoch'}
    if action=='collect':
        root=Path(context['directory'])
        for name,body in [('database.sql.gz',gzip.compress(b'CREATE TABLE recovered(x int);')),
                          ('roles.sql',b'controlled roles'),('model.key',b'synthetic key'),
                          ('attachment.bin',b'synthetic attachment'),('config.json',b'{}'),('certificate.pem',b'synthetic cert')]:
            (root/name).write_bytes(body)
        return {'verified':True,'consistency_id':'closed-epoch','dump_exit':0,'dump_stderr_bytes':0,
                'source_id':'synthetic-source','roles':['myink_app'],
                'artifacts':{'database':'database.sql.gz','roles':'roles.sql','crypto':'model.key',
                    'attachments':'attachment.bin','config':'config.json','certificate':'certificate.pem'},
                'not_applicable':['production TLS'],'planned_peak_bytes':1}
    if action=='restore':return {'verified':True,'target_system_identifier':'different','assertions':['RLS','checkpoints']}
    raise AssertionError(action)


def backup(case, executor=artifacts, phase='PRE'):
    ledger,identity,pair,root=case
    return api().create_backup(ledger,phase,identity if phase=='PRE' else Identity(**{k:v for k,v in pair['post_identity'].items() if k!='schema_version'}),executor,root,pair=pair)


def test_pre_failure_blocks_candidate_not_recovery(case):
    def fail(action,context):
        if action=='collect':raise OSError('dump failed')
        return artifacts(action,context)
    assert backup(case,fail).status=='failed'
    assert not api().release_allowed(case[0],'release-1')
    assert api().release_allowed(case[0],'release-1',recovery=True)


def test_post_pending_blocks_next_release(case):
    assert backup(case).status=='done'
    pre=backup(case)
    m=json.loads(Path(pre.evidence['manifest_path']).read_text())
    restored=api().restore_check(m,{'clean':True,'system_identifier':'target','source_system_identifier':'source','collection_directory':str(Path(pre.evidence['manifest_path']).parent)},artifacts)
    api().record_restore(case[0],pre,restored)
    api().mark_released(case[0],'release-1',case[2]['post_identity'])
    assert not api().release_allowed(case[0],'next-release')
    assert api().release_allowed(case[0],'next-release',recovery=True)
    post=backup(case,phase='POST')
    assert post.status=='done'
    m=json.loads(Path(post.evidence['manifest_path']).read_text())
    restored=api().restore_check(m,{'clean':True,'system_identifier':'target2','source_system_identifier':'source','collection_directory':str(Path(post.evidence['manifest_path']).parent)},artifacts)
    api().record_restore(case[0],post,restored)
    assert api().release_allowed(case[0],'next-release')


def manifest(pair,phase,age,**extra):
    return {'backup_id':pair+':'+phase,'release_pair_id':pair,'phase':phase,'created_at':(datetime(2026,10,11,0,tzinfo=timezone.utc)-timedelta(days=age)).isoformat(),
            'integrity':'verified','restore_status':'done','mirror_status':'verified',**extra}


def test_stable_point_and_last_five_pairs_retained():
    rows=[manifest('p'+str(i),phase,30+i) for i in range(7) for phase in ('PRE','POST')]
    rows+= [manifest('stable','PRE',70,stable=True),manifest('daily','PRE',13),manifest('daily','POST',13),manifest('debt','PRE',80)]
    deletable=api().retention_candidates(rows,datetime(2026,10,11,20,tzinfo=timezone.utc))
    assert set(deletable)=={'p4:PRE','p4:POST','p5:PRE','p5:POST','p6:PRE','p6:POST'}


def test_failed_artifact_not_counted_as_good():
    rows=[manifest('p'+str(i),phase,30+i) for i in range(6) for phase in ('PRE','POST')]
    rows+= [manifest('broken','PRE',20),manifest('broken','POST',20,integrity='failed')]
    assert api().retention_candidates(rows,datetime(2026,10,11,tzinfo=timezone.utc))==['p5:POST','p5:PRE']


def test_duplicate_backup_trigger_has_one_owner(case):
    start=threading.Event();finish=threading.Event();results=[]
    def slow(action,context):
        if action=='collect':start.set();assert finish.wait(5)
        return artifacts(action,context)
    thread=threading.Thread(target=lambda:results.append(backup(case,slow)));thread.start()
    assert start.wait(5)
    duplicate=backup(case)
    finish.set();thread.join(5)
    assert duplicate.status=='pending'
    assert results[0].status=='done'
    assert backup(case)==results[0]
    with case[0].transaction() as db:
        assert db.execute("SELECT count(*) FROM events WHERE kind='backup_claim'").fetchone()[0]==1


@pytest.mark.parametrize('missing',['roles','crypto','attachments','config','certificate'])
def test_missing_roles_or_crypto_material_not_restorable(case,missing):
    receipt=backup(case)
    path=Path(receipt.evidence['manifest_path']);m=json.loads(path.read_text())
    del m['artifacts'][missing]
    assert api().restore_check(m,{'clean':True,'system_identifier':'target','source_system_identifier':'source','collection_directory':str(path.parent)},artifacts).status!='done'


def test_manifest_copy_without_trusted_publication_is_not_success(case):
    receipt=backup(case);ledger,identity,pair,root=case
    outsider=Ledger(root.parent/'outsider.sqlite')
    result=api().create_backup(outsider,'PRE',identity,artifacts,root,pair=pair)
    assert result.status!='done'


def test_snapshot_declares_own_high_water_mark(case):
    receipt=backup(case);m=json.loads(Path(receipt.evidence['manifest_path']).read_text())
    import sqlite3
    db=sqlite3.connect(Path(receipt.evidence['manifest_path']).parent/'ledger.sqlite')
    assert db.execute('SELECT max(id) FROM events').fetchone()[0]==m['ledger_snapshot']['event_hwm']
    with case[0].transaction() as live:
        assert live.execute('SELECT max(id) FROM events').fetchone()[0]>m['ledger_snapshot']['event_hwm']
    assert api().restore_check(m,{'clean':True,'system_identifier':'target','source_system_identifier':'source','collection_directory':str(Path(receipt.evidence['manifest_path']).parent)},artifacts).status=='done'


def test_changed_pair_identity_refused(case):
    backup(case);case[2]['plan_hash']='b'*64
    with pytest.raises(ValueError):backup(case)


def test_calendar_boundary_uses_shanghai_natural_dates():
    rows=[manifest('old','PRE',14),manifest('old','POST',14)]
    rows += [manifest('p'+str(i),phase,i+1) for i in range(5) for phase in ('PRE','POST')]
    rows[0]['created_at']=rows[1]['created_at']='2026-09-27T16:01:00+00:00'
    assert api().retention_candidates(rows,datetime(2026,10,11,16,tzinfo=timezone.utc))==['old:POST','old:PRE']


def test_post_cannot_precede_release(case):
    assert backup(case,phase='POST').status=='blocked'


def test_cached_published_collection_tamper_refuses_revalidation(case):
    receipt=backup(case)
    path=Path(receipt.evidence['manifest_path']).parent/'attachment.bin'
    path.write_bytes(b'corrupted')
    assert backup(case).status!='done'
    assert case[0].get(receipt.operation_id)['status']=='done'


def test_missing_restore_receipt_blocks_candidate(case):
    assert backup(case).status=='done'
    assert not api().release_allowed(case[0],'release-1')


def test_restore_snapshot_identity_cannot_be_relabelled(case):
    receipt=backup(case);directory=Path(receipt.evidence['manifest_path']).parent
    m=json.loads((directory/'manifest.json').read_text());m['identity']['generation']=999
    result=api().restore_check(m,{'clean':True,'system_identifier':'target','source_system_identifier':'source','collection_directory':str(directory)},artifacts)
    assert result.status=='failed'


def test_pre_and_post_cannot_share_deployment_identity(case):
    case[2]['post_identity']=case[2]['pre_identity']
    with pytest.raises(ValueError):backup(case)


def test_failed_restore_does_not_fill_calendar_coverage():
    rows=[manifest('ok','PRE',0),manifest('failed','PRE',1,restore_status='failed')]
    gaps=api().calendar_gaps(rows,datetime(2026,10,11,0,tzinfo=timezone.utc))
    assert '2026-10-10' in gaps and '2026-10-11' not in gaps
