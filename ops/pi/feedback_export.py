"""Trusted, finite feedback export. Actual entry requires POSIX private files.

No model or Pi tools are invoked. PostgreSQL role/isolation acceptance remains
separate; the DSN is read only from PI_FEEDBACK_DATABASE_URL, never from .env.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from .db_reader import SnapshotCollector
from .feedback import (_encoded, _unique, _validate_snapshot, load_feedback_snapshot,
                       normalize_window, validate_cursor)

_PLATFORM = os.name
_MAX_BYTES = 512 * 1024


def _current_uid():
    return os.geteuid() if hasattr(os, 'geteuid') else 0


def _check_private(info):
    if info.st_uid != _current_uid() or info.st_mode & 0o077:
        raise ValueError('owner-only private file required')


def _unlinked(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute fixed host path required')
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('linked host path denied')
    return path


def _fresh_output(path):
    path = _unlinked(path)
    info = path.parent.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('existing private parent required')
    _check_private(info)
    if path.exists():
        raise ValueError('fresh output required')
    return path


def _read_cursor(path, window):
    if path is None:
        return None
    path = _unlinked(path)
    _check_private(path.parent.stat())
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        _check_private(before)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 8192:
            raise ValueError('bounded private cursor required')
        raw = stream.read(8193)
        after = os.fstat(stream.fileno())
    if len(raw) > 8192 or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('cursor changed or overflowed')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite cursor')))
    return validate_cursor(value, window)


def _write_snapshot(path, raw):
    if len(raw) > _MAX_BYTES:
        raise ValueError('feedback snapshot overflow')
    path = _fresh_output(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0), 0o600)
    created = os.fstat(fd)
    complete = False
    try:
        _check_private(created)
        if not stat.S_ISREG(created.st_mode) or created.st_nlink != 1:
            raise ValueError('private regular output required')
        offset = 0
        while offset < len(raw):
            count = os.write(fd, raw[offset:])
            if count <= 0:
                raise OSError('output write did not progress')
            offset += count
        os.fsync(fd)
        pin = hashlib.sha256(raw).hexdigest()
        load_feedback_snapshot(path, pin, trusted_root=path.parent)
        complete = True
        return pin
    finally:
        os.close(fd)
        if not complete:
            # Delete only the inode this invocation created, never a replacement.
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                    path.unlink()
            except FileNotFoundError:
                pass


def export_feedback(*, start, end, output, cursor_file=None):
    """Trusted host only. Returns metadata, never feedback bodies or credentials."""
    if _PLATFORM != 'posix':
        raise ValueError('POSIX private-file enforcement required; Windows ACL acceptance pending')
    window = normalize_window(dict(start=start, end=end))
    if datetime.fromisoformat(window['end']) > datetime.now(timezone.utc):
        raise ValueError('frozen window must have ended')
    output = _fresh_output(output)
    cursor = _read_cursor(cursor_file, window)
    dsn = os.environ.get('PI_FEEDBACK_DATABASE_URL')
    if not isinstance(dsn, str) or not 1 <= len(dsn) <= 4096 or any(char.isspace() or char == '\0' for char in dsn):
        raise ValueError('dedicated feedback database configuration required')
    if make_url(dsn).get_backend_name() != 'postgresql':
        raise ValueError('PostgreSQL feedback reader required')
    engine = create_engine(dsn, connect_args={'connect_timeout': 5})
    try:
        snapshot = SnapshotCollector(engine).collect_feedback(window, admin_scope=True, cursor=cursor)
        _validate_snapshot(snapshot)
        raw = _encoded(snapshot) + b'\n'
        pin = _write_snapshot(output, raw)
        return dict(schema_version=1, status='done', file_sha256=pin,
                    snapshot_sha256=snapshot['snapshot_sha256'], window=window,
                    row_count=len(snapshot['rows']), has_more=snapshot['has_more'])
    finally:
        engine.dispose()


class _ArgumentsError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal message may repeat unknown user-supplied secrets.
        raise _ArgumentsError('invalid feedback export arguments')


def main(argv=None):
    parser = _Parser(description='Trusted POSIX host feedback snapshot export; no Pi/model invocation.')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cursor-file', type=Path)
    try:
        args = parser.parse_args(argv)
    except _ArgumentsError:
        print('Invalid feedback export arguments.', file=sys.stderr)
        return 2
    try:
        result = export_feedback(start=args.start, end=args.end, output=args.output, cursor_file=args.cursor_file)
    except Exception:
        print('Feedback export failed; check trusted configuration and private paths.', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0
