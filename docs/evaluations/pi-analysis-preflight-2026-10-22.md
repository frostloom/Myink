# Pi 真实试验只读预检（2026-10-22）

可信宿主入口的只读前置阶段已实现：`ops.pi.analysis_preflight` 在单一 SQLite 读事务内复用完整 schema/record 校验、原累计20元授权链校验和严格费用汇总。它使用 URI `mode=ro` 与 `query_only`，不构造 Ledger、不初始化 scope、不预留/认领、不接触凭据或 provider。原 Ledger 写入口仍使用相同校验逻辑，schema无变更。

预检要求宿主明确固定 scope SHA256 和规范化 policy SHA256，输出全量逻辑快照指纹（含 schema/operations/events/sequence），不输出正文、授权引用、provider request ID、私有路径或完整策略。规范化 policy 指纹是 `sha256(_json(asdict(load_policy(path))))`，区别于原文件字节 hash。CLI 是 `python -m ops.pi.analysis_preflight --ledger <原账本> --policy <已审查策略> --scope-sha256 <固定身份> --policy-sha256 <规范化策略身份>`；退出0只表示诊断完成，异常退出2并输出固定无正文错误。

## 当前真实账本观察

原私有根 `state/ledger.sqlite` 读到642 operations、1085 events；连续两次预检一致。逻辑快照 SHA256 为 `17389afd9f04bda966b85b8ffd8ec1e8dacb25d6ab42fa37a363ec79da78d968`，原scope SHA256为 `2218dd4133ffb7709f5d2c3812620a2ee7686ea57837983cf0495f0cd1099746`。

- 累计208次：202次已知、6次未知、0 pending。
- 已知费用1.791431元，未知完整预留12.082176元。
- 保守占用13.873607元，原20元预算保守余额6.126393元。
- 历史 reviewed policy 的规范化指纹为 `279b5e2c5edb2ff100850643ad427dd5919a1d86be86a5af72aa0769d7c23a9c`。其声明input bound=1000000、max_tokens=2048，按所声明价格计算单次最大输出保守预留2.016384元。

这些是本次快照的观察，旧204次/13.834690元检查点不能代替当前账本。已知费用与保守占用含义不同；六项历史未知未释放或改写。实际核对前后数据库和WAL字节相同，SQLite可能维护shm读标记，未声称全部辅助文件字节恒定。机器回执见同名JSON；本轮付费请求0。

## 验证与限制

新增29项测试覆盖临时真实SQLite的已知/未知/pending汇总、完整身份漂移、缺失/空/损坏/schema篡改、审批事件缺失、bool/负金额/超预留与未知折扣拒绝、只读连接拒绝写入、活动WAL可见、并发写入不混入快照、无正文错误/CLI、异常Decimal价格和未定cache价格。最初27项观察到模块缺失而RED；实现后修正WAL测试保留连接未实际打开pager的夹具问题。异常指数价格另有RED→GREEN证据。日志及JUnit位于忽略的 `.local/pi-analysis-preflight/` 与本计划临时workspace。

最终完整Pi离线回归1921 passed、0 skipped、19个pi_lab/pi_live未选入（64.23秒）；预检29项通过，compileall与diff-check通过。独立审查待完成。

`audit_valid=true`仅表示所选账本内部校验与宿主给定身份匹配；指纹不是签名、canonical路径证明或锁。`declared_live_ready=true`与`declared_input_bound_calibrated=true`只投影历史策略声明，当前价格证据和输入上界尚未完成独立复核。`paid_admission`、`production_ready`、`automatic_execution`均为false。本轮未运行容器、实际provider、业务Python/Go/web或设施CI，也未改变原试验授权。完整45项语义质量仍unknown。

下一阶段必须完成当前提供方价格/用量维度与输入上界证据审查，固定源码、配置和容器来源，并给定本轮费用与绝对期限；随后将这些条件与原账本的原子预留和容器生命周期连接。报告不能作为launcher令牌，合成容器probe仍不接受真实账本/provider参数。本次只读审计没有把容器合成验收升级为付费或生产验收。
