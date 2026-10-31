"""Backup safety contract; real SQLite/files, finite artifact boundary doubles."""
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import gzip
import importlib.util
import json
from pathlib import Path
import threading
from unittest.mock import patch
import pytest
from ops.pi.contracts import Identity, Receipt
CONTEXT={'schema_context':'schema-v1','tool_context':'tools-v1'}
NOW=datetime(2026,10,11,tzinfo=timezone.utc)
from ops.pi.ledger import Ledger


def api():
    assert importlib.util.find_spec('ops.pi.backup'), 'paired backup implementation missing'
    from ops.pi import backup
    return backup


def trusted_references(ledger,version=1,*,stable_ids=(),referenced_ids=(),context=CONTEXT,complete=True):
    operation='recovery-references:'+str(version)
    api().record_recovery_references(ledger,operation,version=version,context=context,complete=complete,stable_ids=stable_ids,referenced_ids=referenced_ids)
    return operation


@pytest.fixture
def case(tmp_path):
    ledger=Ledger(tmp_path/'ledger.sqlite')
    trusted_references(ledger)
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
    assert not api().release_allowed(case[0],'release-1',context=CONTEXT,now=NOW)
    assert api().release_allowed(case[0],'release-1',recovery=True)


def test_post_pending_blocks_next_release(case):
    assert backup(case).status=='done'
    pre=backup(case)
    m=json.loads(Path(pre.evidence['manifest_path']).read_text())
    restored=api().restore_check(m,{'clean':True,'system_identifier':'target','source_system_identifier':'source','collection_directory':str(Path(pre.evidence['manifest_path']).parent)},artifacts)
    api().record_restore(case[0],pre,restored,context=CONTEXT,now=NOW)
    api().mark_released(case[0],'release-1',case[2]['post_identity'],context=CONTEXT,now=NOW)
    assert not api().release_allowed(case[0],'next-release',context=CONTEXT,now=NOW)
    assert api().release_allowed(case[0],'next-release',recovery=True)
    post=backup(case,phase='POST')
    assert post.status=='done'
    m=json.loads(Path(post.evidence['manifest_path']).read_text())
    restored=api().restore_check(m,{'clean':True,'system_identifier':'target2','source_system_identifier':'source','collection_directory':str(Path(post.evidence['manifest_path']).parent)},artifacts)
    api().record_restore(case[0],post,restored,context=CONTEXT,now=NOW)
    assert api().release_allowed(case[0],'next-release',context=CONTEXT,now=NOW)


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
    assert not api().release_allowed(case[0],'release-1',context=CONTEXT,now=NOW)


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


def qualified_restore(case,phase='PRE'):
    receipt=backup(case,phase=phase);path=Path(receipt.evidence['manifest_path'])
    result=api().restore_check(json.loads(path.read_text()),{'clean':True,'system_identifier':'target-'+phase,'source_system_identifier':'source','collection_directory':str(path.parent)},artifacts)
    api().record_restore(case[0],receipt,result,context=CONTEXT,now=NOW)
    return receipt


def test_known_corrupt_pre_revokes_candidate_and_preserves_recovery(case):
    receipt=qualified_restore(case)
    assert api().release_allowed(case[0],'release-1',context=CONTEXT,now=NOW)
    (Path(receipt.evidence['manifest_path']).parent/'attachment.bin').write_bytes(b'corrupt')
    assert backup(case).status=='blocked'
    assert not api().release_allowed(case[0],'release-1',context=CONTEXT,now=NOW)
    with pytest.raises(ValueError):api().mark_released(case[0],'release-1',case[2]['post_identity'],context=CONTEXT,now=NOW)
    assert api().release_allowed(case[0],'release-1',recovery=True)
    assert case[0].get(receipt.operation_id)['status']=='done'


def test_known_corrupt_post_reopens_debt_and_preserves_history(case):
    qualified_restore(case);api().mark_released(case[0],'release-1',case[2]['post_identity'],context=CONTEXT,now=NOW)
    receipt=qualified_restore(case,'POST')
    assert api().release_allowed(case[0],'next-release',context=CONTEXT,now=NOW)
    (Path(receipt.evidence['manifest_path']).parent/'attachment.bin').write_bytes(b'corrupt')
    assert backup(case,phase='POST').status=='blocked'
    assert not api().release_allowed(case[0],'next-release',context=CONTEXT,now=NOW)
    assert api().release_allowed(case[0],'next-release',recovery=True)
    assert case[0].get(receipt.operation_id)['status']=='done'


def test_first_use_without_trusted_rehearsal_context_blocks_release(case):
    qualified_restore(case)
    assert not api().release_allowed(case[0],'release-1')
    assert api().release_allowed(case[0],'release-1',recovery=True)


