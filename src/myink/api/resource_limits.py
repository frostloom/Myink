"""Bound resource request streams before JSON decoding, including chunked uploads."""
import re

from starlette.responses import JSONResponse

_RESOURCE_PATH = re.compile(
    r"^/api/v1/(?:admin/writing-resources|my-writing-resources|"
    r"projects/[^/]+/writing-resources)(?:/.*)?$"
)
MAX_REQUEST_BYTES = 8 * 1024 * 1024


class ResourceRequestLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope['type'] != 'http' or scope['method'] not in ('POST', 'PUT', 'PATCH')
                or not _RESOURCE_PATH.fullmatch(scope['path'])):
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        try:
            declared = int(headers.get(b'content-length', b'0'))
        except ValueError:
            declared = 0
        if declared > MAX_REQUEST_BYTES:
            response = JSONResponse({'detail': 'RESOURCE_REQUEST_TOO_LARGE'}, status_code=413,
                                    headers={'Cache-Control': 'no-store'})
            return await response(scope, receive, send)
        chunks = []
        received = 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            received += len(chunk)
            if received > MAX_REQUEST_BYTES:
                response = JSONResponse({'detail': 'RESOURCE_REQUEST_TOO_LARGE'}, status_code=413,
                                        headers={'Cache-Control': 'no-store'})
                return await response(scope, receive, send)
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        body = b''.join(chunks)
        chunks.clear()
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        await self.app(scope, bounded_receive, send)
