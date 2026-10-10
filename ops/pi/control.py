import argparse
import json
from pathlib import Path

from .ledger import Ledger, LedgerBlocked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('ledger-check')
    check.add_argument('--state-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        state = args.state_dir
        if not state.is_absolute() or state.drive.lower() != 'e:':
            raise LedgerBlocked('state directory must be an explicit absolute E drive path')
        state.mkdir(parents=True, exist_ok=True)
        Ledger(state / 'ledger.sqlite')
    except (LedgerBlocked, OSError):
        print(json.dumps({'schema_version': 1, 'status': 'blocked'}))
        return 1
    print(json.dumps({'schema_version': 1, 'status': 'done'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
