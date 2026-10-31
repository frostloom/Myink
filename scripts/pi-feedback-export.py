"""Source-tree launcher for the trusted POSIX feedback exporter."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root / 'src')]
from ops.pi.feedback_export import main

if __name__ == '__main__':
    raise SystemExit(main())
