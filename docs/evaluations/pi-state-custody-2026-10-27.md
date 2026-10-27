# Pi 跨主机状态所有权验收（2026-10-27）

已实现原模型预算账本的冻结/激活守卫，并完成Mac ARM到现有Linux x86服务器的**合成账本**移交验证。源端冻结后拒绝付费许可，目标仅在绑定的native主机和规范绝对路径激活，已激活副本复制到另一位置也不能获得许可。真实账本、凭据、manager和生产服务均未迁移；Pi尚未上线。

原reserve事务内第一步检查custody，和freeze共享BEGIN IMMEDIATE，拒绝发生在analysis-slot写入及transport前。存在pending模型许可时（包括过期未结算）不得冻结；历史terminal uncertain预留保持。legacy无custody事件的账本保持兼容，scope仍为local-trial-1，没有每日额度重置或server_daily_enabled绕过。操作CLI为`python -m ops.pi.state_custody --ledger PATH status|freeze|activate`；freeze/activate需明确operator授权引用、transfer及目标或快照摘要。

主机身份只使用Linux machine-id或macOS IOPlatformUUID的域分离SHA256，缺失或不支持的平台拒绝。custody事件为append-only，校验完整交替链、父hash、唯一transfer及精确schema。逻辑快照由完整operations hash与有序events hash组成；freeze记录不可变operations摘要，历史读取逐一重算transition输入的事件前缀，激活前operations变化拒绝。递归JSON解码拒绝顶层及嵌套重复字段，不能覆盖成另一种权限状态。

## 验证

| 项目 | 结果 |
| --- | --- |
| 新回归 | 47项；首22项最初因模块缺失setup error，不能报22个行为断言失败 |
| 原预算/账本兼容回归 | 首轮211通过 |
| CLI/native阶段RED→GREEN | 5失败/38已有控制→43通过 |
| 独立最终代码审查 | 2个P2：历史摘要未复核、重复JSON覆盖；已按一次作者修复处理 |
| 审查修复回归 | 4项RED/43控制→47通过，未做第二轮代码审查 |
| 完整Pi / Node | 3015通过/19按规则未选；54通过/0跳过 |
| 真实模型调用 / 费用 | 0 / 0 |
| 生产状态 | 7容器ID/镜像/重启/OOM/健康前后一致，myink.cloud readyz正常 |

独立私有源账本构造9条uncertain许可、¥18.115200未知预留和原式累计¥50上限，金额用于模拟真实历史约束，**不是复制真实9条请求**。freeze后源端许可拒绝且记录完全不变；一致性SQLite backup传至服务器后，摘要、已审查7个控制层文件、native/path和生产基线均核对。目标激活后仅做1次合成reservation并用固定usage结算10微元，未执行transport，不能计成真实模型消费。原9条记录/events前缀保持，错误位置的active副本拒绝且无新行；新连接重开无额外副作用。所有合成源/目标/副本及日志保留。

真实原账本和原manager状态逐项对比不变：累计748请求/739已知/9历史未知，已知估算¥4.644495，保守占用¥22.759695/50，剩余¥27.240305；关闭policy和凭据hash保持。没有transfer真实私有凭据，没有启用systemd/cron或修改产品镜像。本次服务器验证只覆盖7个stdlib控制层文件，不替代完整Pi/SDK常驻环境、真实provider及恢复/容量验收。

## 信任边界与下一步

这是可信宿主的操作防错和付费所有权约束。仅此SQLite无法防止同host/path恢复整份旧账本、克隆machine-id或恶意特权操作者构造一致替代历史；那些需要外部不可回滚权威。冻结仍允许普通诊断metadata写入，操作员必须先停控制器、封存旧可运行入口、再做一致性backup与摘要；不能称防御所有历史备份。

下一步以当前完整控制器重新固定服务器runtime，准备真实原manager/账本/配置的一致性备份及恢复演练、单一状态交接和最小权限常驻服务，再做有限真实provider与上线后验证。累计50元和9未知预留保持；目标继续active，不能从本次合成移交宣布上线。脱敏原始字段见[JSON](pi-state-custody-2026-10-27.json)。
