"""Fixed Unix-socket client for the human Pi control plane.

This module never opens the manager/fee stores and never runs host commands.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import uuid

import httpx

MAX_RESPONSE = 8 * 1024 * 1024


class PiConsoleUnavailable(RuntimeError):
    code = 'PI_CONSOLE_UNAVAILABLE'
    def __init__(self): super().__init__(self.code)


class PiConsoleNotConfigured(PiConsoleUnavailable):
    code = 'PI_CONSOLE_NOT_CONFIGURED'


class PiConsoleConflict(RuntimeError):
    pass


class PiConsoleNotFound(RuntimeError):
    pass


class PiConsoleClient:
    def __init__(self, socket_path: str, token_file: Path | str, *, transport=None):
        self.socket_path = socket_path
        self.token_file = Path(token_file)
        self.transport = transport

    def _credential(self):
        path = self.token_file
        try:
            if not path.is_absolute() or path.resolve() != path: raise ValueError()
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 256 or stat.S_IMODE(info.st_mode) not in (0o600, 0o640): raise ValueError()
                with os.fdopen(fd, 'rb', closefd=False) as stream: raw = stream.read(257)
            finally: os.close(fd)
            value = raw.decode('ascii').strip()
            if not 32 <= len(value) <= 256 or any(c.isspace() for c in value): raise ValueError()
            return value
        except (OSError, ValueError, UnicodeError): raise PiConsoleUnavailable() from None

    def call(self, method: str, path: str, *, params=None, body=None):
        get_paths = {'/v1/status', '/v1/runs', '/v1/events', '/v1/daily', '/v1/enhancements'}
        operation = False
        if path.startswith('/v1/operations/'):
            raw = path.removeprefix('/v1/operations/')
            try: operation = str(uuid.UUID(raw)) == raw
            except ValueError: pass
        if not (method == 'GET' and (path in get_paths or operation) or method == 'POST' and path == '/v1/decisions'):
            raise ValueError('Invalid local console endpoint')
        socket_path = Path(self.socket_path)
        if not socket_path.is_absolute() or socket_path.resolve() != socket_path: raise PiConsoleUnavailable()
        credential = self._credential()
        transport = self.transport or httpx.HTTPTransport(uds=str(socket_path), retries=0)
        try:
            with httpx.Client(transport=transport, base_url='http://pi-console', timeout=httpx.Timeout(10, connect=3), trust_env=False, follow_redirects=False) as client:
                with client.stream(method, path, params=params, json=body, headers={'X-Pi-Console-Token': credential}) as response:
                    if response.status_code == 409: raise PiConsoleConflict()
                    if response.status_code == 404: raise PiConsoleNotFound()
                    if not 200 <= response.status_code < 300: raise PiConsoleUnavailable()
                    length = response.headers.get('Content-Length')
                    if length is not None and not 0 <= int(length) <= MAX_RESPONSE: raise PiConsoleUnavailable()
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE: raise PiConsoleUnavailable()
            def invalid(_): raise ValueError('Invalid console JSON')
            data = json.loads(raw, parse_constant=invalid)
            if not isinstance(data, dict): raise ValueError()
            return data
        except (httpx.HTTPError, OSError, ValueError, RecursionError): raise PiConsoleUnavailable() from None
