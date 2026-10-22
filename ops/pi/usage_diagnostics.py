"""Private best-effort storage for the gateway's sanitized numerical snapshots.

The existing asynchronous dispatcher owns delivery and isolates callback errors.
This sink is not a ledger, a billing certificate or a model-visible capability.
"""
import json
import os
import stat
from threading import Lock

from .container_probe import _path


def make_usage_observer(path, *, slot_index):
    """Reserve a private destination before admission; one bounded write attempt."""
    if type(slot_index) is not int or not 0 <= slot_index < 30:
        raise ValueError('bounded usage slot required')
    path = _path(path)
    if stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise ValueError('private usage parent required')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        original = os.fstat(fd)
    finally:
        os.close(fd)
    lock, attempted = Lock(), False

    def observe(item):
        nonlocal attempted
        raw = (json.dumps(dict(schema='pi-usage-diagnostic-v1', slot_index=slot_index,
                               evidence=item), allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')
        if len(raw) > 8192:
            return
        with lock:
            if attempted:
                return
            attempted = True  # Storage failure never earns another append attempt.
            _path(path)
            if stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
                raise ValueError('private usage parent changed')
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                current = os.fstat(fd)
                if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                        or stat.S_IMODE(current.st_mode) != 0o600
                        or (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino)
                        or current.st_size != 0):
                    raise ValueError('private usage destination changed')
                if os.write(fd, raw) != len(raw):
                    raise OSError('incomplete private usage record')
                os.fsync(fd)
            finally:
                os.close(fd)
    return observe
