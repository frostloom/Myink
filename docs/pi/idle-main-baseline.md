# idle 时人工主线发布的基线交接

2026-11-09 新增 `idle_baseline` 控制器入口。人工发布后，在原 Gate 空闲且原 nightly/maintenance 两把锁内，核验 root 签发的 `pi-idle-main-baseline-v1` 许可、上一已部署周期结果、新部署身份及代次、镜像完整 Python 包、原账本、实际指标源和已固定 runtime。独立回执写入 `control/manual-baselines/<operation UUID>/verified.json`，原审批周期和旧观察结果保留。

`nightly-driver.json` 可增加 `manual_baseline` 字段，值为许可 operation UUID。此字段绑定当前 driver 摘要及固定 `config/manual-handoffs/<operation UUID>.json`；新夜间源码阶段只采用已完成物理核验的回执。后续 Pi 的真实部署比较完成后，自然使用新的比较来源。空闲交接只登记新基线，不代表比较完成或质量改善，也不批准候选发布和模型调用。

使用已封闭、已固定摘要的 runtime，调用 `entry.py --component idle_baseline --config <固定许可路径> --config-sha256 <许可摘要>`。ACTUAL 禁止注入模拟 verifier。新基线未完成、原意图不明、配置/镜像/费用漂移时拒绝继续，保留现场；已有完成回执仅作幂等核对。上线操作仍须独立授权并同步维护屏障、部署身份和完整 driver/profile/observer 配置。
