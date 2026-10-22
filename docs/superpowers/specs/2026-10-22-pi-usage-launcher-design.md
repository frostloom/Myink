# Pi 宿主 usage 诊断接线

用户要求继续计量准备后的下一步骤；本轮只接线并离线验收。保持实际 live=false，不读真实凭据或账本，不启动真实 provider，不更改价格、usage 解析、预算、请求合同或容器权限。

## 行为

`AnalysisRun.gateway_handler(..., scope_token=..., usage_observer=None)` 将可选可信宿主观察器传给已有网关。观察器只收到 model_gateway 已脱敏的字段存在性、数值、固定原因与 attempt_id，不接收请求/答复正文、密钥、scope token 或私有路径。省略参数时旧调用保持兼容。

宿主 launcher 为每槽在新建0700结果目录中，先创建0600、不可覆盖的 `slot-{index}-usage-private.jsonl`，再构造网关/启动容器。独立小模块提供 `make_usage_observer(path, *, slot_index)`；每文件最多一次写入尝试、最多8192字节（含换行），记录 `schema=pi-usage-diagnostic-v1`、slot_index 和安全快照。只信任现有网关的脱敏快照，不开放为模型工具。

必须拒绝符号链接和非私有父目录；初始化已存在的文件不覆盖；回调重新打开时拒绝目标inode替换、非普通文件、硬链接与权限变化。写前编码/上限验证、锁内一次尝试，防并发膨胀。原inode的打开句柄保持到首次写入决定，或观察器被销毁时释放，避免删除后编号复用；不等待观察器交付。失败不重试。文件初始化失败在模型请求前停止；回调失败由既有异步dispatcher隔离，不改变HTTP、费用或终态。

沿用既有全局单daemon/六条队列的非等待观察器。不join、不flush等待异步队列、不提供可靠交付承诺；存储卡住、队列满或进程退出会丢记录。公开receipt只标明best-effort模式，不投影诊断内容或声称已持久化。未知计量仍完整保留预留并停止，不补零。

## 验收

真实SQLite与loopback HTTP验证AnalysisRun透传、拒绝重放不新增诊断、缺失缓存维度保留未知费用。launcher使用已有假Docker+真实stdio子进程+MockTransport边界测试，证明两个槽的独立文件、缺字段/上游异常停止与无正文泄漏。文件安全、并发上限、回调存储错误/卡住均覆盖。完整Pi离线回归；不把此结果算作实际LinuxPi或真实DeepSeek计量验收。
