"""The scheduled observer verifies its closed source tree before imports."""
import importlib.util
import json
import os
from hashlib import sha256
from pathlib import Path
import pytest


def module():
    path=Path(__file__).parents[1]/'deploy/observer_entry.py'
    spec=importlib.util.spec_from_file_location('observer_entry_test',path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


@pytest.fixture
def release(tmp_path):
    (tmp_path/'code').mkdir();(tmp_path/'code/known.py').write_text('value=1\n')
    files={'code/known.py':sha256((tmp_path/'code/known.py').read_bytes()).hexdigest()}
    encoded=json.dumps(files,sort_keys=True,separators=(',',':')).encode()
    digest=sha256(encoded).hexdigest()
    (tmp_path/'manifest.json').write_text(json.dumps(dict(schema='pi-observer-runtime-v1',files=files,code_sha256=digest,git_commit='a'*40)))
    return tmp_path,digest


def test_closed_runtime_matches_expected_root_pin(release):
    root,pin=release
    assert module().verify_release(root,pin,expected_owner=os.getuid())==root/'code'


@pytest.mark.parametrize('change',['wrong_pin','edited','extra','link','writable'])
def test_runtime_drift_prevents_imports(release,change):
    root,pin=release
    if change=='wrong_pin':pin='b'*64
    elif change=='edited':(root/'code/known.py').write_text('value=2\n')
    elif change=='extra':(root/'code/extra.py').write_text('value=3\n')
    elif change=='link':
        (root/'code/known.py').unlink();(root/'code/known.py').symlink_to(root/'manifest.json')
    else:(root/'code/known.py').chmod(0o666)
    with pytest.raises(ValueError):module().verify_release(root,pin,expected_owner=os.getuid())
