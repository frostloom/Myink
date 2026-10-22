"""Bounded byte-preserving response frames across the container stdio pipe."""
import base64
import codecs

from .container_runtime import FRAME_LIMIT, strict_json

CHUNK_LIMIT = 16384
STREAM_LIMIT = 1048576
BODY_LIMIT = 65536
CHUNK_COUNT_LIMIT = 1024
STATUSES = (200, 400, 403, 429, 502)


class ReplyStream:
    """Own a lazy response, including closure of its upstream HTTP context."""
    def __init__(self, frames):
        self.frames = frames

    def close(self):
        self.frames.close()


def response_frames(status, chunks, remaining, progress):
    """No read-ahead: exchange writes each frame before requesting the next."""
    if type(status) is not int or status not in STATUSES:
        raise ValueError('invalid relay status')
    limit = STREAM_LIMIT if status == 200 else BODY_LIMIT
    total = count = 0
    decoder = codecs.getincrementaldecoder('utf-8')()
    yield dict(type='response_start', status=status)
    try:
        for raw in chunks:
            if remaining() <= 0:
                progress['reason'] = 'deadline_exceeded'
                raise TimeoutError('relay expired')
            if not isinstance(raw, bytes) or not 0 < len(raw) <= CHUNK_LIMIT:
                raise ValueError('bounded response chunk required')
            total += len(raw)
            progress['response_bytes'] = min(total, limit + 1)
            if total > limit:
                progress['reason'] = 'response_size_limit'
                raise ValueError('response byte limit')
            if count >= CHUNK_COUNT_LIMIT:
                progress['reason'] = 'response_chunk_limit'
                raise ValueError('response chunk limit')
            decoder.decode(raw, final=False)
            yield dict(type='response_chunk', seq=count, data=base64.b64encode(raw).decode('ascii'))
            count += 1
        decoder.decode(b'', final=True)
        if remaining() <= 0:
            progress['reason'] = 'deadline_exceeded'
            raise TimeoutError('relay expired')
        yield dict(type='response_end', chunks=count, bytes=total)
    except UnicodeDecodeError:
        progress['reason'] = 'invalid_utf8'
        raise


def receive_response(readline, start, write):
    """Validate independently before writing each bounded HTTP response chunk.

    A transport end does not establish SSE completion or known model usage.
    The caller must close HTTP on failure, never append another status line.
    """
    def read():
        raw = readline(FRAME_LIMIT + 1)
        if not raw.endswith(b'\n') or len(raw) > FRAME_LIMIT:
            raise ValueError('incomplete response frame')
        value = strict_json(raw)
        if not isinstance(value, dict):
            raise ValueError('response object required')
        return value

    first = read()
    status = first.get('status')
    if type(status) is not int or status not in STATUSES:
        raise ValueError('invalid response status')
    if set(first) == {'status', 'body'}:
        if not isinstance(first['body'], str):
            raise ValueError('legacy response text required')
        body = first['body'].encode('utf-8')
        if len(body) > BODY_LIMIT:
            raise ValueError('legacy response byte limit')
        start(status); write(body)
        return
    if set(first) != {'type', 'status'} or first['type'] != 'response_start':
        raise ValueError('response start required')
    limit = STREAM_LIMIT if status == 200 else BODY_LIMIT
    start(status)
    total = count = 0
    decoder = codecs.getincrementaldecoder('utf-8')()
    while True:
        item = read()
        if item.get('type') == 'response_end':
            if (set(item) != {'type', 'chunks', 'bytes'}
                    or type(item['chunks']) is not int or type(item['bytes']) is not int
                    or item['chunks'] != count or item['bytes'] != total):
                raise ValueError('response totals mismatch')
            decoder.decode(b'', final=True)
            return
        if (set(item) != {'type', 'seq', 'data'} or item.get('type') != 'response_chunk'
                or type(item['seq']) is not int or item['seq'] != count
                or count >= CHUNK_COUNT_LIMIT or not isinstance(item['data'], str)
                or len(item['data']) > 4 * ((CHUNK_LIMIT + 2) // 3)):
            raise ValueError('bounded ordered response chunk required')
        body = base64.b64decode(item['data'], validate=True)
        total += len(body)
        if not 0 < len(body) <= CHUNK_LIMIT or total > limit:
            raise ValueError('response byte limit')
        decoder.decode(body, final=False)
        write(body)
        count += 1
