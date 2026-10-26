"""Check a built API's source, tested core versions, contract and boot without services."""
import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import tomllib
import uuid
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--image', required=True)
parser.add_argument('--docker', default='docker')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
requirements = tomllib.loads((root / 'pyproject.toml').read_text())['project']['dependencies']
names = {re.match(r'[A-Za-z0-9_.-]+', item).group() for item in requirements}
names.update({'starlette', 'pydantic-core', 'langchain-core', 'psycopg-binary'})
expected = {
    'source': hashlib.sha256((root / 'src/myink/api/routes_sse.py').read_bytes()).hexdigest(),
    'spec': hashlib.sha256((root / 'spec/api-openapi.json').read_bytes()).hexdigest(),
    'versions': {name: importlib.metadata.version(name) for name in sorted(names)},
}
payload = '''import hashlib, importlib.util, importlib.metadata, json, pathlib, sys
expected = json.loads(sys.argv[1])
source = hashlib.sha256(pathlib.Path(importlib.util.find_spec('myink.api.routes_sse').origin).read_bytes()).hexdigest()
assert source == expected['source'], 'API image does not contain the tested SSE source'
versions = {name: importlib.metadata.version(name) for name in expected['versions']}
assert versions == expected['versions'], f'Core runtime versions differ from the tested environment: {versions}'
from myink.api.main import app
spec = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + '\\n'
assert hashlib.sha256(spec.encode()).hexdigest() == expected['spec'], 'OpenAPI contract drift in image'
from fastapi.testclient import TestClient
with TestClient(app) as client:
    response = client.get('/healthz')
    assert response.status_code == 200 and response.json() == {'status': 'ok'}
print(json.dumps({'sourceSha256': source, 'coreVersions': versions, 'paths': len(app.openapi()['paths']), 'healthz': 200}))
'''
container = 'myink-api-image-smoke-' + uuid.uuid4().hex[:12]
receipt = {'kind': 'isolated_api_image_smoke', 'image': args.image, 'passed': False, 'cleanupErrors': []}
created = False

def docker(*command):
    return subprocess.run([args.docker, *command], capture_output=True, text=True, timeout=60, check=True).stdout.strip()

try:
    metadata = json.loads(docker('image', 'inspect', args.image))[0]
    receipt['imageId'] = metadata['Id']
    receipt['revision'] = metadata['Config'].get('Labels', {}).get('org.opencontainers.image.revision')
    # A failed/timed-out CLI may already have created the named container.
    created = True
    docker('create', '--init', '--name', container, '--network', 'none', '-e', 'APP_ENV=test',
           '-e', 'JWT_SECRET=test-jwt-secret-at-least-32-bytes-long', '-e', 'RANKINGS_ENABLED=0',
           '--entrypoint', 'python', args.image, '-c', payload, json.dumps(expected))
    output = docker('start', '-a', container)
    assert docker('inspect', '--format', '{{.State.ExitCode}}', container) == '0'
    receipt['runtime'] = json.loads(output)
    receipt['passed'] = True
except Exception as exc:
    receipt['error'] = str(exc)
    if isinstance(exc, subprocess.CalledProcessError):
        receipt['stderr'] = (exc.stderr or '')[-1800:]
finally:
    if created:
        try:
            docker('rm', '-f', '-v', container)
        except Exception as exc:
            receipt['cleanupErrors'].append(str(exc))
            receipt['passed'] = False
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'passed': receipt['passed'], 'output': str(args.output), 'cleanupErrors': receipt['cleanupErrors']}))
raise SystemExit(0 if receipt['passed'] else 1)
