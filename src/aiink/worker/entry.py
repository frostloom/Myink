"""worker 进程入口：`aiink-worker`（pyproject scripts）。"""

from __future__ import annotations

from aiink.worker.consumer import run

if __name__ == "__main__":
    run()