@pytest.mark.parametrize('field',['schema_context','tool_context'])
def test_changed_rehearsal_context_requires_new_actual_restore(case,field):
    qualified_restore(case)
    changed={**CONTEXT,field:'changed'}
    assert not api().release_allowed(case[0],'release-1',context=changed,now=NOW)


def test_virtual_weekly_expiry_and_future_clock_block_candidate(case):
    qualified_restore(case)
    assert api().release_allowed(case[0],'release-1',context=CONTEXT,now=NOW+timedelta(days=7,microseconds=-1))
    assert not api().release_allowed(case[0],'release-1',context=CONTEXT,now=NOW+timedelta(days=7))
    assert not api().release_allowed(case[0],'release-1',context=CONTEXT,now=NOW-timedelta(seconds=1))
    assert api().release_allowed(case[0],'release-1',recovery=True,context=None)


@pytest.mark.parametrize('status',['pending','failed'])
def test_newer_pending_or_failed_rehearsal_blocks_prior_success(case,status):
    receipt=qualified_restore(case)
    new='restore:'+receipt.evidence['backup_id']+':new-attempt'
    operation=api().start_rehearsal(case[0],receipt,new,context=CONTEXT)
    if status=='failed':case[0].finish(Receipt(operation,'failed',{'reason':'actual_restore_failed'}))
    assert not api().release_allowed(case[0],'release-1',context=CONTEXT,now=NOW)
    assert api().release_allowed(case[0],'release-1',recovery=True)


def test_legacy_restore_receipt_cannot_qualify_current_context(case):
    receipt=backup(case);legacy='restore:'+receipt.evidence['backup_id']+':legacy'
    api().record_restore(case[0],receipt,Receipt(legacy,'done',{'verified':True}),now=NOW)
    assert not api().release_allowed(case[0],'release-1',context=CONTEXT,now=NOW)


def test_done_without_verified_actual_restore_cannot_qualify(case):
    receipt=backup(case);operation='restore:'+receipt.evidence['backup_id']+':unverified'
    api().record_restore(case[0],receipt,Receipt(operation,'done',{'verified':False}),context=CONTEXT,now=NOW)
    assert not api().release_allowed(case[0],'release-1',context=CONTEXT,now=NOW)
    assert api().release_allowed(case[0],'release-1',recovery=True)


def test_old_completed_post_is_not_a_permanent_weekly_obligation(case):
    ledger,identity,pair,root=case
    qualified_restore(case);api().mark_released(ledger,pair['release_pair_id'],pair['post_identity'],context=CONTEXT,now=NOW)
    qualified_restore(case,'POST')
    candidate=Identity('current-pre',3,'trusted',{'worker':'sha256:current'})
    newpair={'release_pair_id':'current-pair','pre_identity':asdict(candidate),'post_identity':asdict(Identity('candidate',4,'trusted',{'worker':'sha256:candidate'})),'plan_hash':'b'*64}
    newcase=(ledger,candidate,newpair,root)
    receipt=backup(newcase);path=Path(receipt.evidence['manifest_path'])
    result=api().restore_check(json.loads(path.read_text()),{'clean':True,'system_identifier':'current-target','source_system_identifier':'source','collection_directory':str(path.parent)},artifacts)
    api().record_restore(ledger,receipt,result,context=CONTEXT,now=NOW+timedelta(days=8))
    assert api().release_allowed(ledger,newpair['release_pair_id'],context=CONTEXT,now=NOW+timedelta(days=8)),'old completed POST should need availability, not another weekly restore'


def test_missing_reference_inventory_is_not_explicit_empty(case):
    ledger,identity,pair,root=case
    orphan=Ledger(root.parent/'missing-references.sqlite');other=(orphan,identity,pair,root.parent/'orphan-backups')
    qualified_restore(other)
    assert not api().release_allowed(orphan,pair['release_pair_id'],context=CONTEXT,now=NOW),'missing trusted current reference inventory cannot authorize'
    assert api().release_allowed(orphan,pair['release_pair_id'],recovery=True)


@pytest.mark.parametrize('status',['pending','failed','uncertain'])
def test_new_post_attempt_reopens_completed_debt(case,status):
    qualified_restore(case);api().mark_released(case[0],'release-1',case[2]['post_identity'],context=CONTEXT,now=NOW)
    receipt=qualified_restore(case,'POST')
    operation=api().start_rehearsal_attempt(case[0],receipt,'011b2b82-9364-40e6-8b44-a865358cdfef',context=CONTEXT)
    if status!='pending':case[0].finish(Receipt(operation,status,{'reason':'target_preparation_unconfirmed'}))
    assert not api().release_allowed(case[0],'next-release',context=CONTEXT,now=NOW+timedelta(days=30))
    assert api().release_allowed(case[0],'next-release',recovery=True)


