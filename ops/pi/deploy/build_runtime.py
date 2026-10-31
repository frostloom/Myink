"""Build an explicit pure-Python paid-host closure from installed distributions.

No installation, dependency discovery at runtime or user/site import fallback.
The release verifier covers source, vendor modules, metadata and licenses.
"""
from hashlib import sha256
from importlib.metadata import distribution
from pathlib import Path,PurePosixPath
import json,re

DEPENDENCIES={'httpx':'httpx','httpcore':'httpcore','h11':'h11','anyio':'anyio','idna':'idna','certifi':'certifi','sniffio':'sniffio','typing_extensions':'typing_extensions.py'}


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def build(root,git_commit):
    root=Path(root);assert root.is_absolute() and root.resolve()==root and not root.exists() and re.fullmatch('[0-9a-f]{40}',git_commit)
    root.mkdir(mode=0o755);project=Path(__file__).resolve().parents[3];versions={}
    def copy(source,relative):
        target=root/relative;assert not target.exists() and source.is_file() and source.stat().st_size<=4194304
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o755);target.write_bytes(source.read_bytes());target.chmod(0o644)
    for source in sorted((project/'ops/pi').rglob('*')):
        relative=source.relative_to(project/'ops/pi')
        if any(part in ('tests','__pycache__') for part in relative.parts) or source.is_dir():continue
        assert not source.is_symlink() and source.suffix not in ('.pyc','.pyo'), 'closed source assets required'
        copy(source,'code/ops/pi'/relative)
    for source in (project/'ops/__init__.py',project/'src/myink/pi_audit.py'):
        if source.exists():copy(source,'code'/source.relative_to(project))
    copy(Path(__file__).with_name('observer_entry.py'),'entry.py')
    for name,module in DEPENDENCIES.items():
        dist=distribution(name);versions[name]=dist.version;copied=0;licenses=0
        for relative in dist.files or []:
            relative=PurePosixPath(str(relative));parts=relative.parts
            if relative.is_absolute() or '..' in parts or not parts:continue
            if parts[0]!=module and not parts[0].endswith('.dist-info'):continue
            if '__pycache__' in parts or relative.suffix=='.pyc':continue
            assert relative.suffix not in ('.so','.dylib','.pyd'), 'native vendor dependency forbidden'
            copy(Path(dist.locate_file(relative)),Path('vendor',*parts));copied+=1
            if 'licenses' in parts or any('LICENSE' in part for part in parts):licenses+=1
        assert copied and licenses,'vendor license required'
    (root/'dependency-lock.json').write_bytes(encoded(dict(schema='pi-host-dependencies-v1',python='3.12',dependency_versions=versions)))
    files={p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
    assert len(files)<=5000 and sum(p.stat().st_size for p in root.rglob('*') if p.is_file())<=67108864
    pin=sha256(encoded(files)).hexdigest();manifest=dict(schema='pi-observer-runtime-v1',files=files,code_sha256=pin,git_commit=git_commit)
    (root/'manifest.json').write_bytes(encoded(manifest));return dict(runtime_sha256=pin,files=len(files),dependency_versions=versions)
