# Pi 当前Mac的Linux容器合成运行验收（2026-10-21）

本轮已在Linux ARM64容器内启动真实Node24.22.0/Pi1.1.0，经容器loopback与有界stdio中继接入宿主AnalysisRun预算网关。固定baseline/candidate两个槽位均通过原合同与宿主重评分，各一个请求被模拟provider接纳并完成已知结算；30槽总分母保留，2 DONE、28 NOT_RUN。**没有外部模型请求、真实账本修改、质量改善结论、main合并或部署。**

`pi_runtime_verified=true`只表示本次固定版本、固定合成输入、模拟响应和本地容器协议已验证；`billing_verified=false`、`production_ready=false`、`automatic_execution=false`、`paid_requests=0`、45项语义质量仍unknown。不生成accepted_envelope或付费执行grant。公开[机器回执](pi-container-runtime-2026-10-21.json)来自最终actual-006，包含原私有回执摘要及代码/依赖指纹，无正文与令牌。

## 依赖获取与来源

- 官方固定Node24.22.0 Linux ARM64压缩包，TLS下载后核对官方SHA256：`fef00bb4d36e1c50104a9775a10359beee98f162b4104dd12472c75065c6a143`。解压Node二进制SHA256为`719a43d185f3b6a59d8fcbba1ff06b93c75f76fb0bb9916f81d33921615d4cb5`，实际ELF/ARM64与版本核验通过；没有升级Mac运行时。
- 从既有私有Pi工程只复制package.json/package-lock.json到新目录，固定Pi1.1.0及现有依赖锁。lock SHA256：`fd0f5bd8aa13e01da8792b161d80502f32e1afd00103151fbcc21f4b3146785a`；全部resolved地址检查为registry.npmjs.org。
- 专用获取容器使用已缓存Python3.12镜像，不pull/build。仅获取阶段允许bridge网络；只读根、capdropALL、nnp、1GiB/0swap/.5CPU/64pids，唯一私有运行时目录可写，临时npm缓存位于有限tmpfs。执行npm ci --ignore-scripts --include=optional --engine-strict --audit=false --fund=false，121个包、退出0；保留node-domexception弃用警告，没有依此升级包。精确核验获取容器daemon/ID/name/image/label后删除。
- Linux依赖树含19856个文件/链接，规范JSON摘要`6e169d5462405f59c070365267eec24fddc005a3c141819ba7a1f548a592c528`。旧手工manifest默认空格序列化摘要40539fe4…不是CLI使用的规范摘要，二者不可互换。
- 不把Mac node_modules中的平台包当Linux依赖。执行前重新校验运行时树、Pi版本、Node ELF及整个代码导入闭包，拒绝额外源码/缓存、父级链接、源根额外文件及整树socket/FIFO等特殊文件；所挂载根仅node/pi/code。

## 执行与计量边界

复用[容器底座验收](pi-container-containment-2026-10-21.md)的精确归属与hardening：network=none、只读根、uid/gid65534、capdropALL、no-new-privileges、私有PID/cgroup、384MiB/0swap/.5CPU/64pids；只读固定worker和运行时/源码快照，可写仅/work16MiB与/tmp8MiB tmpfs。无业务源码、真实账本、凭据或宿主socket挂载。

容器内固定HTTPServer只监听127.0.0.1，经stdio向宿主发送请求；宿主只POST到当前槽位的固定loopback网关，不接受容器URL或工具路由，不跟随重定向。头部白名单保留重复认证头供原网关拒绝；每帧196608字节、总量1MiB、最多4请求、每槽最多60秒。stderr与stdout合并接受同一有界读取，失败原始前缀只存私有证据，不向公开回执投影。

宿主新建独立合成SQLite Ledger，复用原AnalysisRun、冻结30槽、逐槽不同token、原子claim、费用上限/绝对期限、reserve/settle。唯一provider是内置httpx.MockTransport，固定provider.invalid、trust_env=false，无真实提供方客户端或密钥入口。两次模拟结算合计1668 microyuan只是固定用量与虚构费率计算，**不是实际消费或真实计费验收**。原累计20元账本及历史unknown预留未触碰。

固定Pi配置：无工具、MCP、上下文文件、外部扩展、重试或压缩；仅加载原固定纯文本wire guard。两个新会话使用同system/cwd，PiAdapter核验RPC/会话并退出，宿主再次对照冻结身份、正文评分、完整会话SHA、单条纯文本assistant、无工具、clear/abort确认和退出0。运行时版本/身份为当前受信代码和依赖指纹下的观测，不是独立远程证明。

