# Pi 正式审批核对与刷新后的待审命令

2026-10-23，工具确已接收到旧命令的正式人工批准标记；它仅覆盖旧命令在原上下文中的执行，不自动覆盖新脚本或变更后的上下文。旧命令为 `.local/pi-uncapped-real-20261023/execute.py`，其SHA保持 `6deb977e8e2fd7f6c728d32894f2cdce6a8a291aa7fda25c1ecec57891b72735`，没有修改它来套用批准，也没有运行它。

## 旧脚本失去的前提

旧脚本固定217笔账本基线及早于非流式用量修复的源码闭包。当前账本218笔、9 unknown、0 pending，旧ledger SHA不匹配；旧source也报 `controller source snapshot drift`。原策略v2、20元、磁盘模型调用开关false没有改变。直接重放旧脚本会在预检停止，不能把旧批准当作新实验的授权标记。

## 已准备的新命令

```
PYTHONPATH=. .venv/bin/python .local/pi-uncapped-refresh-20261023/execute-refreshed.py > .local/pi-uncapped-refresh-20261023/execute-refreshed.log 2>&1
```

新脚本使用当前218笔基线、2227项通过的离线测试记录，以及重新冻结的当前源码；仍发送原冻结写作输入，不释放历史unknown。固定最多30次、1800秒、异常停止、不重试，持久追加原scope的v3无费用上限审批、临时启用并结束恢复关闭。它是新动作，必须独立审批；不是已批准旧动作的同名替换。

新源码真实Linux合成pilot为2 DONE/28 NOT_RUN、2次虚拟上游调用、2容器全部移除，operation标签扫描为空，源码闭包匹配。该刷新只做2槽pilot，不冒称又执行了完整30槽Linux验收。私有新source、合成回执和独立核对在 `.local/pi-uncapped-refresh-20261023/attempt-001/`。

新命令已通过正常工具入口请求独立审批，但被拒绝：理由是旧人工批准只覆盖旧命令，新动作未取得对应工具层批准。新真实执行进程没有启动，`real-attempt-001/`尚不存在，没有新增真实调用、私有数据外发、canonical审批或策略变更。

下一次正式复核应选择最新的 `execute-refreshed.py` 命令，而非旧的 `execute.py`。在该待审动作得到处理前，不再改变运行代码、账本基线或请求内容，避免再次产生上下文漂移。没有提交、推送、合并或部署。
