# Pi 前一天全天采集修复与真实发布回执

用户 2026-11-05 明确授权修复、推送并上线。采集代码 `1930e0aa0cb823ef387dc497795f6792d9d3eaeb` 和关联页面修复 `24c62e775be97ddd5eb81c397a40e7dedd4b962e` 均已合入并推送 main。管理入口：https://myink.cloud/admin/pi。

## 原因与现在的结果

原 nightly source 继承了部署后短时 observer 的一小时窗口。11 月 5 日 02:00 实际只采集北京时间当天 00:59–01:59，遗漏 11 月 4 日上午的写作。生产 tasks 及 Pi 固定只读指标接口均确认：11 月 4 日 10:19 一条 chapter_generate 失败，10:26 创建的另一条在 10:28 完成。旧零样本只描述那一个小时，不能代表全天无写作。

新 nightly source 为每轮独立派生 window_policy=previous_day_shanghai、lookback_hours=24 的 observer，精确覆盖北京时间昨天 00:00 至今天 00:00。原人工部署 baseline、部署后短时比较配置、source 模板及历史收据保持原字节。日历窗口与真实采集时间分开，新鲜度仍是45分钟，但按实际采集时间判断，且检查日历日期、原始 intent 和窗口一致性；旧滚动观察规则保持不变。新签发的研究 profile 使用当前已校验的封闭 worker runtime，以接受日历收据；原 host、策略、费用库和人工发布边界不变。

北京时间 11 月 5 日 14:02 进行了真实只读补采，没有注入时钟，也没有重放已结束的夜间轮次。窗口为 11 月 4 日 00:00–11 月 5 日 00:00，实际 2 条任务、1 完成、1 失败，observed_samples=1、minimum_samples=20，status=insufficient_evidence。仍保留 insufficient_samples、insufficient_tail_samples、unknown_identity 和 unmeasured_metrics 等证据缺口，不能据此宣称线上质量改善。

## 控制器与页面发布

封闭控制器 420 文件，runtime pin 为 `87400dd1b9066fd23596332e24af38727a18528ca0a7f4da39ae24f8851603ad`，目录 `/home/ubuntu/myink-pi-managed/releases/nightly-calendar-1930e0aa/runtime`。实际 root daily observer、诊断检查和 ACTUAL worker profile 校验均通过；原配置中仅 nightly.env 的入口和 runtime pin 更新，driver/source 模板摘要不改。14:04:07 安装核验收尾完成。旧 runtime 和环境备份保留。

首次安装检查因父进程持有 canonical nightly lock，子入口正确返回 lock_busy，导致检查脚本的 outside_window 断言失败。现场 intent、采集快照和已完成的 schema 校验保留；随后在原操作下只恢复元数据核验，释放锁后确认真实白天入口返回 outside_window，未重新采集、创建任务、调用模型或重放安装。

真实管理员页面验证又发现：运行索引按标识排序，旧前端直接取第一条，故新数据虽然已经导出，默认仍显示旧零数据轮次。页面现从当前页最多25条运行的最后事件中按全局 sequence 选择最近记录，最多4个并发读取；当前任务和手动选择优先，定位失败明确提示手动选择。范围为当前页，不宣称跨所有历史页的全局最新。

页面于 14:22:11 完成真实 Caddy 发布，新镜像 `sha256:201977f3c0a6e39e8a89b62282a582be91fc9f1ed75b120bdf90b782d490bc88`，保留旧镜像 `sha256:9ca75fda991af9b3410c6c86873140a9452d5f5b7f2b4dbd456fd3f47369b5ee` 及旧 Compose；5份当前静态文件经真实 TLS 逐字节核对，42份旧文件在候选镜像中核对保留。其余六个业务与依赖容器保持原 ID/镜像，Caddy 活动配置不变。

最终真实管理员浏览器无需手动切换即可显示1/20、证据不足及11月4日完整窗口；旧“没有写作数据”结论不再被默认选中。手动切到旧轮次仍能查看原零数据记录，回到自动选择重新显示1/20。桌面1440px、手机390px均无横向溢出，实际 release id 为 `vue-f3ac390538666de6cb6a28747f37fba7f8d8a5e2b5f81b1d065aa10fbdee013b`。诊断短期认证文件已删除，浏览器已关闭，仓库不保存凭据。

## 验证、费用与下一轮

- Pi 完整离线回归：4573项通过，63项专用测试未执行，1条既有 SyntaxWarning，846.88秒；此前中断的初次全量不计作通过。
- 前端共享209项、Vue全量843项通过；Vue使用单进程和15秒超时。Pi页面22项回归覆盖旧首行误选、失败不回退、手动优先及并发上限。lint无错误，保留9项既有警告，类型检查与构建通过。
- [部署代码 main CI 四项全部成功](https://github.com/frostloom/Myink/actions/runs/41979718445)，包含 Python、镜像、完整三浏览器矩阵和 Pi 离线门禁。采集提交1930e0aa的 Pi/main CI 也均成功。
- healthz、readyz、管理员页面200；真实管理员状态/历史/每日/事件读取200且no-store，匿名401、普通账号403。
- 本次修复、补采与发布模型请求0。50元预算、9笔未知预留、原费用逻辑摘要 fe7c37ea1259b0d92d51524d818703a7063a953e54e53b062dbc36b6eb844afb 和 manager 摘要 a588accf16ed7e7b1d3fc5e04709e000924010c6f840586ffbc2d2599ebf1eff 均不变。

Pi 当前 Gate idle、timer active/waiting。下次北京时间11月6日02:00按新规则检查11月5日全天；已在原审计预留02:15后续测试计划，尚未执行。此次证明真实全天补采和 worker schema可用，新的完整夜间日历路径仍待下一次实际调度核对；未宣称已执行付费开发、候选发布或线上效果比较。

根证据保留在 `/home/ubuntu/myink-pi-managed/control/calendar-day-20261105` 与 `/home/ubuntu/myink-pi-managed/control/calendar-ui-20261105-24c62e77`。版本、变更范围、验证和次日计划均已追加原审计。该回执之后若仅新增文档提交，不代表再次构建或发布产品。

[脱敏机器回执](pi-calendar-window-release-2026-11-05.json)保留精确版本、采集窗口、快照、权限检查、账本摘要和验证结果。
