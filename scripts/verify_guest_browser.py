"""Verify the built guest UI with an isolated real API, without model calls.

Source a dedicated test-service environment, then run with --output DIR.
Only loopback PostgreSQL on a non-default port and APP_ENV=test are accepted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

from sqlalchemy import delete
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def check_environment():
    assert os.environ.get('APP_ENV') == 'test', 'APP_ENV must be test'
    assert os.environ.get('PYTHON_DOTENV_DISABLED') == '1', 'Disable dotenv before running'
    for name in ('DATABASE_URL', 'ADMIN_DATABASE_URL'):
        url = make_url(os.environ[name])
        assert url.host in ('localhost', '127.0.0.1') and url.port not in (None, 5432), name


def fixture(metadata_path, action):
    from myink.db import new_session
    from myink.guest_quota import reserve
    from myink.guests import ip_key
    from myink.invitations import create_invitation
    from myink.models import (GuestQuotaBucket, GuestQuotaOperation, Invitation,
                              Project, User)

    metadata = json.loads(metadata_path.read_text())
    if action == 'prepare':
        with new_session() as db:
            invitation, code = create_invitation(db, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
            metadata.update(invitationId=str(invitation.id), invitation=code)
            metadata_path.write_text(json.dumps(metadata))
            db.commit()
    elif action == 'seed':
        with new_session() as db:
            for index, uid in enumerate(metadata['users']):
                project = Project(user_id=uuid.UUID(uid), title=f'真实游客隔离作品{index + 1}',
                                  genre='悬疑', target_words=10000, form='long')
                db.add(project)
                db.flush()
                metadata.setdefault('projects', []).append(str(project.id))
            db.commit()
        for dimension, amount in (('short', 1), ('long', 3)):
            reserve(user_id=metadata['users'][0], client_ip=metadata['ip'], dimension=dimension,
                    amount=amount, operation_id=str(uuid.uuid4()), task_id=str(uuid.uuid4()))
    elif action == 'cleanup':
        ids = [uuid.UUID(uid) for uid in metadata.get('users', [])]
        with new_session() as db:
            db.execute(delete(Project).where(Project.user_id.in_(ids)))
            db.execute(delete(User).where(User.id.in_(ids)))
            db.execute(delete(GuestQuotaOperation).where(GuestQuotaOperation.user_id.in_(ids)))
            db.execute(delete(GuestQuotaBucket).where(GuestQuotaBucket.ip_key == ip_key(metadata['ip'])))
            if metadata.get('invitationId'):
                db.execute(delete(Invitation).where(Invitation.id == uuid.UUID(metadata['invitationId'])))
            db.commit()
            assert not db.query(User).filter(User.id.in_(ids)).count()
            assert not db.query(Project).filter(Project.user_id.in_(ids)).count()
        return
    metadata_path.write_text(json.dumps(metadata))


def stop_child(child):
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=10)


def run_browser(environment, output):
    command = ['node', 'web/scripts/guest-real-browser.mjs', '--output', str(output)]
    child = subprocess.Popen(command, cwd=ROOT, env=environment)
    try:
        try:
            code = child.wait(timeout=180)
        except subprocess.TimeoutExpired:
            receipt_path = output / 'receipt.json'
            receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {'kind': 'guest_real_isolated_api_browser'}
            receipt.update(passed=False, error='Browser verifier exceeded its 180-second deadline')
            receipt_path.write_text(json.dumps(receipt, indent=2))
            raise
        if code:
            raise subprocess.CalledProcessError(code, command)
    finally:
        stop_child(child)


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='myink-guest-real-private-') as private:
        metadata_path = Path(private) / 'metadata.json'
        metadata_path.write_text(json.dumps({'ip': f'2001:db8:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::1', 'users': []}))
        api = None
        try:
            fixture(metadata_path, 'prepare')
            with socket.socket() as listener, (output / 'api.log').open('w') as log:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
                environment = {**os.environ, 'MYINK_GUEST_METADATA': str(metadata_path),
                               'MYINK_GUEST_REAL_API': f'http://127.0.0.1:{port}',
                               'MYINK_GUEST_PYTHON': sys.executable}
                api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'myink.api.main:app', '--fd', str(listener.fileno())],
                                       cwd=ROOT, env=environment, pass_fds=(listener.fileno(),), stdout=log, stderr=log)
                deadline = time.monotonic() + 30
                while True:
                    try:
                        urllib.request.urlopen(environment['MYINK_GUEST_REAL_API'] + '/healthz', timeout=1).close()
                        break
                    except Exception:
                        if api.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError('Isolated API did not start; see api.log')
                        time.sleep(.2)
                run_browser(environment, output)
        finally:
            try:
                stop_child(api)
            finally:
                fixture(metadata_path, 'cleanup')
                (output / 'cleanup.json').write_text(json.dumps({'fixtureAccountsRemoved': True, 'apiStopped': api is None or api.poll() is not None}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--fixture', choices=('seed',))
    parser.add_argument('--metadata', type=Path)
    args = parser.parse_args()
    check_environment()
    if args.fixture:
        fixture(args.metadata, args.fixture)
        return
    verify((args.output or Path(tempfile.mkdtemp(prefix='myink-guest-real-'))).resolve())


if __name__ == '__main__':
    main()
