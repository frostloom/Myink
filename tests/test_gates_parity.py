"""闸门脚本 parity：Python 用的是网关那份 `.lua` 的逐字节副本，不是手抄。

语义真源留在 `gateway/internal/queue/`（连带它那 8 个行为测试）。这条断言是"原样复用"
唯一**可检查**的证明，也是 Go 源码与 `internal/queue/` 必须留在仓库里的理由。
要改闸门语义，先改 Go 那份，再把文件 `cp` 过来。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = _ROOT / "gateway" / "internal" / "queue"
_COPY = _ROOT / "src" / "myink" / "worker"


@pytest.mark.parametrize("name", ["gates.lua", "compensate.lua"])
def test_copy_is_byte_identical_to_the_gateway_original(name):
    assert (_COPY / name).read_bytes() == (_SOURCE / name).read_bytes(), (
        f"{name} 与网关那份漂移了。两份必须逐字节相同——"
        f"改语义就改 {_SOURCE / name}，然后把文件复制过来。"
    )


def test_the_scripts_load_from_the_package_directory():
    """脚本必须躺在模块旁边：`package-data` 漏了的话进不了 wheel/镜像。

    真跑一遍生产同款的加载路径（`__file__` 同级），而不是断言仓库里那个相对路径。
    """
    from myink.worker import enqueue

    here = Path(enqueue.__file__).parent
    assert (here / "gates.lua").is_file(), f"{here} 里没有 gates.lua（package-data 漏了？）"
    assert (here / "compensate.lua").is_file()
    assert enqueue._GATES_LUA == (_SOURCE / "gates.lua").read_text(encoding="utf-8")
