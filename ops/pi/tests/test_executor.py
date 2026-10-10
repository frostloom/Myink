from datetime import datetime, timezone, timedelta
import pytest
from ops.pi.executor import execute, safe_source, sandbox_environment, validate_daemon

def test_unknown_command_rejected():
    assert execute('shell', {'command': 'echo unsafe'}, datetime.now(timezone.utc) + timedelta(seconds=30), None).status == 'blocked'

@pytest.mark.parametrize('path', ['../secret', '/secret'])
def test_path_escape_and_symlink_rejected(tmp_path, path):
    with pytest.raises(ValueError):
        safe_source(tmp_path, path)

def test_symlink_rejected(tmp_path):
    link = tmp_path / 'link'
    try:
        link.symlink_to(tmp_path.parent, target_is_directory=True)
    except OSError:
        import subprocess
        subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(tmp_path.parent)], check=True, capture_output=True)
    with pytest.raises(ValueError):
        safe_source(tmp_path, 'link/secret')

def test_secret_env_not_inherited():
    assert 'PLATFORM_MODEL_API_KEY' not in sandbox_environment({'PLATFORM_MODEL_API_KEY': 'never-forward', 'EMBED_ENABLED': '0'})

def test_foreign_docker_target_rejected():
    assert validate_daemon('private-daemon', {'ID': 'foreign-daemon', 'CgroupVersion': '2', 'CgroupDriver': 'systemd'}) is False

def test_missing_cgroup_proof_blocks_execution():
    assert execute('test', {}, datetime.now(timezone.utc) + timedelta(seconds=30), None).status == 'blocked'
