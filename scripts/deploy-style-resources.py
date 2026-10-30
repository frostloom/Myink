"""Roll out a tested revision without reseeding or replacing author data.

Run on the production host after images, retained-assets.json and the captured
previous-caddy-image.txt are staged in releases/style-resources-<short>.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

revision = sys.argv[1]
assert re.fullmatch(r'[0-9a-f]{40}', revision)
short = revision[:8]
root = Path('/home/ubuntu/myink')
os.chdir(root)
os.umask(0o077)
state = root / 'releases' / ('style-resources-' + short)
assert state.is_dir() and state.stat().st_mode & 0o077 == 0
docker = ['sudo', '-n', 'docker']
compose = docker + ['compose', '-f', str(root / 'docker-compose.yml')]
api_image, web_image = 'myink-api:' + short, 'myink-caddy:' + short
old_api_tag = 'myink-api:before-style-resources-' + short
old_web_tag = 'myink-caddy:before-style-resources-' + short
fallback_web = 'myink-caddy:rollback-style-resources-' + short


def output(args, **kwargs):
    return subprocess.check_output(args, **kwargs)


def run(args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def sql(query):
    return output(docker + ['exec', 'myink-pg', 'psql', '-U', 'myink', '-d', 'myink', '-Atc', query]).decode().strip()


def active():
    return int(sql("SELECT count(*) FROM tasks WHERE status IN ('queued','running','retrying')"))


def check_queues():
    expected = {'queue:tasks', 'queue:delay', 'queue:tasks:vip', 'queue:delay:vip'}
    raw = output(docker + ['exec', 'myink-rabbitmq', 'rabbitmqctl', '-q', 'list_queues', 'name', 'messages_ready', 'messages_unacknowledged']).decode()
    seen = set()
    for line in raw.splitlines():
        cols = line.split()
        if len(cols) == 3 and cols[0] in expected:
            assert int(cols[1]) + int(cols[2]) == 0, 'Queued or unacknowledged deliveries'
            seen.add(cols[0])
    assert seen == expected, 'Expected queues are missing'


def ready():
    return json.load(urllib.request.urlopen('https://myink.cloud/readyz', timeout=10))


def wait_ready():
    for _ in range(40):
        try:
            if ready()['status'] == 'ok':
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError('Public readiness did not recover')


def inspect_image(name):
    return json.loads(output(docker + ['image', 'inspect', name]))[0]


def inspect_services():
    return json.loads(output(docker + ['inspect', 'myink-api', 'myink-myink-worker-1', 'myink-myink-worker-2']))


def copy_image_assets(image, destination):
    name = 'myink-style-assets-' + uuid.uuid4().hex[:12]
    attempted = False
    try:
        attempted = True
        run(docker + ['create', '--network', 'none', '--name', name, image], stdout=subprocess.DEVNULL)
        run(docker + ['cp', name + ':/srv/web/dist/assets/.', str(destination)])
        # Docker runs as root and may copy owner-only assets as root-owned files.
        # The release directory is private; let the deploy user verify its copy.
        run(['sudo', '-n', 'chown', '-R', f'{os.getuid()}:{os.getgid()}', str(destination)])
    finally:
        if attempted:
            removed = subprocess.run(docker + ['rm', '-f', '-v', name], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if removed.returncode and b'No such container' not in removed.stderr:
                raise RuntimeError('Unable to clean up the temporary asset container')


def protected(tables):
    return {name: sql('SELECT count(*),md5(COALESCE(string_agg(row_to_json(t)::text,\'|\' ORDER BY row_to_json(t)::text),\'\')) FROM "' + name + '" t') for name in tables}


def frontend_check():
    html = urllib.request.urlopen('https://myink.cloud/', timeout=10).read().decode()
    assert 'myink-release' in html
    paths = re.findall(r'(?:src|href)="(/assets/[A-Za-z0-9_.-]+)"', html)
    assert any(p.endswith('.js') for p in paths) and any(p.endswith('.css') for p in paths)
    for path in paths:
        remote = urllib.request.urlopen('https://myink.cloud' + path, timeout=15).read()
        local_hash = output(docker + ['exec', 'myink-caddy', 'sha256sum', '/srv/web/dist' + path]).decode().split()[0]
        assert hashlib.sha256(remote).hexdigest() == local_hash, 'Published asset differs from image'
    return {'entry_assets_verified': len(paths)}


def runtime_check():
    services = inspect_services()
    image_id = inspect_image(api_image)['Id']
    assert all(item['State']['Running'] and item['Image'] == image_id and item['Config']['Labels']['org.opencontainers.image.revision'] == revision for item in services)
    assert all(not any(m['Destination'] in ('/app', '/app/src') for m in item['Mounts']) for item in services)
    hosts = [item['Config']['Hostname'] for item in services if item['Name'].startswith('/myink-myink-worker-')]
    code = '''import json,sys,time
from sqlalchemy import select
from myink.api.routes_style import resource_style_choices,resolve_style_selection
from myink.db import new_session
from myink.models import User
from myink.models.writing_resource import PersonalWritingResource,WritingResource
from myink.worker.redis_client import get_redis
r=get_redis()
for attempt in range(20):
 if all(any(r.ttl(k)>0 for k in r.scan_iter('queue:heartbeat:'+h+'-*')) for h in sys.argv[1:]):
  break
 time.sleep(1)
else:
 raise RuntimeError('Worker heartbeats did not become ready')
with new_session() as db:
 users=list(db.scalars(select(User.id)))
 rows=list(db.scalars(select(WritingResource).where(WritingResource.kind=='style',WritingResource.status=='published',WritingResource.current_version.is_not(None))))
 platform={row.id for row in rows if isinstance((row.publication.get('body') or {}).get('profile'),dict)}
 count=0
 for uid in users:
  rows=list(db.scalars(select(PersonalWritingResource).where(PersonalWritingResource.user_id==uid,PersonalWritingResource.kind=='style',PersonalWritingResource.status=='published')))
  private={row.id for row in rows if isinstance((row.body or {}).get('profile'),dict)}
  options=resource_style_choices(db,uid)
  assert {o['resource_id'] for o in options if o['origin']=='platform'}==platform
  assert {o['resource_id'] for o in options if o['origin']=='personal'}==private
  for option in options:
   assert len(option['id'])<=48
  for option in options[:1]+[o for o in options if o['origin']=='personal'][:1]:
   assert resolve_style_selection(db,uid,option['id'])[0]==option['profile']
  count+=len(options)
print(json.dumps({'users_checked':len(users),'visible_style_choices_checked':count,'platform_style_count':len(platform),'worker_heartbeats':'ok'}))
'''
    result = json.loads(output(docker + ['exec', '-i', 'myink-api', 'python', '-', *hosts], input=code.encode()))
    assert result['platform_style_count'] >= 14
    try:
        urllib.request.urlopen('https://myink.cloud/api/v1/writing-resources/styles', timeout=10)
    except urllib.error.HTTPError as exc:
        assert exc.code in (401, 403)
    else:
        raise AssertionError('Style catalog did not require authentication')
    return result


api_meta, web_meta = inspect_image(api_image), inspect_image(web_image)
for meta in (api_meta, web_meta):
    assert meta['Architecture'] == 'amd64' and meta['Config']['Labels']['org.opencontainers.image.revision'] == revision
old_api = output(docker + ['inspect', '-f', '{{.Image}}', 'myink-api']).decode().strip()
old_web = output(docker + ['inspect', '-f', '{{.Image}}', 'myink-caddy']).decode().strip()
assert old_web == (state / 'expected-caddy-image.txt').read_text().strip(), 'Frontend changed since assets were captured'
assert inspect_image(old_api)['Config']['Labels']['org.opencontainers.image.revision'] == '3405ff9944e597c69ce8fafbafcf87b117ad8319'
assert all(item['State']['Running'] and item['Image'] == old_api for item in inspect_services())
assert sql("SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_class t ON t.oid=i.indrelid WHERE c.relname='uq_personal_resource_source' AND t.relname='personal_writing_resources' AND i.indisunique AND i.indisvalid AND pg_get_indexdef(c.oid) LIKE '%(user_id, source_resource_id)%'") == '1'
assert sql("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND ((table_name='project_writing_resources' AND column_name='dismissed') OR (table_name='short_creation_sessions' AND column_name='style_item_id'))") == '2'
assert active() == 0
check_queues()
run(docker + ['tag', old_api, old_api_tag])
run(docker + ['tag', old_web, old_web_tag])
# Build a rollback frontend with the old index and both old/new content hashes.
rollback_dir = state / 'rollback-frontend'
assets = rollback_dir / 'assets'
assets.mkdir(parents=True, exist_ok=False)
copy_image_assets(web_image, assets)
retained = json.loads((state / 'retained-assets.json').read_text())['files']
for name, expected in retained.items():
    path = assets / name
    assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'Prior frontend asset missing or changed'
(rollback_dir / 'Dockerfile').write_text('FROM ' + old_web_tag + '\nCOPY assets/ /srv/web/dist/assets/\n')
run(docker + ['build', '--platform', 'linux/amd64', '-t', fallback_web, str(rollback_dir)], stdout=subprocess.DEVNULL)
assert inspect_image(fallback_web)['Config']['Labels']['org.opencontainers.image.revision'] == 'a8a4361ec1a9d3b5b8aa82ffa081f006d542ed82'
with (state / 'attempt-started.json').open('x') as file:
    json.dump({'revision': revision, 'started_at': time.time()}, file)
(state / 'compose.before.yml').write_bytes((root / 'docker-compose.yml').read_bytes())
(state / 'environment.before').write_bytes((root / '.env').read_bytes())
tables = sql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
assert all(re.fullmatch('[a-z][a-z0-9_]*', name) for name in tables)
baseline = None
api_stopping = worker_stopping = candidate_started = frontend_started = False
try:
    api_stopping = True
    run(compose + ['stop', '-t', '120', 'myink-api'])
    assert active() == 0
    check_queues()
    worker_stopping = True
    run(compose + ['stop', '-t', '120', 'myink-worker'])
    assert active() == 0
    check_queues()
    baseline = protected(tables)
    (state / 'protected-before.json').write_text(json.dumps(baseline))
    with (state / 'database-before.dump').open('wb') as file:
        run(docker + ['exec', 'myink-pg', 'pg_dump', '-U', 'myink', '-d', 'myink', '-Fc'], stdout=file)
    assert (state / 'database-before.dump').stat().st_size > 0
    with (state / 'database-before.dump').open('rb') as file, (state / 'backup-manifest.txt').open('wb') as manifest:
        run(docker + ['exec', '-i', 'myink-pg', 'pg_restore', '--list'], stdin=file, stdout=manifest)
    assert protected(tables) == baseline, 'Database changed while services were stopped'
    run(docker + ['tag', api_image, 'myink-api:local'])
    candidate_started = True
    run(compose + ['up', '-d', '--no-deps', '--no-build', '--scale', 'myink-worker=2', 'myink-worker'])
    run(compose + ['up', '-d', '--no-deps', '--no-build', 'myink-api'])
    wait_ready()
    checks = runtime_check()
    run(docker + ['tag', web_image, 'myink-caddy:local'])
    frontend_started = True
    run(compose + ['up', '-d', '--no-deps', '--no-build', 'myink-caddy'])
    wait_ready()
    caddy = json.loads(output(docker + ['inspect', 'myink-caddy']))[0]
    assert caddy['State']['Running'] and caddy['Image'] == web_meta['Id']
    assert caddy['Config']['Labels']['org.opencontainers.image.revision'] == revision
    checks.update(frontend_check())
    receipt = {'revision': revision, 'url': 'https://myink.cloud', 'health': ready(), 'checks': checks,
               'previous_api': old_api, 'previous_frontend': old_web,
               'retained_previous_assets': len(retained), 'backup_verified': True,
               'database_unchanged_while_stopped': True, 'protected_tables': tables}
    (state / 'verification.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt), flush=True)
except BaseException:
    if frontend_started:
        # New pages may already be open. Keep their required new API available;
        # restore the old index while retaining both versions of hashed assets.
        run(docker + ['tag', api_image, 'myink-api:local'])
        run(docker + ['tag', fallback_web, 'myink-caddy:local'])
        run(compose + ['up', '-d', '--no-deps', '--no-build', '--scale', 'myink-worker=2', 'myink-worker', 'myink-api', 'myink-caddy'])
        wait_ready()
        checks = runtime_check()
        checks.update(frontend_check())
        (state / 'frontend-rollback-verification.json').write_text(json.dumps({'api_revision': revision, 'ready': ready(), 'checks': checks}))
        print('Kept the new backend and restored the compatible previous frontend; inspect before retrying', file=sys.stderr)
    elif not candidate_started:
        if worker_stopping:
            run(compose + ['up', '-d', '--no-deps', '--no-build', '--scale', 'myink-worker=2', 'myink-worker'])
        if api_stopping:
            run(compose + ['up', '-d', '--no-deps', '--no-build', 'myink-api'])
    else:
        run(compose + ['stop', '-t', '120', 'myink-api'])
        run(compose + ['stop', '-t', '120', 'myink-worker'])
        try:
            assert active() == 0
            check_queues()
            assert baseline is not None and protected(tables) == baseline
        except BaseException:
            # A new task or database write may depend on the new schema semantics.
            # Keep the new release; never restore the database over author work.
            run(docker + ['tag', api_image, 'myink-api:local'])
            run(docker + ['tag', web_image, 'myink-caddy:local'])
            run(compose + ['up', '-d', '--no-deps', '--no-build', '--scale', 'myink-worker=2', 'myink-worker', 'myink-api', 'myink-caddy'])
            print('Kept candidate release to preserve new work; manual inspection required', file=sys.stderr)
            raise
        run(docker + ['tag', old_api, 'myink-api:local'])
        run(docker + ['tag', fallback_web, 'myink-caddy:local'])
        run(compose + ['up', '-d', '--no-deps', '--no-build', '--scale', 'myink-worker=2', 'myink-worker', 'myink-api', 'myink-caddy'])
        wait_ready()
        restored = inspect_services()
        assert all(item['State']['Running'] and item['Image'] == old_api for item in restored)
        (state / 'rollback-verification.json').write_text(json.dumps({'old_api_image': old_api, 'ready': ready()}))
        print('Previous backend and compatible frontend restored; no database restore', file=sys.stderr)
    raise
