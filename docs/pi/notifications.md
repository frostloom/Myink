# 日报、事故信号与失联排查

最终主机试验 `003` 已停止全部自有进程、keeper 和网关；没有发送日报或事故告警。真实邮件、短信和云告警均未配置、未发送；本地捕获属于 `simulated`。每日开发报告和事故告警是不同的交付物。实现边界及证据见[本机报告](../evaluations/pi-local-trial/report.md)与[索引](../evaluations/pi-local-trial/receipt-index.json)。

日报包含实验/run/内容版本、阶段目标与产物、源码及配置身份、任务成功/延迟/费用及未知预留、45 个语义指标的可用性、恢复结果、No release 原因和下一动作。日报不能通过“发送成功”证明业务、数据库或备份健康。正文、账号、密钥、完整会话和 dump 留在私有证据目录。

现有 `send_daily(ledger, report, transport)` 使用 date、run_id、content_version 和可选 recipient；日期/run/类型/内容版本形成稳定去重身份。缺收件人或 transport 时为 pending、attempts=0。captured 只证明本地捕获。明确 not_sent 最多尝试三次；异常或发送后回执缺失保留 uncertain，先用提供方幂等身份查证，不能删账本或换 run_id 重发。

未来收件人由可信宿主配置，提供方凭据只在通知进程持有，不写进 Pi context、Git、公共报告或镜像。腾讯个人短信渠道尚未实现；邮件也须取得实际提供方配置及独立交付回执。先验证捕获，再独立核对实际接收；配置完成与实际送达分别记录。

失联时依次核对最后成功心跳时间、控制器进程/owner/generation、网关账本 pending/uncertain、磁盘和资源状态、维护入口与 PG/队列。恢复不依赖模型余额。未来外部云监控必须独立注入并验证 PG down、备份失败、心跳缺失，记录发送及接收时间；本机模拟信号不能关闭这些待验收项。联系和通知地址不进入公共索引。
