"""Recovery material import rejects unsafe archives before native side effects."""
import importlib.util
import io
import tarfile
import pytest


def restore_api():
    assert importlib.util.find_spec('ops.pi.product_restore'), 'missing owned PostgreSQL recovery adapter'
    from ops.pi.product_restore import materialize_archive
    return materialize_archive


def archive(path, entries):
    with tarfile.open(path, 'w') as stream:
        for name, kind, body in entries:
            info=tarfile.TarInfo(name);info.mode=0o777
            if kind=='link':info.type=tarfile.SYMTYPE;info.linkname=body
            elif kind=='dir':info.type=tarfile.DIRTYPE
            else:info.size=len(body)
            stream.addfile(info,io.BytesIO(body) if kind=='file' else None)
    path.chmod(0o600)


def test_restore_materials_remain_private_and_content_matches(tmp_path):
    source=tmp_path/'materials.tar';target=tmp_path/'restored'
    archive(source,[('feedback','dir',b''),('feedback/a.bin','file',b'private-data')])
    proof=restore_api()(source,target,maximum_bytes=100)
    assert (target/'feedback/a.bin').read_bytes()==b'private-data'
    assert (target/'feedback/a.bin').stat().st_mode & 0o777 == 0o600
    assert (target/'feedback').stat().st_mode & 0o777 == 0o700
    assert proof['files']==1 and proof['bytes']==12


@pytest.mark.parametrize('entries',[
    [('../escape','file',b'x')], [('/absolute','file',b'x')],
    [('feedback/link','link','/etc/passwd')],
    [('a','file',b'x'),('a','file',b'y')],
    [('a','file',b'x'),('a/b','file',b'y')],
    [('large','file',b'x'*101)],
])
def test_unsafe_or_oversize_restore_archive_is_rejected(tmp_path,entries):
    source=tmp_path/'materials.tar';archive(source,entries)
    with pytest.raises((ValueError,FileExistsError)):
        restore_api()(source,tmp_path/'restored',maximum_bytes=100)
    assert not (tmp_path.parent/'escape').exists()
