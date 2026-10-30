"""Exact-revision backend/catalog rollout, with protected-data and history gates."""
import json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path
revision=sys.argv[1]
assert re.fullmatch('[0-9a-f]{40}',revision)
short=revision[:8]; root=Path('/home/ubuntu/myink'); os.chdir(root); os.umask(0o077)
state=root/'releases'/('writing-craft-'+short); state.mkdir(mode=0o700,exist_ok=True)
d=['sudo','-n','docker']; compose=d+['compose','-f',str(root/'docker-compose.yml')]
def out(args,**kw): return subprocess.check_output(args,**kw)
def run(args,**kw): subprocess.run(args,check=True,**kw)
def sql(query): return out(d+['exec','myink-pg','psql','-U','myink','-d','myink','-Atc',query]).decode().strip()
def active(): return int(sql("SELECT count(*) FROM tasks WHERE status IN ('queued','running','retrying')"))
def queues_empty():
    raw=out(d+['exec','myink-rabbitmq','rabbitmqctl','-q','list_queues','name','messages_ready','messages_unacknowledged']).decode()
    for line in raw.splitlines():
        p=line.split()
        if len(p)==3 and p[0] in ('queue:tasks','queue:delay','queue:tasks:vip','queue:delay:vip'):
            assert int(p[1])+int(p[2])==0,'Pending deliveries; postpone rollout'
def health(): return json.load(urllib.request.urlopen('https://myink.cloud/readyz',timeout=10))
def keyed(raw,n=1): return {'|'.join(line.split('|')[:n]):line for line in raw.splitlines() if line}
resource_sql='SELECT id,generation,current_version,md5(body::text),md5(publication::text) FROM writing_resources ORDER BY id'
revision_sql='SELECT resource_id,version,md5(document::text) FROM writing_resource_revisions ORDER BY resource_id,version'
publication_sql='SELECT resource_id,generation,md5(document::text) FROM writing_resource_publications ORDER BY resource_id,generation'
upgrade={'writing-rule:continuity','role-prompt:writer','role-prompt:planner'}
add={'genre-rule:craft-realism-suspense', 'style:classical-elegance', 'style:romantic-tension', 'style:poetic-imagery', 'style:uncanny-gloom', 'style:rational-realist', 'style:heroic-action', 'style:epic-scope', 'style:light-humor', 'style:restrained-suspense', 'style:warm-fresh', 'style:life-narration'}
retire={'style:xianxia-jiuzhou','style:changan-yexing','style:xingjian-yuanzheng','style:dushi-yiguan'}
image='myink-api:'+short
meta=json.loads(out(d+['image','inspect',image]))[0]
assert meta['Architecture']=='amd64' and meta['Config']['Labels']['org.opencontainers.image.revision']==revision
with (state/'attempt-started.json').open('x') as marker:
    json.dump({'revision':revision,'started_at':time.time()},marker)
old=out(d+['inspect','-f','{{.Image}}','myink-api']).decode().strip()
caddy=json.loads(out(d+['inspect','myink-caddy']))[0]
(state/'previous-api.txt').write_text(old)
(state/'compose.before.yml').write_bytes((root/'docker-compose.yml').read_bytes())
(state/'environment.before').write_bytes((root/'.env').read_bytes())
run(d+['tag',old,'myink-api:before-craft-'+short])
override=state/'candidate.json'; override.write_text(json.dumps({'services':{'myink-migrate':{'image':image}}}))
candidate=compose+['-f',str(override)]
publisher=(state/'publish-writing-craft.py').read_text()
expected=json.loads((state/'expected-old.json').read_text())
assert set(expected)==upgrade|retire
# Package exactly one reviewed release transaction; never run full seed/init.
prefix=publisher.replace("if __name__ == '__main__':\n    main()",'')
prelude=prefix+'\nfrom myink.db import get_admin_engine\nfrom sqlalchemy.orm import Session\nexpected='+repr(expected)+'\n'
def catalog_apply(apply=False):
    code=prelude+f"with Session(get_admin_engine()) as db:\n report=apply_bundle(db,expected,apply={apply!r})\n"+(' db.commit()\n' if apply else '')+"print(json.dumps(report))\n"
    raw=out(candidate+['run','--rm','--no-deps','-T','--entrypoint','python','myink-migrate','-'],input=code.encode())
    return json.loads(raw)
plan=catalog_apply()
assert set(plan['upgraded'])==upgrade and set(plan['added'])==add and set(plan['removed_current_entries'])==retire
assert active()==0; queues_empty()
tables=sql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
tables=[t for t in tables if t not in ('writing_resources','writing_resource_revisions','writing_resource_publications')]
assert all(re.fullmatch('[a-z][a-z0-9_]*',t) for t in tables)
def protected():
    return {t:sql('SELECT count(*),md5(COALESCE(string_agg(row_to_json(t)::text,\'|\' ORDER BY row_to_json(t)::text),\'\')) FROM "'+t+'" t') for t in tables}
