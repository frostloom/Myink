"""Closed Linux64 architecture binding for frozen Node and Docker evidence."""
from pathlib import Path

MACHINES = ('aarch64', 'x86_64')


def canonical_machine(value):
    aliases = {'aarch64': 'aarch64', 'arm64': 'aarch64',
               'x86_64': 'x86_64', 'amd64': 'x86_64'}
    if not isinstance(value, str) or value not in aliases:
        raise ValueError('unsupported runtime machine')
    return aliases[value]


def node_machine(path):
    # The complete binary is separately pinned by runtime_fingerprint.
    with Path(path).open('rb') as stream:
        raw = stream.read(64)
    if (len(raw) != 64 or raw[:7] != b'\x7fELF\x02\x01\x01'
            or raw[7] not in (0, 3)
            or int.from_bytes(raw[16:18], 'little') not in (2, 3)
            or int.from_bytes(raw[20:24], 'little') != 1
            or int.from_bytes(raw[52:54], 'little') != 64):
        raise ValueError('Linux 64-bit Node required')
    machine = {183: 'aarch64', 62: 'x86_64'}.get(int.from_bytes(raw[18:20], 'little'))
    if machine is None:
        raise ValueError('unsupported Linux Node machine')
    return machine


def verify_runtime(runtime, expected_machine='aarch64'):
    if (expected_machine not in MACHINES or not isinstance(runtime, dict)
            or runtime.get('node') != 'v24.22.0' or runtime.get('pi') != '1.1.0'
            or runtime.get('uid') != 65534 or runtime.get('machine') != expected_machine
            or runtime.get('network_denied') is not True):
        raise ValueError('runtime boundary mismatch')
