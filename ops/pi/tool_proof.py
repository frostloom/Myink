"""Unprivileged, read-only proof client. No ledger, proxy, redirect or retry path."""
import http.client
import json
import re
import socket
from threading import Timer
import time
from urllib.parse import urlsplit

CAP = 32768
NAMES = frozenset(('observe_metrics','read_source','propose_plan','apply_patch','run_check','candidate_status'))


def strict_json(raw):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('nonfinite JSON number')
    value = json.loads(raw, object_pairs_hook=object_pairs, parse_constant=invalid)
    json.dumps(value, allow_nan=False)  # Also reject a numeric exponent overflowing float.
    return value


def validate_proof(body):
    if (not isinstance(body, dict) or set(body) != {'call_id','name','arguments','receipt'}
            or not isinstance(body['call_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', body['call_id'])
            or not isinstance(body['name'], str) or body['name'] not in NAMES
            or not isinstance(body['arguments'], dict) or not isinstance(body['receipt'], dict)):
        raise ValueError('strict proof envelope required')
    return body


def proof_bytes(call_id, name, arguments, receipt):
    body = validate_proof(dict(call_id=call_id, name=name, arguments=arguments, receipt=receipt))
    raw = json.dumps(body, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')
    if len(raw) > CAP:
        raise ValueError('combined proof exceeds cap; never truncate fields')
    return raw


def verified_response(raw):
    try:
        body = strict_json(raw)
        return isinstance(body, dict) and set(body) == {'verified'} and body['verified'] is True
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return False


class ToolProofClient:
    def __init__(self, base_url, token, *, timeout=5):
        url = urlsplit(base_url)
        if (url.scheme != 'http' or url.hostname != '127.0.0.1' or url.path not in ('', '/')
                or url.query or url.fragment or url.username or url.password
                or not url.port or not 1 <= url.port <= 65535
                or not isinstance(token, str) or not re.fullmatch(r'[!-~]{1,4096}', token)
                or type(timeout) not in (int, float) or not 0 < timeout <= 10):
            raise ValueError('fixed loopback proof endpoint and bounded timeout required')
        self.port, self.token, self.timeout = url.port, token, timeout

    def __call__(self, call_id, name, arguments, receipt):
        connection = None; timer = None
        try:
            raw = proof_bytes(call_id, name, arguments, receipt)
            deadline = time.monotonic() + self.timeout
            connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=self.timeout)
            def expire():
                try:
                    if connection.sock:
                        connection.sock.shutdown(socket.SHUT_RDWR)
                    connection.close()
                except OSError:
                    pass
            timer = Timer(self.timeout, expire); timer.daemon = True; timer.start()
            connection.request('POST', '/v1/tool-proof', body=raw, headers={
                'Content-Type':'application/json', 'x-api-key':self.token, 'X-Pi-Scope':'local-trial-1'})
            response = connection.getresponse()
            lengths = response.headers.get_all('Content-Length', [])
            if (response.status != 200 or response.headers.get_all('Content-Type') != ['application/json']
                    or len(lengths) != 1 or not lengths[0].isdigit() or not 1 <= int(lengths[0]) <= 64
                    or response.headers.get('Transfer-Encoding')):
                return False
            result = response.read(65)
            return time.monotonic() < deadline and len(result) == int(lengths[0]) and verified_response(result)
        except (OSError, ValueError, TypeError, http.client.HTTPException, RecursionError):
            return False
        finally:
            if timer: timer.cancel()
            if connection: connection.close()
