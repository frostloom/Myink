# Pi 分析对照运行接入计划

> 使用 superpowers:executing-plans 在已有 Pi worktree 当前会话执行；每个小目标单独提交推送。沿用已批准的管理员设计与分析对照范围，不增加生产权限。

**Goal:** 将现有冻结提示和共同评分接到真实 Pi RPC，并用无外部请求的真实进程验证实际出站请求。
**Architecture:** 复用 analysis_trial、writing_analysis、PiAdapter 和 make_pi_config。新增有限槽位接入层，只负责提示/请求身份、单槽调用和共同评分；原宿主预算、隔离和账本仍独立负责，模拟通过不授予付费或发布权限。
**Tech Stack:** Python、pytest、现有 Pi1.1.0/Node24、WSL、本机模拟 Anthropic SSE。
**Spec:** docs/superpowers/specs/2026-10-10-pi-autonomy-design.md；docs/evaluations/pi-analysis-contract-preregistration-2026-10-18.md；2026-10-20 用户授权继续下一步及逐小目标推送。

## Global Constraints

- 保护四项已有 ops/pi 未提交修改及 main 既有修改；不合并 main、不部署。
- 原累计20元上限和未知预留不变；本计划只运行离线与本地模拟请求，不访问外部模型，不改写原账本。
- 45项语义质量unknown；合同有效不代表真实写作质量提高；automatic_execution/release_allowed始终false。
- 固定5组×2臂×3次重复，30个槽位；不自动重试、修复输出或补跑。每槽新会话、共同cwd/system、无工具。
- 请求2048输出tokens、32768输出UTF-8字节；SDK/网关两种编码均≤65536字节，单槽deadline≤90秒。计费、累计时间/次数及隔离证明仍需实际宿主绑定，接入层不能自证授权。

## Review Focus

1. 重排、换臂、证据/提示漂移必须在启动进程前拒绝。
2. 实际SDK附加cwd/system及编码必须与冻结请求核对，禁止只检查静态提示。
3. HTTP成功、适配器done、合同有效分别保留，非目标观察仍由原严格评分拒绝。
4. 不可信错误或正文不进入公开摘要；失败槽位保留且不重试。
5. 本地模拟不连接真实提供方，不能复用旧040 grant或清零未知预算。

### Task 1: 有限槽位与单槽RPC接入

**Files:** ops/pi/analysis_execution.py；ops/pi/tests/test_analysis_execution.py；docs/pi/analysis-and-scoring.md。
**Interfaces:** prepare_contract_slots(views,report,model,cwd)、verify_contract_request(body,slot)、run_contract_slot(slot_index,slot,view,report,engine,session,deadline,model,cwd)。

- [x] 先写测试：30槽固定顺序/同system、漂移拒绝且engine未调用、非目标结果失败、无重试、无效会话/deadline拒绝。运行看到缺少实现的RED。
- [x] 最小实现，复用原提示/解析/评分及Engine协议；不创建新预算或权限接口。Expected: 定向测试通过。
- [x] 跑 analysis_trial / writing_analysis / pi_rpc 相关回归；文档注明真实计费和隔离尚未接入。Expected: 无新增失败，旧跳过单列。
- 提交交付门槛：测试证据记录后单独提交并推送，核对远程SHA。

### Task 2: 真实Pi进程本地模拟验证

**Files:** ops/pi/lab/pi-analysis-contract-probe.py；相关测试；docs/evaluations/pi-analysis-runtime-2026-10-20.md。
**Interfaces:** 使用Task1单槽API、make_pi_config和PiAdapter；loopback HTTP模拟仅回固定合成结果，不含真实数据或提供方密钥。

- [x] 先写探针边界测试并见RED：非回环/非固定路径请求、错误令牌、重复请求、坏payload不得被模拟成功掩盖。
- [x] 实现固定模拟探针，两臂顺序运行同cwd但新会话；原始请求/会话留私有目录，只公开摘要与哈希。
- [x] 在WSL以已有E盘Pi/Node实跑并记录真实进程、实际请求匹配、会话退出和共同评分；保留失败，环境阻碍不能算通过。
- 最终交付门槛：独立审查两项改动，修复阻断；定向回归通过后单独提交推送，结果须核对远程SHA，不用本计划复选框替代。

## 后续边界

真实付费30槽对照仍需当前宿主scope、原累计账本、实际模型价格与严格进程隔离验收。本计划不声称已完成付费对照或自主发布闭环。
