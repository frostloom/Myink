# Pi 分析合同运行接入（2026-10-20）

本轮把原冻结提示与严格评分接到现有Engine/Pi RPC，并通过真实Pi1.1.0进程的本地模拟网关验证。**没有调用外部模型、没有真实语义质量改善结论、没有发布或合并main。**

## 交付与边界

- `ops/pi/analysis_execution.py`：固定30槽，5组×2臂×3次；提示、证据、报告、实际system/cwd和完整请求指纹绑定。宿主提供可信`slot_index`，接入层据固定顺序重算当前槽位，禁止拿另一合法槽位替换。
- `run_contract_slot`：新会话、无工具、一次Engine调用、deadline最多90秒；复用原严格JSON/字面引用/目标域评分，保留私有原始输出。无自动补跑、重试或输出修复。
- `verify_contract_request`：在宿主网关转发前核对实际SDK请求，额外字段、数值类型、system或正文漂移均拒绝；两种编码仍受65536字节上限。
- `ops/pi/lab/pi-analysis-contract-probe.py`：只绑定127.0.0.1，固定模拟令牌与路径，一槽最多接受一次请求；没有真实提供方客户端、真实密钥或账本接口。已启动槽位先登记，异常保留固定错误分类和请求数，不能算NOT_RUN。

这仍是执行接入层。宿主负责持久游标与防重放、原累计预算预留、整轮时限、真实模型路由/价格、隔离与所属进程树清理。`billing_verified=false`和`production_containment_verified=false`不能被模拟成功替换。45项语义仍unknown，automatic_execution/release_allowed均false。

## 实际验证

真实环境：MyinkPiLab WSL、uid/gid65534、E盘已安装Node v24.16.0和Pi1.1.0。Windows注册表只读确认该发行版BasePath为`E:\tools\myink-pi\runtime\wsl`。使用其中固定Linux原生目录解决DrvFS文件锁的utime限制，未改系统账户shell、挂载参数或文件的广泛权限。

选取首组事件召回的baseline/candidate两个槽位作**合成协议探针**：

| 项目 | baseline | candidate |
| --- | --- | --- |
| 实际Pi本地HTTP请求 | 1 | 1 |
| 请求与冻结值匹配 | 是 | 是 |
| 同system/cwd、新会话 | 是 | 是 |
| Engine状态 | done | done |
| 会话有效、清队列/abort确认、进程退出0 | 是 | 是 |
| 原共同合同评分 | 有效 | 有效 |

30槽清单只选2槽作本地探针，余28槽未运行；**正式真实模型30槽实验未启动**。模拟响应为固定合成结果，不能比较两臂分析能力或采纳候选。操作系统级严格资源隔离/后代进程树证明没有在此探针验收。

测试先RED后GREEN：首个新模块24项缺实现失败，随后24通过；探针7项缺实现失败，随后通过。实际导入暴露pytest依赖后补独立`-I -S`导入负例并修复；独立审查又发现槽位整体替换与请求后异常计数两项问题，均分别复现RED后修复。

最终相关回归：**402 passed、1 Windows符号链接权限SKIP、0 failures/errors，24.25秒**。范围为新接入/探针和原analysis_trial、writing_analysis、pi_rpc、pi_config测试。没有重跑业务全量CI、生产数据库、外部模型或完整离线ops套件；此前1687通过属于上一轮基线。

## 保留的失败与复核位置

首次nobody登录shell被拒，改用`wsl --exec`保持非root；随后发现运行夹具依赖pytest，改为无测试依赖的合成输入。DrvFS首次真实Pi运行在auth锁utime处失败：0次HTTP、baseline返回failed、candidate未运行。失败源码指纹和摘要均保留，不以第二次成功覆盖。

成功运行目录是WSL内`/opt/myink-pi-lab/analysis-contract-probes/20261020-002`（虚拟磁盘在E盘）。固定合成wire、私有回执和4份会话/转录已复制到项目忽略目录`.local/pi-analysis-probe-20261020/native-run-002/`，逐份内容哈希一致；Windows不支持的Linux时间元数据未复制。

源归档与修复覆盖清单在`.local/pi-analysis-probe-20261020/source-003/`及`source-manifest-003.json`，从已推送d4de8a5归档仅加入本轮4份文件，未纳入原4项未提交修改。原始测试日志/JUnit为`.local/pi-analysis-runtime-final.log/.xml`。公开[机器回执](pi-analysis-runtime-2026-10-20.json)只含状态、分母和哈希，无正文或密钥。

只读核对原账本仍为204次尝试、保守占用13.834690元（包含未知预留，不是实际消费额），本轮新增付费尝试0次；未释放或重置旧预留。

## 下一小目标

将该实际SDK请求核对接入**当前有效的宿主scope与原累计20元账本**，完成新轮计数/费用/整轮超时与严格进程隔离证明，再执行已预注册的真实分析对照。沿用现有模型和授权范围，不复用040固定开发grant，不用本地模拟结果作付费、语义质量或自主发布验收。

最终独立审查：原两项P2均经复现后修复，无新增实质阻断。审查者只读核对4份源码覆盖、私有摘要、2份回执、2份会话和JUnit哈希一致；未独立重跑测试或探针。
