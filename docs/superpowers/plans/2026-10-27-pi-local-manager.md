# 本机管理器与指标记录实施计划

设计见 ../specs/2026-10-27-pi-local-manager-design.md。在已有Pi worktree内由主代理实现，采用TDD；完成后一次独立代码审查。用户已授权阶段提交推送，不另建分支，不合main或部署。

1. `ops/pi/manager.py` 与 `ops/pi/tests/test_manager.py`：显式初始化/注册、只读状态、串行有界批处理、稳定执行claim，pending/unknown停止；测试费用/输入/输出角色、漂移、取消与模式隔离。
2. `ops/pi/tests/test_manager_recovery.py`：独立子进程并发与崩溃注入，外部计数证明不重复调用；输出可重现脱敏验收数据，区分模拟和真实。
3. `docs/pi/engineering-metrics.md` 及验收JSON/MD：冻结旧基线来源、指标口径和简历可用措辞，保留拒绝与未知，不将业务测试增量归因于Pi核心改进。接线/回归、独立审查、必要TDD修复、阶段提交推送。

Review focus：事务后/调用前与调用后/回执前崩溃；两个进程竞争；注册pending与执行pending区分；费用账本/sidecar/源目录别名；默认只读；ACTUAL禁止注入模拟runner；请求与运行模式不可换；批处理不能超预算/自动重试未知；指标不得把claim当收费或把模拟当生产成功率。
