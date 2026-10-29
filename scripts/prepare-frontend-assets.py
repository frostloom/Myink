"""Retain public hashed assets from explicit prior frontend images before switching.

Only creates stopped, isolated temporary containers. Never starts an application
or mounts a running container's data/certificate volumes. Existing assets merge
by content and are never silently overwritten.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--image', action='append', required=True)
parser.add_argument('--docker', default='docker')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
destination = root / 'caddy' / 'retained-assets'
destination.mkdir(parents=True, exist_ok=True)

def docker(*command):
    return subprocess.check_output([args.docker, *command], text=True, stderr=subprocess.PIPE, timeout=60).strip()

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

receipt = {'kind': 'retained_public_frontend_assets', 'images': [], 'files': {}}
for image in args.image:
    identity = docker('image', 'inspect', '--format', '{{.Id}}', image)
    container = f'myink-retain-assets-{uuid.uuid4().hex[:12]}'
    created = False
    with tempfile.TemporaryDirectory(prefix='myink-retain-assets-') as temporary:
        try:
            # The daemon may create the container before the CLI fails/times out.
            created = True
            docker('create', '--init', '--network', 'none', '--name', container, identity)
            docker('cp', f'{container}:/srv/web/dist/assets/.', temporary)
            for source in Path(temporary).rglob('*'):
                if source.is_symlink():
                    raise ValueError('Hashed frontend assets must not contain symlinks')
                if not source.is_file():
                    continue
                relative = source.relative_to(temporary)
                target = destination / relative
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ValueError('Asset path escapes the retained directory')
                checksum = digest(source)
                if target.exists() and digest(target) != checksum:
                    raise ValueError(f'Existing asset content differs: {relative}')
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copyfile(source, target)
                receipt['files'][str(relative)] = checksum
            receipt['images'].append({'image': image, 'id': identity})
        finally:
            if created:
                try:
                    docker('rm', '-f', '-v', container)
                except subprocess.CalledProcessError as exc:
                    # A create rejected before allocation leaves nothing to remove.
                    # Other daemon/cleanup errors must still make the gate fail.
                    if not any(message in (exc.stderr or '') for message in
                               ('No such container:', 'No such object:')):
                        raise
print(json.dumps(receipt, indent=2))