@pytest.mark.parametrize('change',['missing-completeness','context','unknown-reference','pending'])
def test_current_reference_inventory_must_be_complete_bound_and_known(case,change):
    qualified_restore(case);ledger=case[0]
    if change=='pending':ledger.intent('recovery-references:2','recovery_reference_inventory',{'version':2,'context':CONTEXT,'complete':True,'stable_ids':[],'referenced_ids':[]})
    else:trusted_references(ledger,2,complete=change!='missing-completeness',context={**CONTEXT,'tool_context':'changed'} if change=='context' else CONTEXT,referenced_ids=['unknown'] if change=='unknown-reference' else [])
    assert not api().release_allowed(ledger,'release-1',context=CONTEXT,now=NOW)
    assert api().release_allowed(ledger,'release-1',recovery=True)


def historical_pairs(case):
    ledger,_,_,root=case;cases=[]
    for n in range(6):
        pre=Identity('pre-'+str(n),n*2+1,'trusted',{'worker':'sha256:pre-'+str(n)})
        pair={'release_pair_id':'history-'+str(n),'pre_identity':asdict(pre),'post_identity':asdict(Identity('post-'+str(n),n*2+2,'trusted',{'worker':'sha256:post-'+str(n)})),'plan_hash':'c'*64}
        current=(ledger,pre,pair,root);cases.append(current)
        # Creation and retention clocks share one fixed epoch; retain pair ordering.
        class HistoricalClock(datetime):
            @classmethod
            def now(cls,tz=None):
                value=NOW+timedelta(seconds=n)
                return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)
        with patch.object(api(),'datetime',HistoricalClock):
            qualified_restore(current);api().mark_released(ledger,pair['release_pair_id'],pair['post_identity'],context=CONTEXT,now=NOW);qualified_restore(current,'POST')
    # Current candidate is fresh; historical POST proofs stay unchanged.
    receipt=backup(cases[-1]);api().record_restore(ledger,receipt,Receipt('restore:'+receipt.evidence['backup_id']+':fresh-current','done',{'verified':True}),context=CONTEXT,now=NOW+timedelta(days=30))
    return cases


def test_classification_keeps_last_five_and_allows_only_eligible_archive(case):
    cases=historical_pairs(case);ledger=case[0];clock=NOW+timedelta(days=30)
    classified=api().classify_recovery_set(ledger,'classify:1',context=CONTEXT,now=clock)
    oldest=[backup(cases[0],phase=phase).evidence['backup_id'] for phase in ('PRE','POST')]
    assert classified.status=='done' and set(classified.evidence['archive_ids'])==set(oldest)
    for phase in ('PRE','POST'):Path(backup(cases[0],phase=phase).evidence['manifest_path']).unlink()
    assert api().release_allowed(ledger,cases[-1][2]['release_pair_id'],context=CONTEXT,now=clock)
    assert ledger.get('classify:1')['status']=='done'
    # Adding a trusted reference removes the exemption; it needs files and current proof.
    trusted_references(ledger,2,referenced_ids=[oldest[1]])
    assert not api().release_allowed(ledger,cases[-1][2]['release_pair_id'],context=CONTEXT,now=clock)
    assert api().release_allowed(ledger,cases[-1][2]['release_pair_id'],recovery=True)


def test_missing_unclassified_history_is_not_retirement(case):
    cases=historical_pairs(case);receipt=backup(cases[0],phase='POST')
    Path(receipt.evidence['manifest_path']).unlink()
    assert not api().release_allowed(case[0],cases[-1][2]['release_pair_id'],context=CONTEXT,now=NOW+timedelta(days=30))


def test_forged_archive_record_cannot_exempt_missing_history(case):
    cases=historical_pairs(case);ledger=case[0];old=backup(cases[0],phase='POST')
    payload={'references':{},'classified_at':NOW.isoformat(),'catalog':{}}
    ledger.intent('forged','recovery_set_classification',payload)
    ledger.finish(Receipt('forged','done',{'archive_ids':[old.evidence['backup_id']],'classification_sha256':'0'*64}))
    Path(old.evidence['manifest_path']).unlink()
    assert not api().release_allowed(ledger,cases[-1][2]['release_pair_id'],context=CONTEXT,now=NOW+timedelta(days=30))


