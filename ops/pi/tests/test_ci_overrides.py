"""Run local CI against fake executables to verify overrides without any service."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def test_ci_project_ports_urls_and_skip_are_real_overrides(tmp_path):
    script = Path(__file__).parents[3] / 'scripts/ci-local.sh'
    fake = tmp_path / 'bin'
    fake.mkdir()
    log = tmp_path / 'commands.log'
    child = '#!/bin/sh\nprintf "%s|" "$0" "$@" >> "$B12_LOG"\nprintf "\\n" >> "$B12_LOG"\nprintf "%s\\n" "$DATABASE_URL,$ADMIN_DATABASE_URL,$REDIS_URL,$REDIS_ADDR,$AMQP_URL" >> "$B12_LOG"\n'
    for name in ('docker', 'python', 'myink', 'git', 'npm'):
        path = fake / name
        path.write_text(child)
        path.chmod(0o755)
    bash = 'D:/git/Git/bin/bash.exe' if sys.platform == 'win32' else shutil.which('bash')
    assert bash and Path(bash).exists(), 'Bash is required for the changed CI script'
    env = {**os.environ, 'B12_FAKE_ROOT': str(fake), 'B12_LOG': str(log),
           'MYINK_TEST_PROJECT': 'myinkpi-test-owned', 'MYINK_TEST_PG_PORT': '25432',
           'MYINK_TEST_REDIS_PORT': '26380', 'MYINK_TEST_RABBIT_PORT': '25673',
           'MYINK_TEST_DATABASE_URL': 'postgresql+psycopg://myink_app:synthetic@127.0.0.1:25432/myink',
           'MYINK_TEST_ADMIN_DATABASE_URL': 'postgresql+psycopg://myink:synthetic@127.0.0.1:25432/myink',
           'MYINK_TEST_REDIS_URL': 'redis://127.0.0.1:26380/0', 'SKIP_IMAGES': '1'}
    command = 'if command -v cygpath >/dev/null; then fake=$(cygpath -u "$B12_FAKE_ROOT"); else fake=$B12_FAKE_ROOT; fi; export PATH="$fake:$PATH"; exec bash "$1"'
    result = subprocess.run([bash, '-c', command, 'b12', str(script)], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    recorded = log.read_text()
    assert '-p|myinkpi-test-owned|' in recorded
    assert 'myink_app:synthetic@127.0.0.1:25432/myink' in recorded
    assert 'redis://127.0.0.1:26380/0,127.0.0.1:26380,amqp://myink:myink@127.0.0.1:25673/' in recorded
    assert 'down|--volumes|' in recorded
    assert '全部通过' not in result.stdout