"""Bounded synthetic Windows endpoint, started only by the trusted controller."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import os
import sys
from threading import Timer
import time

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'B7-controlled-host-endpoint')

state = Path(sys.argv[1])
if state.drive.lower() != 'e:' or not state.is_absolute() or '..' in state.parts:
    raise SystemExit('private E state required')
identity = json.loads((state / 'lab-env.json').read_text())
server = ThreadingHTTPServer(('0.0.0.0', 0), Handler)
receipt = {'pid': os.getpid(), 'port': server.server_port, 'started': time.time(),
           'owner': 'B7-controlled-probe', 'lab_uuid': identity['lab_uuid']}
(state.parent / 'evidence' / 'b7-host-server.json').write_text(json.dumps(receipt))
Timer(180, server.shutdown).start()
server.serve_forever()
server.server_close()
