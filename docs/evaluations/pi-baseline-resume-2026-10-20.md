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

待执行。45项语义质量指标仍unknown，未建立真实质量改善结论。本轮暂未发起模型请求或发布候选。