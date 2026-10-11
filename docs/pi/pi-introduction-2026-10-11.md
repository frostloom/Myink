# Pi 实际引入记录（2026-10-11）

本轮把 Pi 实际安装到 E 盘，并接入 Myink 管理员的 `Engine` 接口。[脱敏验收摘要](evidence/2026-10-11-pi-introduction-receipt.json)记录当前范围。它目前可以通过受控 RPC 做只读源码分析。开发工具与发布闭环尚未启用，本轮未修改主工作区，也未部署生产 Pi。

## 已完成

- 精确安装 `@earendil-works/pi-coding-agent@1.1.0`，固定 Node 24.16.0 与完整依赖锁。146 个锁定包中，121 个适用于 Linux x64 的包已安装；归档完整性逐项核对，安装脚本未执行生命周期钩子。
- 真实 Pi 进程通过本地 Anthropic SSE 替身完成一次请求。回执确认请求被接受、阶段 settled、新 assistant 会话记录有效、中止命令有序确认、所属进程退出 0；这不是仅用 fake 子进程的单元测试。
- 管理员角色与引擎接口解耦。当前实现为 Pi，控制程序管理预算与权限，Pi 的输出不会自行授予发布权限。
- 预算网关验证独立实验令牌、限定文本请求、关闭思考、禁用重试与重定向。兼容固定 SDK 的 `/v1/messages?beta=true`，只向上游转发规范路径。
- 只读预览输出七字段 JSON：假设、源码依据、未知基线、候选指标、测试、风险和所有者决策边界。源码引文必须逐字匹配固定摘录；不把源码推断当成运行效果。

## 真实模型预览

真实 Pi 与配置的 `deepseek-v4.1-flash` 已完成一次只读分析，阶段约 12.4 秒，所属 Pi 进程退出 0。输出已通过七字段与源码引文校验，会话 SHA256 为 `3185f69b9e225421df171df322d70dc647e5bfa6702458913975e0207f6a4878`。网关累计账本确认 **1 次真实请求**。上游 usage 未满足可信完整结算条件，该请求终态为 `uncertain`、`usage_known=false`；按最坏上界保留 **2,016,384 微元（2.016384 元）**。这是保守预算占用，实际费用未知，不能当作已消费金额或完整计费兼容通过。不会以 Pi 的默认零值覆盖未知，也没有额外付费重跑。预算沿用首次本机实验的累计 100 次请求、估算 10 元；本次只读预览另外限制最多六次实际转发，不能通过重启重置。模型只接收固定提交的三个非敏感文件摘录，不读取上游密钥、环境文件、备份或主工作区。

其建议是调查 `collect_snapshot` 逐页调用 reader 的往返与连接开销，并验证会话复用是否有收益。[原始结构化建议](evidence/2026-10-11-pi-readonly-plan.json)保留源码引文、指标、测试和风险。它仅分析固定提交的摘录，没有观察 reader 的实际连接实现或测量性能；建议尚未批准为可执行改动，特别是受保护的管理员代码不能由模型自行修改。

## 实测隔离与可维护性

Pi 在 E 盘承载的 `MyinkPiLab` Linux VHD 内以 uid/gid 65534 运行。内存上限 384 MiB，CPU 0.5 核，swap 为 0；模型网关独立运行，拥有自己的资源上限与硬截止。Pi 只访问 localhost，主工作区、宿主 C 盘、凭据、累计账本与备份目录不可见。它只有当前阶段的私有目录写权限。

首次直接使用 DrvFS 存储非 root 的 auth 锁时，锁心跳遇到 `EPERM`。修复是在 E 盘承载的 Linux 原生文件系统建立独立目录，并只在该运行的 mount namespace 内绑定到显式 E 路径；没有改全局挂载设置或改为 root 运行 Pi。失败运行与后续成功运行分别保留。

升级流程见 [pi-version-upgrade.md](pi-version-upgrade.md)。固定配置入口为 `ops/pi/pi_config.py`，RPC 为 `ops/pi/pi_rpc.py`，只读驱动为 `ops/pi/lab/pi-preview.py`，可信网关为 `ops/pi/lab/preview_gateway.py`。完整依赖清单在 `ops/pi/runtime/`。

## 成果位置

| 内容 | 位置 |
| --- | --- |
| 隔离代码分支 | `codex/pi-autonomy-design` |
| 隔离工作区 | `C:/Users/14341/.codex/worktrees/pi-autonomy-design/Myink` |
| 固定 Node | `E:/tools/myink-pi/runtime/node/node-v24.16.0-linux-x64` |
| 实际安装项目 | `E:/tools/myink-pi/runtime/pi-project` |
| E 盘 Linux VHD | `E:/tools/myink-pi/runtime/wsl` |
| 安装、锁与完整性证据 | `E:/tools/myink-pi/evidence/c14/` |
| 成功真实进程模拟回执 | `E:/tools/myink-pi/evidence/c14/mock-003/` |
| 真实只读预览回执、会话与预算 | `E:/tools/myink-pi/evidence/c14/preview-001/` |
| 统一累计账本 | `E:/tools/myink-pi/state/ledger.sqlite` |
| 真实上游配置 | 私有 `state/credentials/`，不进入 Git |

主工作区已有未提交修改被保留；B12 未验收的构建改动没有纳入本轮提交。

## 验证与后续

本轮 Pi 配置、RPC、只读计划与网关边界定向测试 **19 项通过**，请求约束扩展 **6 条断言通过**。此前网关配置与 SDK 路径变更的定向回归 **96 项通过**。这些检查针对各自范围，不能相加当成一次全量验收。本轮未宣称全项目测试、质量提升或上线通过。代码批次已推送到 [隔离功能分支](https://github.com/frostloom/Myink/tree/codex/pi-autonomy-design)，没有合并 main。

当前 C14 为部分完成：文本调用与会话生命周期已实测，完整计费兼容、工具往返与恢复协调仍未验收。替换引擎接口已建立，其他引擎的实际替换验收待 C18。剩余工作是最少受控开发工具与阶段规范、指标采集和公平质量对照、一次本地小步开发及次日归因演练。备份、审计、所有者版本识别、构建资源与恢复门槛仍按总计划执行；安装和分析成功不代表完整自动迭代已完成。
