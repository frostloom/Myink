"""Snapshot publication must not depend on garbage collection or recreate sources."""
import gc
from pathlib import Path
import sqlite3
import pytest
from ops.pi.backup import snapshot_ledger
from ops.pi.ledger import Ledger
from ops.pi.development_inputs import ledger_snapshot,file_hash


def test_snapshot_is_closed_stable_and_sidecar_free_before_return(tmp_path):
    source=Ledger(tmp_path/'source.sqlite')
    source.intent('example','synthetic',dict(value=1))
    target=tmp_path/'snapshot.sqlite';before=ledger_snapshot(source.path)
    enabled=gc.isenabled();gc.disable()
    try:
        watermark=snapshot_ledger(source,target)
        assert not any(Path(str(target)+suffix).exists() for suffix in ('-wal','-shm','-journal'))
        digest=file_hash(target)
        assert ledger_snapshot(target)==before and watermark['operations']==1
        gc.collect()
        assert file_hash(target)==digest and ledger_snapshot(source.path)==before
    finally:
        if enabled:gc.enable()


def test_missing_snapshot_source_is_never_created(tmp_path):
    source=Ledger(tmp_path/'missing.sqlite');source.path.unlink()
    with pytest.raises(sqlite3.Error):snapshot_ledger(source,tmp_path/'failed.sqlite')
    assert not source.path.exists()
