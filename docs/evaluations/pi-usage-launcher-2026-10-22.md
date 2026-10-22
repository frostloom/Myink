# Pi 宿主 usage 诊断接线验收（2026-10-22）

可信宿主分析入口已接入既有脱敏 usage 观察器，实际策略保持 live=false。新代码没有读取真实凭据或原账本，没有实际 Docker、Linux Pi 或提供方调用；0付费请求，计费、生产及自动执行验收仍false。公开机器回执见同名JSON。

## 完成的行为

`AnalysisRun.gateway_handler`新增可选可信宿主`usage_observer=None`并传给既有网关；旧调用保持默认行为。launcher在每槽建立网关、接纳请求和创建容器前，在0700新结果目录中独占预建0600的`slot-{index}-usage-private.jsonl`，观察器文件初始化失败则本槽不发送。默认check不创建文件，live未启用的execute仍不能写入。

新`ops.pi.usage_diagnostics.make_usage_observer`只接既有网关已脱敏的快照。文件格式`pi-usage-diagnostic-v1`包含slot_index及evidence（attempt_id、固定解析原因、计量字段存在性/类型/有效整数等）；不保存请求、响应正文、密钥或局部token。每文件最多一次写入尝试、8192字节含换行；超长快照丢弃，正常并发回调也只能写一次。路径必须绝对且无符号链接，父目录0700；追加前验证原设备/inode、普通文件、单硬链接、0600及原始空文件。文件已有内容、被替换、链接或权限变宽时拒绝追加。写入错误不重试，短写或fsync失败可能留下不完整或未持久化记录，不能把文件存在算成完整证据。

诊断沿用已有单daemon、六条队列的异步dispatcher；不等待存储，不join队列，不释放或修改预算预留，不改变请求合同/模型/价格/usage解析器。存储卡住、队列满、daemon未启动或进程退出可能丢记录；不同运行共享这个有界dispatcher，前一个阻塞可导致后续诊断缺失。公开receipt仅标识`usage_diagnostics=best_effort_private`，不投影内容或宣称落盘成功。该模式字段在check时同样只是计划模式。

## 验证

新增22项测试先RED（缺sink、回调参数及文件接线）后GREEN。首次实现运行19通过、3失败：测试错误地对`Ledger.get`已经解码的字典再调用`json.loads`；只修正测试读取，实际未知计量已达到预期保守终态。

- 新测试及既有launcher/run/budget/usage/cache定向216 passed，12.90秒。
- 完整Pi离线2013 passed、0 skipped、19项pi_lab/pi_live未选入，56.93秒；compileall和diff-check通过。
- 覆盖真实私有文件（并发、字节上限、独占、父目录权限、链接、inode/模式替换、FIFO）、真实SQLite/loopback HTTP接纳与重放、缺缓存维度完整预留、未知/异常上游停止、两个独立槽位记录，以及回调抛错/卡住仍完成HTTP和宿主结算。
- launcher边界使用既有假Docker、真实stdio子进程和MockTransport，不是实际Docker或Linux Pi验收，也不是DeepSeek响应/账单证明。未运行业务Python/Go/web或完整设施CI。

日志/JUnit保存在本轮Superpowers任务目录，收尾归档到忽略的`.local/pi-usage-launcher-20261022/`；摘要见公开JSON。当前私有source-reviewed快照及4.10元草稿仍绑定旧代码，不能把历史容器验收套到新实现。实际诊断前需重新冻结来源、绑定真实五组输入、当前证据、费用上限与绝对deadline，核对真实usage语义及账单；缺维度仍不补零，unknown完整预留并停止。
