# Pi 基线恢复与数据分析继续记录（2026-10-20）

## 小目标1：备份生命周期测试时钟

原2026-10-19快照检查停止在59%，有4个失败标记，无完整失败详情或最终JUnit，不能计为通过。按收集顺序确定精确nodeid后，同一冻结快照在沙箱外复现：1 failed、3 passed（4.85s）。

- `test_backup_lab.py::test_preparation_failure_closes_prior_current_rehearsal`：仍失败。
- `test_backup_lab.py::test_protocol_archive_refuses_hardlink_or_budget`：通过。
- `test_ci_overrides.py::test_ci_project_ports_urls_and_skip_are_real_overrides`：通过。
- `test_executor.py::test_symlink_rejected`：通过。

唯一稳定失败的根因是测试时钟混用：`qualified_restore`使用固定`NOW=2026-10-11 UTC`写演练时间，资格查询没有传`now`而使用现实时间。7天后原成功演练自然失效，导致测试在准备失败前就被拒绝，未走到它要验证的撤销分支。

只调整该测试：资格查询和mark_released显式使用同一固定NOW。生产7天过期、未来时间拒绝、准备失败撤销资格、恢复不依赖普通发布资格等规则保持。现有`test_backup.py`的7天边界负例一并运行。

当前工作区相关4文件测试：`test_backup.py test_backup_lab.py test_ci_overrides.py test_executor.py`，139 passed（103.25s），退出码0；不调用模型、不连接业务服务。四项既有未提交路径迁移修改不纳入本次提交；下一目标从提交归档重新验收，不能用工作区结果替代干净基线。

原始复现、GREEN日志和JUnit留在主工作区忽略的`.local/`中。主分支、线上服务和历史账本均未改变。

## 小目标2：干净基线与数据分析

### 干净源码回归

从提交 `4083b69dec005765b620a596bee0b480b8c638b0` 的 `git archive` 解压到 E 盘忽略目录，以归档内 `src` 为 PYTHONPATH，运行：

```text
python -u -B -m pytest ops/pi/tests/ -q -ra --tb=short --durations=12 -m 'not pi_lab and not pi_live' --basetemp ../test-tmp --junitxml ../offline-junit.xml
```

退出码0：**1687 passed、2 skipped、19 deselected，488.60秒**。两项skip分别为writing_analysis和writing_evidence符号链接测试，原因是Windows无法创建符号链接；未作为通过。19项pi_lab/pi_live未选入。没有运行完整业务CI、真实提供方或生产测试。四项既有未提交修改未进入归档。

### 留存数据核对与分析结论

原025输入清单SHA256为 `646270e7ea7b58d76950050934f78afe5f4ee0a7fb87e322298e63b04bc5beb7`，原报告文件SHA256为 `0a58a5e69680379c93edfeec6bfe4bd629db32724811648efc67debf91ed65f6`，本轮均核对一致。原输入、报告与账本保持不变。

以当前可信源码只读重算，历史时间窗为2026-09-12至2026-10-12（UTC），共27个任务、298条运行、20个快照。当前报告与原报告仅有dataset_id、sources.feedback、table_coverage.feedback三处差异：新实现加入空反馈表投影，连带改变数据集身份；operations与quality值一致。不能声称原报告字节重现，也没有新生产采样。

| 观察 | 证据和限制 |
| --- | --- |
| 长篇任务 | 19个，留存状态done14、failed5；73.68%仅是历史状态比例，不是作者满意率，也不能推断当前故障率。 |
| 召回与抽取留存 | 各6个任务有记录，13个unknown，8个短篇not_applicable。留存表示有证据，不代表充分或正确；unknown不等于没有执行或质量失败。 |
| 正文、审核与修订 | 正文14 retained/13 unknown；审核23/4；修订8/19。它们是各阶段可用性，不能当作成功率。 |
| 时间 | created-to-updated包含排队、人工等待和状态更新时间，不能作为模型耗时；样本不足，不报告p95。 |
| 成本 | 长篇252条关联运行中仅124条有报告成本，总成本unknown；部分已知和约0.61645元不能替代整任务账单。短篇22条关联运行的报告和约0.46728元，也不证明任务成本完整。 |
| 语义质量 | 45项全部unknown，0项独立实测；没有召回精确率、抽取正确率或正文质量提升结论。 |

对原5组有限view重复冻结两次，摘要一致；事件、情节两组共享同一view，不能算独立样本。冻结仅证明静态输入与提示可复核，不等于实际Pi系统提示、cwd或运行隔离已验收。所有摘要、覆盖分母和预算汇总保存在[机器可读回执](pi-retained-data-audit-2026-10-20.json)，其中不含正文或密钥。

### 累计预算与下一步

只读核对原`local-trial-1`账本：204次历史尝试，已知估算1.752514元，6次未知费用保守预留12.082176元，合计占用13.834690元；原20元上限下剩余6.165310元。**占用不是实际消费额**；未知预留不能清零。本轮新增模型请求0次，没有改写账本。

下一小目标是把[现有分析合同对照草案](pi-analysis-contract-preregistration-2026-10-18.md)绑定到当前真实Pi运行器，而非重新设计提示：

1. 复核现有模型路由与价格，按原累计20元预算验证每槽最坏预留；草案30槽/1.50元只是拟议外层限制，不自动生效，不另增费用授权。
2. 绑定已核验的私有输入与真实SDK编码、动态system/cwd、准确源码和配置哈希；两臂实际上下文一致、无工具、无额外读取。
3. 在实际运行器证明计数、费用、超时和精确所属进程清理，先离线/模拟验收并独立审查，再生成当前范围的执行回执。原040开发运行器只适配原固定源目录，不能直接当新分析运行器重放。
4. 满足执行约束后按预注册保留所有槽位、失败与NOT_RUN，先比较合同有效性；有独立语义评判依据后再作质量主张。上述5个历史failed任务的根因仍待更充分证据，当前不据此盲改产品。

本次小目标完成的是测试基线和可核对的数据分析准备。**Pi自动发现问题→开发→真实质量对照→安全发布的完整闭环尚未完成**。保持`automatic_execution=false`、`release_allowed=false`；没有合并main、部署或启用每日自治。

原始离线日志/JUnit与私有审计程序留在主工作区`.local/pi-baseline-20261020/`和`.local/pi-analysis-audit-20261020.py`；公开回执给出日志/JUnit哈希，未将私有素材纳入Git。

独立审查覆盖本轮两项小目标：无阻断或实质问题；回执与原始审计字段、日志/JUnit哈希一致，生产代码未改。提交与推送结果以Git远程SHA核对，不以计划复选框代替。
