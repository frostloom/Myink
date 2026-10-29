"""Actual Caddy local-CA TLS/cache/SSE against actual queue-worker events."""
import json,time
from pathlib import Path
import httpx
m=json.loads(Path('/tmp/myink-vue-chain-metadata-0025.json').read_text());headers={}
ca='/tmp/myink-vue-chain-ca-0025.crt';tls='https://localhost:28443';plain='http://127.0.0.1:28080'
c=httpx.Client(verify=ca,trust_env=False,timeout=90);checks=[]
login=c.post(tls+'/api/v1/auth/token',json={'username':m['user']['username'],'password':m['password']});assert login.status_code==200 and 'token' in login.json()
headers={'Authorization':'Bearer '+login.json()['token']}
m['tokens']['user']=login.json()['token']
def ok(name):checks.append(name);print(name,flush=True)
for origin in [plain,tls]:
    r=c.get(origin+'/projects/'+m['longProjectId']);assert r.status_code==200 and '/assets/index-' in r.text
    assert 'no-store' in r.headers.get('cache-control','') or 'no-cache' in r.headers.get('cache-control','')
    import re
    asset=re.search(r'src="(/assets/index-[^"]+\.js)"',r.text).group(1)
    assert 'immutable' in c.get(origin+asset).headers['cache-control']
    r=c.get(origin+'/api/not-v1');assert r.status_code==404 and r.json()['error']=='not_found'
    r=c.get(origin+'/api/v1/auth/session',headers=headers);assert r.status_code==200 and r.json()['username']==m['user']['username']
ok('caddy_http_and_trusted_local_ca_tls_deep_link_cache_api')
chapters=c.get(tls+f'/api/v1/projects/{m["longProjectId"]}/chapters',headers=headers);assert chapters.status_code==200
next_seq=max(chapter['chapter_seq'] for chapter in chapters.json())+1
r=c.post(tls+f'/api/v1/projects/{m["longProjectId"]}/chapters/next/generate',headers=headers,json={'seq':next_seq,'mode':'auto'});assert r.status_code==202,(r.status_code,r.text);tid=r.json()['task_id']
for _ in range(150):
    r=c.get(tls+'/api/v1/tasks/'+tid,headers=headers)
    if r.status_code==200:break
    assert r.status_code==404;time.sleep(.2)
else:raise AssertionError('worker did not materialize task')
frames=[];last=None;first_delta=None;terminal=None;stream_started=time.monotonic()
with c.stream('GET',tls+'/api/v1/tasks/'+tid+'/events',headers=headers) as response:
    assert response.status_code==200,(response.status_code,response.read())
    assert response.headers['content-type'].startswith('text/event-stream')
    assert 'content-encoding' not in response.headers
    for line in response.iter_lines():
        assert time.monotonic()-stream_started<120,'SSE terminal deadline exceeded'
        if line.startswith('id:'):last=line[3:].strip()
        if line.startswith('data:'):
            event=json.loads(line[5:].strip());frames.append({'id':last,'type':event.get('type'),'at':time.monotonic(),'status':event.get('status')})
            if event.get('type')=='artifact_delta' and first_delta is None:first_delta=time.monotonic()
            if event.get('type')=='status' and event.get('status')=='done':terminal=time.monotonic();break
assert first_delta and terminal and terminal-first_delta>.1,(first_delta,terminal)
deltas=[f for f in frames if f['type']=='artifact_delta'];assert len(deltas)>3
ok('actual_worker_sse_stream_through_tls_is_incremental_uncompressed')
# Regression replay uses the authentic original worker stream that exposed the bug.
# The observer's one-second sampling makes a post-done tail nondeterministic on new fast tasks.
import redis
rdb=redis.Redis(host='127.0.0.1',port=28380,db=0,decode_responses=True)
regression_tid='41d8e6f7-dd07-484f-8c05-9ee4cb2a3c38'
stored=rdb.xrange('queue:sse:'+regression_tid)
assert len(stored)==59,'original real-worker regression stream missing or changed'
done_index=next(i for i,(_,event) in enumerate(stored) if event.get('event')=='status' and event.get('status')=='done')
post_done_nodes=[event.get('node') for _,event in stored[done_index+1:] if event.get('event')=='node']
assert 'summarize' in post_done_nodes,'authentic post-done summarize tail missing'
legacy_deltas=[sid for sid,event in stored if event.get('event')=='artifact_delta']
assert len(legacy_deltas)>3
cursor=legacy_deltas[len(legacy_deltas)//2];replayed=[];last=None;stream_started=time.monotonic();replay_done=False
with c.stream('GET',tls+'/api/v1/tasks/'+regression_tid+'/events',headers={**headers,'Last-Event-ID':cursor}) as response:
    assert response.status_code==200
    for line in response.iter_lines():
        assert time.monotonic()-stream_started<15,'SSE replay terminal/EOF deadline exceeded'
        if line.startswith('id:'):last=line[3:].strip()
        if line.startswith('data:'):
            event=json.loads(line[5:].strip());replayed.append(last)
            if event.get('type')=='status' and event.get('status')=='done':replay_done=True
assert replay_done and replayed and cursor not in replayed
replay_seconds=time.monotonic()-stream_started
assert replay_seconds<15
ok('actual_tls_original_worker_done_then_summarize_replay_done_and_eof')
done_cursor=stored[done_index][0];tail_replayed=[];tail_started=time.monotonic();last=None
with c.stream('GET',tls+'/api/v1/tasks/'+regression_tid+'/events',headers={**headers,'Last-Event-ID':done_cursor}) as response:
    assert response.status_code==200
    for line in response.iter_lines():
        assert time.monotonic()-tail_started<15,'acknowledged-terminal tail EOF deadline exceeded'
        if line.startswith('id:'):last=line[3:].strip()
        if line.startswith('data:'):
            event=json.loads(line[5:].strip());tail_replayed.append({'id':last,'type':event.get('type'),'node':event.get('node'),'status':event.get('status')})
assert tail_replayed and all(event['id']>done_cursor and event['status']!='done' for event in tail_replayed)
assert any(event['node']=='summarize' for event in tail_replayed)
tail_seconds=time.monotonic()-tail_started;assert tail_seconds<15
ok('actual_tls_acknowledged_done_replays_only_new_node_tail_and_eof')
final=c.get(tls+'/api/v1/tasks/'+tid,headers=headers).json();assert final['status']=='done'
m['edgeTaskId']=tid;Path('/tmp/myink-vue-chain-metadata-0025.json').write_text(json.dumps(m,ensure_ascii=False))
Path('/tmp/myink-vue-chain-edge-receipt-0025.json').write_text(json.dumps({'checks':checks,'count':len(checks),'tls':'dedicated Caddy internal CA verified via its exported root, no system trust-store mutation','artifactDeltas':len(deltas),'firstDeltaToDoneSeconds':terminal-first_delta,'frameCount':len(frames),'replayFrames':len(replayed),'postDoneNodes':post_done_nodes,'taskId':tid,'regressionTaskId':regression_tid,'regressionOriginalFrames':len(stored),'replayToEofSeconds':replay_seconds,'acknowledgedDoneTail':tail_replayed,'tailToEofSeconds':tail_seconds},indent=2))