def test_archive_does_not_waive_reopened_post_debt(case):
    cases=historical_pairs(case);ledger=case[0];clock=NOW+timedelta(days=30)
    assert api().classify_recovery_set(ledger,'classify:1',context=CONTEXT,now=clock).status=='done'
    receipt=backup(cases[0],phase='POST')
    api().start_rehearsal_attempt(ledger,receipt,'011b2b82-9364-40e6-8b44-a865358cdfef',context=CONTEXT)
    assert not api().release_allowed(ledger,cases[-1][2]['release_pair_id'],context=CONTEXT,now=clock)


def test_retained_post_corruption_blocks_after_classification(case):
    cases=historical_pairs(case);ledger=case[0];clock=NOW+timedelta(days=30)
    assert api().classify_recovery_set(ledger,'classify:1',context=CONTEXT,now=clock).status=='done'
    receipt=backup(cases[-1],phase='POST');(Path(receipt.evidence['manifest_path']).parent/'attachment.bin').write_bytes(b'known corruption')
    assert not api().release_allowed(ledger,cases[-1][2]['release_pair_id'],context=CONTEXT,now=clock)
    assert api().classify_recovery_set(ledger,'classify:2',context=CONTEXT,now=clock).status=='blocked'
    assert ledger.get(receipt.operation_id)['status']=='done'


@pytest.mark.parametrize('key',['stable_ids','referenced_ids'])
def test_trusted_required_reference_needs_current_rehearsal(case,key):
    receipt=qualified_restore(case);api().mark_released(case[0],'release-1',case[2]['post_identity'],context=CONTEXT,now=NOW);qualified_restore(case,'POST')
    trusted_references(case[0],2,**{key:[receipt.evidence['backup_id']]})
    assert api().release_allowed(case[0],'next-release',context=CONTEXT,now=NOW)
    assert not api().release_allowed(case[0],'next-release',context=CONTEXT,now=NOW+timedelta(days=8))
    assert api().release_allowed(case[0],'release-1',recovery=True)


def test_current_mirror_manifest_corruption_closes_gate(case):
    receipt=qualified_restore(case)
    (case[3].parent/'mirror'/receipt.evidence['backup_id']/'manifest.json').write_bytes(b'corrupt')
    assert not api().release_allowed(case[0],'release-1',context=CONTEXT,now=NOW)



def test_unattested_empty_inventory_cannot_override_current_refs(case):
    import hashlib
    receipt=qualified_restore(case);trusted_references(case[0],2,stable_ids=[receipt.evidence['backup_id']])
    payload={'version':3,'context':CONTEXT,'complete':True,'stable_ids':[],'referenced_ids':[]}
    case[0].intent('untrusted-empty','recovery_reference_inventory',payload)
    case[0].finish(Receipt('untrusted-empty','done',{'inventory_sha256':hashlib.sha256(api().encoded(payload)).hexdigest()}))
    assert not api().release_allowed(case[0],'release-1',context=CONTEXT,now=NOW)
    with pytest.raises(ValueError):trusted_references(case[0],2)


def test_archive_classification_cannot_hide_retention_window_or_incomplete_pair(case):
    cases=historical_pairs(case);ledger=case[0]
    # Every point is in the current natural-date window, including the sixth pair.
    assert api().classify_recovery_set(ledger,'classify-window',context=CONTEXT,now=NOW).evidence['archive_ids']==[]
    pre=Identity('incomplete-pre',20,'trusted',{'worker':'sha256:incomplete'})
    pair={'release_pair_id':'incomplete','pre_identity':asdict(pre),'post_identity':asdict(Identity('incomplete-post',21,'trusted',{'worker':'sha256:new'})),'plan_hash':'d'*64}
    receipt=qualified_restore((ledger,pre,pair,case[3]))
    classified=api().classify_recovery_set(ledger,'classify-old',context=CONTEXT,now=NOW+timedelta(days=30))
    assert classified.status=='done' and receipt.evidence['backup_id'] not in classified.evidence['archive_ids']


@pytest.mark.parametrize('entry',['gate','classification'])
def test_current_references_advancing_during_validation_are_refused(case,monkeypatch,entry):
    qualified_restore(case);ledger=case[0]
    assert api().release_allowed(ledger,'release-1',context=CONTEXT,now=NOW)
    original=api().revalidate_collection;advanced=False
    def advance(*args,**kwargs):
        nonlocal advanced
        result=original(*args,**kwargs)
        if not advanced:
            advanced=True;trusted_references(ledger,2,complete=False)
        return result
    monkeypatch.setattr(api(),'revalidate_collection',advance)
    if entry=='gate':assert not api().release_allowed(ledger,'release-1',context=CONTEXT,now=NOW),'refs changed while validation ran'
    else:assert api().classify_recovery_set(ledger,'classify-race',context=CONTEXT,now=NOW).status=='blocked','changed inventory received canonical archive authority'
    assert api().release_allowed(ledger,'release-1',recovery=True)
