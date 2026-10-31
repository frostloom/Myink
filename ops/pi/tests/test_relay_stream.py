"""Bounded real protocol operations; no model, Docker or real ledger."""
import base64
import importlib
import io
import json

import pytest


def api():
    assert importlib.util.find_spec('ops.pi.relay_stream'), 'stream relay protocol missing'
    return importlib.import_module('ops.pi.relay_stream')


def receive(frames):
    raw=io.BytesIO(b''.join(json.dumps(f).encode()+b'\n' for f in frames))
    statuses=[];body=[]
    api().receive_response(raw.readline,statuses.append,body.append)
    return statuses,b''.join(body)


def frame(data,seq=0):
    return dict(type='response_chunk',seq=seq,data=base64.b64encode(data).decode())


def test_stream_is_incremental_preserves_bytes_and_supports_large_sse():
    consumed=[]
    def chunks():
        for i in range(5):
            consumed.append(i);yield b'x'*16384
    progress={}
    stream=api().response_frames(200,chunks(),lambda:10,progress)
    assert next(stream)==dict(type='response_start',status=200)
    assert consumed==[]
    first=next(stream)
    assert consumed==[0] and base64.b64decode(first['data'])==b'x'*16384
    assert receive([dict(type='response_start',status=200),first,*stream])==([200],b'x'*81920)
    assert progress['response_bytes']==81920


def test_utf8_can_cross_boundaries_without_transformation():
    raw='你好\n'.encode()
    assert receive(api().response_frames(200,iter([raw[:1],raw[1:5],raw[5:]]),lambda:10,{}))==([200],raw)


@pytest.mark.parametrize('chunks',[[b'\xff'],[b'\xe4']])
def test_invalid_or_incomplete_utf8_has_bounded_reason(chunks):
    progress={}
    with pytest.raises(UnicodeDecodeError):list(api().response_frames(200,iter(chunks),lambda:10,progress))
    assert progress['reason']=='invalid_utf8'


@pytest.mark.parametrize('status,limit',[(200,1048576),(403,65536)])
def test_aggregate_bytes_not_just_frame_size_are_limited(status,limit):
    progress={}
    with pytest.raises(ValueError):
        list(api().response_frames(status,iter([b'x'*16384]*(limit//16384)+[b'x']),lambda:10,progress))
    assert progress['response_bytes']==limit+1 and progress['reason']=='response_size_limit'


def test_many_tiny_chunks_are_finite():
    with pytest.raises(ValueError):list(api().response_frames(200,iter([b'x']*1025),lambda:10,{}))


@pytest.mark.parametrize('frames',[
    [dict(type='response_start',status=True)],
    [dict(type='response_start',status=201)],
    [dict(type='response_start',status=200)],
    [dict(type='response_start',status=200),frame(b'x',1)],
    [dict(type='response_start',status=200),frame(b'')],
    [dict(type='response_start',status=200),dict(type='response_chunk',seq=0,data='!')],
    [dict(type='response_start',status=200),frame(b'x'*16385)],
    [dict(type='response_start',status=200),frame(b'x'),dict(type='response_end',chunks=1,bytes=2)],
    [dict(type='response_start',status=200),frame(b'\xe4'),dict(type='response_end',chunks=1,bytes=1)],
    [dict(type='response_start',status=200),dict(type='response_start',status=200)],
])
def test_receiver_rejects_malformed_truncated_and_drifting_protocol(frames):
    with pytest.raises(ValueError):receive(frames)


def test_receiver_independently_enforces_total_and_chunk_limits():
    for chunks in ([frame(b'x'*16384,i) for i in range(65)], [frame(b'x',i) for i in range(1025)]):
        with pytest.raises(ValueError):receive([dict(type='response_start',status=200),*chunks])


def test_legacy_reply_stays_bounded():
    assert receive([dict(status=403,body='denied')])==([403],b'denied')
    with pytest.raises(ValueError):receive([dict(status=200,body='x'*65537)])


def test_exchange_streams_into_real_child_with_bounded_frames():
    import subprocess,sys
    from ops.pi.container_runtime import exchange
    script='''import sys,json
from ops.pi.relay_stream import receive_response
sys.stdin.readline()
print(json.dumps(dict(type='request',path='/v1/messages',headers=[['x-api-key','synthetic']],body='{}')),flush=True)
size=[0]
receive_response(sys.stdin.buffer.readline,lambda s:None,lambda b:size.__setitem__(0,size[0]+len(b)))
print(json.dumps(dict(type='result',result=dict(size=size[0]),session='',runtime={})),flush=True)
'''
    child=subprocess.Popen([sys.executable,'-u','-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        result=exchange(child,{},lambda f,s:api().ReplyStream(api().response_frames(200,iter([b'x'*16384]*5),lambda:10,{})),seconds=3)
        assert result['result']==dict(size=81920)
    finally:
        child.kill();child.wait();child.stdin.close();child.stdout.close()


def test_exchange_closes_lazy_response_when_child_closes_pipe():
    import subprocess,sys
    from ops.pi.container_runtime import exchange
    closed=[]
    def frames():
        try:
            yield dict(type='response_start',status=200)
            for i in range(100):yield frame(b'x'*16384,i)
        finally:closed.append(True)
    script='''import sys,json,os,time
sys.stdin.readline()
print(json.dumps(dict(type='request',path='/v1/messages',headers=[['x-api-key','synthetic']],body='{}')),flush=True)
os.close(0)
time.sleep(.1)
'''
    child=subprocess.Popen([sys.executable,'-u','-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        with pytest.raises((BrokenPipeError,ValueError)):
            exchange(child,{},lambda f,s:api().ReplyStream(frames()),seconds=3)
        assert closed==[True]
    finally:
        child.kill();child.wait();child.stdin.close();child.stdout.close()


@pytest.mark.parametrize('bad_end',[False,True])
def test_worker_serves_stream_over_real_loopback_without_appending_error(bad_end):
    from http.server import HTTPServer
    from threading import Thread
    import httpx
    from ops.pi.lab.container_runtime_worker import relay_handler
    chunks=[b'\xe4',b'\xbd\xa0'+b'x'*16381]+[b'x'*16384]*4
    frames=list(api().response_frames(200,iter(chunks),lambda:10,{}))
    if bad_end:frames[-1]['bytes']+=1
    source=io.BytesIO(b''.join(json.dumps(f).encode()+b'\n' for f in frames))
    emitted=[]
    with HTTPServer(('127.0.0.1',0),relay_handler(emitted.append,source.readline)) as server:
        thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.01});thread.start()
        try:
            with httpx.Client(trust_env=False) as client:
                reply=client.post(f'http://127.0.0.1:{server.server_port}/v1/messages',headers={'x-api-key':'synthetic'},content=b'{}')
            assert reply.status_code==200 and reply.content==b''.join(chunks)
            assert 'content-length' not in reply.headers and reply.headers['connection']=='close'
            assert len(emitted)==1 and emitted[0]['body']=='{}'
            assert b'HTTP/1.' not in reply.content and b'Error' not in reply.content
        finally:server.shutdown();thread.join()