## 最终真实证据

actual-006操作`112e5d32-d52f-4ead-9fba-877fe6569aa8`；controller SHA256 `f316e30cf4dafcbc61ae5302dff74600dae9fa6504a4921421585858fd9afbeb`，worker `656ee0caa9f72ea2f9b66a9df4b3b111530ac234bc55722f5b138d849273a975`。完整依赖、源码、Node、lock、Pi入口与会话摘要见机器回执。

| 验证 | baseline | candidate |
| --- | --- | --- |
| 错误token | 403、无claim/预留 | 403、无claim/预留 |
| 冻结正文漂移 | 403、无claim/预留 | 403、无claim/预留 |
| 实际Pi请求 | 200、一次MockTransport | 200、一次MockTransport |
| 原令牌/正文重放 | 403、无新增预留 | 403、无新增预留 |
| 原共同合同/宿主重评分 | 通过 | 通过 |
| 新会话、无工具、进程退出0 | 通过 | 通过 |
| 容器停止、精确删除 | 通过 | 通过 |

费用不足负例在真实loopback/SQLite测试中验证429、0次transport与0预留，claim保持UNCERTAIN、不重试；没有额外将Linux Pi跑一次费用不足，不能将这项单测称为Linux实际429验收。CPU/OOM/PID行为与超时/溢出后代清理来自上一轮专门压力探针；本轮逐个inspect相同hardening，并验证真实Pi正常退出和清理，不重跑压力行为。

## 失败与审查修复

- 初始模块RED18项失败，worker缺失RED1 failed/20 passed；均先运行失败测试再实现。
- actual-001至003因SDK实际发送的标准上下文头不在中继白名单而blocked。错误token/漂移均403；Pi请求尚未通过中继，后续重放控制反而成为首个200模拟请求。保留每次失败分母、合成attempt与精确清理。调试只投影header名称，未暴露值。新增三个头部RED后仅支持实测标准字段；Pi失败时不再发重放控制来掩盖原失败。
- actual-004两槽通过；actual-005补充运行时及源码摘要后通过。最终独立只读审查发现代码导入父级/额外模块/pyc未封闭，以及挂载根额外文件/socket未封闭，两项Important。分别3 failed/36 passed和3 failed/39 passed复现（socket最初测试路径过长，缩短路径后才计有效RED），完成整棵源树封闭与特殊文件拒绝；没有把修复前成功当最终版本证明。
- 最终actual-006匹配修复后的指纹，两槽通过。独立审查其余中继、认证、预算与清理边界无新增Critical/Important/Minor；审查者未运行Docker、获取依赖或判断最终实际回执，实际验证由主代理执行。

## 复现与后续

固定Linux运行时私有缓存为本worktree忽略目录`.local/pi-container-runtime/source`（node/pi/code），归档、锁、完整manifest、获取日志和失败回执均在其父目录；新机器须重新按固定官方校验和及同一锁文件获取，不能仅凭摘要重建缺失依赖。原私有Mac runtime不变。示例从仓库根运行，root必须全新；Docker/daemon/image参数必须来自当前可信宿主核对，不复用其他电脑的daemon身份：

```sh
.venv/bin/python -m ops.pi.container_runtime \
  --root "$PWD/.local/pi-container-runtime/new-run" \
  --source "$PWD/.local/pi-container-runtime/source" \
  --runtime-sha256 6e169d5462405f59c070365267eec24fddc005a3c141819ba7a1f548a592c528 \
  --docker /Users/a1/开发工具/bin/docker \
  --endpoint unix:///Users/a1/.docker/run/docker.sock \
  --daemon-id 6a464461-31f4-4b73-bb3d-0f5e94024a27 \
  --image-id sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
```

代码改变后应重新复制固定代码快照，不能放宽verify_source以接受漂移。未知create保留恢复身份，daemon不可用/控制操作耗时仍不能提供独立硬实时终止保证。SSE在本地合成中继中先有界缓存再返回Pi，尚不代表生产流式性能。真实provider、真实用量/计费、生产容量/checker隔离、付费30槽和语义质量未验收。

下一步将容器执行路径纳入真实试验的可信宿主入口，先核对原累计账本、实际源/配置身份、价格与输入上界校准，再评估有限真实只读分析对照；不能将本合成probe开放为付费launcher。

最终验证：容器定向83 passed；完整Pi离线1892 passed、0 skipped、19 deselected（pi_lab/pi_live），51.72秒，JUnit无failures/errors；compileall通过，最终精确operation label查询为空。业务Python/Go/前端和集成服务未运行，本轮没有修改这些路径。
