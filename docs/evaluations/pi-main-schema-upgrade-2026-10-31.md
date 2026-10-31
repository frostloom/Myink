# main 首次升级的数据库迁移演练

这是隔离环境中的真实数据库与成品镜像演练，模式为 `ISOLATED_SYNTHETIC`，不代表生产已迁移或发布。[机器回执](pi-main-schema-upgrade-2026-10-31.json)保留精确来源及验证结果。

从生产当前源码 `f2304a284247ba02e575e08d73cc97a48a5621c9` 提取 Python 包，在独立 Compose 项目 `myink-pi-main-upgrade-20261031`、PostgreSQL 端口17432运行旧版 `myink init --seed`。随后用已准备的 amd64 成品 `myink-api:pi-admin-amd64-7e99f45f` 运行新版 `myink init`，源提交为 `7e99f45f6b70ee9713058f73b247552b4520c6b4`。没有连接生产数据库、队列、模型或 Pi 账本。

验证结果：

- 47张既有表、470行模拟数据，迁移前后逐表规范行指纹、行数及原RLS标志一致。
- 新增 `maintenance_control`、`maintenance_executions`、`admission_intents`、`queue_handoffs` 及 `myink_lock_maintenance()`；三个私有工作表强制RLS。
- 应用角色不能直接更新维护控制表，可以调用锁函数；报表角色不能读取三个私有工作表。
- 初始化生成的 bootstrap/initial/gen0 身份不是生产部署身份。使用原维护CAS逻辑关闭并绑定隔离身份后，再次运行成品初始化，关闭状态及绑定完整保留。

旧线上版本缺少上述表及函数，旧代码也不执行新维护屏障。因此首次 main 发布必须先用旧版可执行的入口关闭和排空办法停止新增工作，完成可恢复备份，再迁移、在关闭状态绑定精确部署身份、执行物理替换及核验。不能把新表中的关闭标志当成对旧进程已经生效的隔离。

原 `0ad352dc-888b-4a75-97d4-39296f327c6b` 周期仍观察旧 f230 部署。新 main 版本不得借用该周期旧批准，不得重绑其收据冒充新版本比较结果。实际发布前须保留到期证据或明确记录中断与新的观察归属。未执行的服务器 peer/systemd/物理替换仍按[运行手册](../pi/admin-console.md)验收。

生产未改变。本演练不证明线上指标改善，也未产生新的付费模型调用。