changed=False; catalog_attempted=False; catalog_changed=False; protected_before=None; resources=None; after=None
try:
    changed=True; run(compose+['stop','-t','120','myink-api'])
    assert active()==0; queues_empty()
    run(compose+['stop','-t','120','myink-worker'])
    assert active()==0; queues_empty()
    protected_before=protected(); resources=keyed(sql(resource_sql)); revisions=keyed(sql(revision_sql),2); publications=keyed(sql(publication_sql),2)
    for filename,value in [('protected-before.json',protected_before),('resource-hashes-before.json',resources),('revision-hashes-before.json',revisions),('publication-hashes-before.json',publications)]:
        (state/filename).write_text(json.dumps(value))
    with (state/'database-before.dump').open('wb') as file: run(d+['exec','myink-pg','pg_dump','-U','myink','-d','myink','-Fc'],stdout=file)
    assert (state/'database-before.dump').stat().st_size>0
    with (state/'database-before.dump').open('rb') as file,(state/'backup-manifest.txt').open('wb') as log: run(d+['exec','-i','myink-pg','pg_restore','--list'],stdin=file,stdout=log)
    initial_versions=sql("SELECT id FROM writing_resources WHERE id IN ("+','.join("'"+rid+"'" for rid in sorted(upgrade|retire))+") AND (current_version<>1 OR generation<>1)")
    assert not initial_versions,'This release expects version/generation 1 for the reviewed bundle'
    assert catalog_apply()==plan
    catalog_attempted=True
    report=catalog_apply(True); catalog_changed=True
    (state/'catalog-transaction.json').write_text(json.dumps(report))
    assert set(report['upgraded'])==upgrade and set(report['added'])==add and set(report['removed_current_entries'])==retire
    after=keyed(sql(resource_sql)); after_revisions=keyed(sql(revision_sql),2); after_publications=keyed(sql(publication_sql),2)
    assert resources.keys()-after.keys()==retire and after.keys()-resources.keys()==add
    assert {rid for rid in resources.keys()&after.keys() if resources[rid]!=after[rid]}==upgrade
    assert all(after_revisions.get(key)==value for key,value in revisions.items())
    assert all(after_publications.get(key)==value for key,value in publications.items())
    assert {key.split('|')[0] for key in after_revisions.keys()-revisions.keys()}==upgrade|add
    assert len(after_revisions)-len(revisions)==len(upgrade|add)
    assert {key.split('|')[0] for key in after_publications.keys()-publications.keys()}==upgrade|add
    assert len(after_publications)-len(publications)==len(upgrade|add)
    assert protected()==protected_before,'Protected noncatalog data changed'
    (state/'resource-hashes-after.json').write_text(json.dumps(after))
    run(d+['tag',image,'myink-api:local'])
    run(compose+['up','-d','--no-deps','--no-build','--scale','myink-worker=2','myink-worker'])
    run(compose+['up','-d','--no-deps','--no-build','myink-api'])
    for _ in range(40):
        try:
            if health()['status']=='ok': break
        except Exception: pass
        time.sleep(2)
    else: raise RuntimeError('Backend readiness failed')
    apps=json.loads(out(d+['inspect','myink-api','myink-myink-worker-1','myink-myink-worker-2']))
    assert all(c['State']['Running'] and c['Config']['Labels']['org.opencontainers.image.revision']==revision for c in apps)
    assert all(not any(m['Destination']=='/app/src' for m in c['Mounts']) for c in apps)
    assert json.loads(out(d+['inspect','myink-caddy']))[0]['Id']==caddy['Id']
    hosts=[c['Config']['Hostname'] for c in apps if c['Name'].startswith('/myink-myink-worker-')]
    probe='''import json,sys
from myink.worker.redis_client import get_redis
from myink.seed import STYLE_PRESETS
from myink.db import new_session
from myink.writing_resources import catalog
r=get_redis()
for h in sys.argv[1:]:
 assert any(r.ttl(k)>0 for k in r.scan_iter('queue:heartbeat:'+h+'-*')),h
with new_session() as db:
 current=catalog(db,include_automatic=True)
 retired={"style:xianxia-jiuzhou","style:changan-yexing","style:xingjian-yuanzheng","style:dushi-yiguan"}
 assert not retired.intersection(x['id'] for x in current)
 print(json.dumps({'worker_heartbeats':'ok','style_ids':[p['id'] for p in STYLE_PRESETS],'published_versions':{x['id']:x['current_version'] for x in current if x['id'] in '''+repr(upgrade|add)+'''}}))
'''
    verification=json.loads(out(d+['exec','-i','myink-api','python','-',*hosts],input=probe.encode()))
    assert set(verification['style_ids'])=={'uncanny-gloom', 'restrained-suspense', 'life-narration', 'rational-realist', 'epic-scope', 'character-narration', 'light-humor', 'warm-fresh', 'romantic-tension', 'heroic-action', 'poetic-imagery', 'natural-narration', 'brisk-narration', 'classical-elegance'}
    assert verification['published_versions']=={**{rid:2 for rid in upgrade},**{rid:1 for rid in add}}
    receipt={'revision':revision,'url':'https://myink.cloud','health':health(),'frontend_container_unchanged':True,'frontend_revision':caddy['Config']['Labels']['org.opencontainers.image.revision'],'checks':verification,'transaction':report,'unrelated_current_resources_unchanged':len(resources)-len(upgrade)-len(retire),'existing_resource_history_unchanged':True,'protected_tables_unchanged_during_migration':tables,'backup_verified':True}
    (state/'verification.json').write_text(json.dumps(receipt,indent=2)); print(json.dumps(receipt),flush=True)
