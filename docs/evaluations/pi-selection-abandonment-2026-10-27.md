# Pi 选择冻结核对与同队列接续验收（2026-10-27）

本轮完成宿主只读检查、明确Docker清理审计、独立放弃审批和原manager内追加reconciliation记录。只支持选择阶段已停止、无工具或开发执行、唯一新增费用已结算的ACTUAL任务。旧dispatch/control及其协议失败不改写；旧输出不采纳，放弃不能算成功。新任务仍须全新身份、当前完整runtime和原账本检查点、原选择/开发两阶段独立审批。

## 原任务与恢复

原`observation-nfc-001`原始worker仍pending/protocol_failed、native control两条uncertain、manager dispatch仍uncertain。独立核对原请求/模板/catalog/审批/native结果/会话与RPC、prepared空及无开发输出，原费用账本与结算后快照一致、唯一费用2228微元已知、原unknown9条完整保留，原policy/credential SHA一致且调用关闭，所属container/operation实际不存在后，只在同一个manager追加abandoned核对记录。

独立审查批准后实际apply：旧manager所有行及events前缀完整，旧control和原费用账本整个快照相等。原raw uncertain分母1保留，abandoned1、unresolved0。3个全新CLI进程恢复原队列均idle、0分派；无重复请求/费用。核对中断的pending继续冻结；已持久保存有效授权的pending只能用同报告/审查及重新核对的事实完成原写回，不能授权重跑模型。报告或审查丢失、篡改、链接、其他未知执行均拒绝。

## 真实新任务，不删未选择轮次

两项均使用原manager和原费用账本；未另开队列绕过旧状态。

| 新任务 | 固定Docker基线 | 真实选择 | 开发 | 费用（微元） | 原生终态 |
| --- | --- | --- | --- | --- | --- |
| NFC | 5测试、2断言失败、0错误/跳过 | 1次调用，返回null | 未进入，无开发批准 | 1638 | done/observe |
| casefold | 5测试、2断言失败、0错误/跳过 | 1次调用，选择具体缺陷 | 独立批准后5次调用，候选通过5固定检查及原协议认证 | 2300+16035 | done/review_candidate |

NFC协议已验证，但模型把失败基线误读为无可选任务，原样保留为未选择，不能记成修复。为了覆盖开发路径，另加不同的casefold既定契约缺陷（lower不能处理德语sharp-s和希腊sigma），新数据/身份/检查点/审批，不改签或重放NFC意图。额外casefold实际6请求/18335微元；原不限累计费用授权不变，选择1请求/120秒，开发最多12请求/32共享RPC/900秒，cycle1800秒、父manager2100秒等有限界限保留。

本阶段共 **7次真实调用、19973微元（0.019973元）已知估算、0新增未知**。费用来自冻结费率账本，不是服务商账单。原账本现690尝试/681已知/9历史未知，已知累计4.469255元；旧operations和events前缀不变，旧unknown未释放。原policy恢复关闭、credential和产品L1源SHA不变。

最后再以3个新CLI进程恢复同一队列，0分派/0新增调用，费用全快照相等。本阶段两组共6次新进程恢复；不是生产长期零重复扣费保证。原manager最终raw uncertain1+done2，abandoned1、unresolved0；done2中只有casefold进入开发。7个唯一所属容器直接inspect确认不存在、7个operation标签无剩余。candidate SHA保留在JSON，候选只在私有工作区，不采纳业务代码。

## 代码与验证

核心提交`dbb6fcbc`，运行闭包`7b85d979…`，依赖指纹`52ae48ab…`，沿用官方Pi1.1.0核心。独立最终代码审查发现1项P1：原始session/RPC嵌套工具记录可能放行；作者6个RED拒绝用例复现后，补上三条纯文本session、完整RPC一致性/顺序及metadata/流式事件的语义工具节点拒绝。另增自洽未知费用快照拒绝。86相关测试、完整Pi2812通过/19实验项未选、Node54通过；不声称第二轮独立代码批准。原协议失败的底层线程原因仍未由旧材料确认，不将新成功倒推成旧成功。

公开源码中的合成fixture和测试可复现核对/中断/恢复边界；CLI见[本机开发入口](../pi/local-development-launcher.md#选择阶段已停止任务的核对与放弃)。私有证据在`.local/pi-selection-abandonment-20261027`，其原manager仍在上一阶段目录。未本机重跑产品服务全套；远程门禁结果在JSON与GitHub运行中记录。未合main、部署、启用服务器自治或修改上游Pi核心。未测配对效率改善和生产可靠性。

后续应加强选择阶段对失败基线的语义理解，并对其他中断阶段设计分别限定的核对证据；未知费用和已进入开发的异常仍停下，不套用本profile。

Core verification: [all four remote gates passed](https://github.com/frostloom/Myink/actions/runs/40461045745) for `dbb6fcbc`, including the fresh PostgreSQL suite, frontend, image builds and Pi offline/Node checks. The final evidence commit is checked separately.