except BaseException:
    if changed:
        run(compose+['stop','-t','120','myink-api']); run(compose+['stop','-t','120','myink-worker'])
        try:
            current_resources=keyed(sql(resource_sql))
            if catalog_attempted and resources is not None:
                catalog_changed=current_resources!=resources
                if catalog_changed:
                    assert after is not None and current_resources==after,'Catalog changed outside the verified release state'
            assert active()==0; queues_empty()
            assert protected_before is None or protected()==protected_before
        except BaseException:
            # Preserve any post-start deliveries/author writes. Do not restore DB.
            if catalog_changed: run(d+['tag',image,'myink-api:local'])
            run(compose+['up','-d','--no-deps','--no-build','--scale','myink-worker=2','myink-worker','myink-api'])
            print('Kept candidate backend/catalog to preserve new work; manual inspection required',file=sys.stderr); raise
        if catalog_changed:
            # Only current definitions are rolled back; preserve all immutable
            # history and use fresh generations to avoid future CAS collisions.
            rollback=prelude+"""from copy import deepcopy
from myink.models.writing_resource import WritingResource
from myink.writing_resources import update_resource,publish,cas
with Session(get_admin_engine()) as db:
 for rid in sorted(UPGRADE):
  row=db.get(WritingResource,rid,with_for_update=True)
  target={k:expected[rid][k] for k in FIELDS}
  row=update_resource(db,rid,row.generation,target)
  publish(db,rid,row.generation,'Rollback failed craft rollout',version=1)
 for rid in sorted(ADD):
  row=db.get(WritingResource,rid,with_for_update=True)
  assert row is not None
  cas(db,row,row.generation,dict(status='draft'))
 for rid in sorted(RETIRE):
  assert db.get(WritingResource,rid) is None
  old=db.get(__import__('myink.models.writing_resource',fromlist=['WritingResourcePublication']).WritingResourcePublication,(rid,1))
  assert old is not None
  doc=old.document
  db.add(WritingResource(id=rid,**{k:deepcopy(doc[k]) for k in FIELDS},status='published',generation=1,current_version=1,publication=deepcopy(doc)))
 db.commit()
print('Previous current definitions restored; publication history preserved')
"""
            run(candidate+['run','--rm','--no-deps','-T','--entrypoint','python','myink-migrate','-'],input=rollback.encode())
        run(d+['tag',old,'myink-api:local'])
        run(compose+['up','-d','--no-deps','--no-build','--scale','myink-worker=2','myink-worker','myink-api'])
        for _ in range(40):
            try:
                if health()['status']=='ok': break
            except Exception: pass
            time.sleep(2)
        else: raise RuntimeError('Previous backend restart did not become ready')
        restored=json.loads(out(d+['inspect','myink-api','myink-myink-worker-1','myink-myink-worker-2']))
        assert all(c['State']['Running'] and c['Image']==old for c in restored),'Rollback image mismatch'
        oldhosts=[c['Config']['Hostname'] for c in restored if c['Name'].startswith('/myink-myink-worker-')]
        heartbeat_check="from myink.worker.redis_client import get_redis\nimport sys\nr=get_redis()\nfor h in sys.argv[1:]:\n assert any(r.ttl(k)>0 for k in r.scan_iter('queue:heartbeat:'+h+'-*')),h\n"
        run(d+['exec','-i','myink-api','python','-',*oldhosts],input=heartbeat_check.encode())
        assert json.loads(out(d+['inspect','myink-caddy']))[0]['Id']==caddy['Id']
        (state/'rollback-verification.json').write_text(json.dumps({'old_image':old,'ready':health(),'worker_heartbeats':'ok'}))
        print('Previous backend readiness/images/heartbeats verified; no database dump restoration',file=sys.stderr)
    raise
