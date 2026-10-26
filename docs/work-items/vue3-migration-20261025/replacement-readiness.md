# Vue 替换验收报告（2026-10-26）

最新状态：发布安全P2已修复并完成新产物验收；见[safe-update-fixes.md](safe-update-fixes.md)。下文保留对应历史阶段事实。

当前更新：再次复审发现发布安全需求遗漏，两项P2待修复；详见[再次复审](recheck-release-safety.md)。下文为此前已执行结果，不能据此放行发布。

Main集成复审的两项P2现已修复，默认开发/构建/Docker/Compose已切Vue，三个浏览器与768px验收通过，独立最终复核无阻断。当前结论与最新镜像见[默认Vue修复报告](main-cutover-fixes.md)。下表保留既有真实链路验收，未提交、合并或发布；Pi未处理。

## 候选身份

- 工作区：/Users/a1/.codex/worktrees/myink-vue3-migration/Myink；分支codex/vue3-migration；基线a96066c43b41e535da4b73e260a998ba9350c415。全部迁移与修复仍未提交，HEAD不是最终成果身份。
- Vue入口index-LHE4QUm9.js，JS SHA256为8ace8616b0dc484c661be17834853f6a81fc1c95f4179f185173f46a2f12f51a；HTML SHA为cf8afe03dd7800c22a54bf0b5337c6e0bf781a010b8cea97334c60cba13825b0。生产图818模块，无React运行时/旧TSX。
- 当前React构建index-BDxdzfd9.js；只读取得的原线上历史React为index-Cvlt329b.js。旧Cyxw/Ddk浏览器数据保留原身份，不混称最终LHE。
- 同时交付src/myink/api/routes_sse.py小范围修复。源码/锁文件摘要与镜像ID见build-provenance.json；真实browser快照已逐字节与当前Vue输出比对一致。

## 最终实际执行

| 门禁 | 结果 | 证据 |
| --- | --- | --- |
| Vue完整单测 | 76文件564 passed，0skip | readiness-defect-fix.md；最终MaxWorkers2，不延长5秒断言限制 |
| Vue类型/lint/build | 全exit0，7既有多组件warning，大chunk提示保留 | /tmp/myink-vue-lhe-lint.log、/tmp/myink-vue-final-rails-build.log |
| React共享锁回归 | 72文件599 passed、lint/build exit0；12既有lint warning | readiness-packaging.md及原验证记录 |
| 依赖安全 | npm audit 0已知漏洞 | Vite8.2.4/Vitest4.1.12补丁更新；Node24.22.x与CI/容器对齐 |
| 最终LHE合成浏览器 | 标准27、工作台10、长文本/媒体/IME/反馈24全通过 | readiness-browser-load.md；/tmp/myink-vue-lhe-{workspace,readiness}/receipt.json |
| 修复后Python完整回归 | 1966 passed，1 skipped，5 xfailed，2 subtests passed，exit0 | readiness-final-python-tests.log；192.34s |
| 实际API/模型HTTP/队列/worker/DB | 长短篇13、MFA/admin/资源/附件/密码10已有实际证据 | readiness-real-chain.md；HTTP模型为本地确定性fixture，不调用付费服务 |
| 最终实际HTTP/可信本地CA TLS/SSE | 4 passed；新任务增量＋原真实done→summarize修复重放及游标后EOF | readiness-final-real-chain-edge-receipt.json；回放约21ms、游标尾约16ms结束 |
| 最终LHE真实浏览器 | 11 passed，0pageErrors/0HTTP5xx；两rail各一次logout POST200 | readiness-final-real-chain-browser-receipt.json |
| 接口契约 | OpenAPI113路径导出字节完全不变 | 当前spec/API镜像合同摘要一致 |
| Vue镜像运行 | 7 passed；原生Vue、深链/cache、原Cvlt旧JS可取 | readiness-final-vue-image-receipt.json |
| 默认React回退镜像运行 | 7 passed；原生React且LHE旧JS可取 | readiness-final-react-image-receipt.json |
| API补丁镜像 | SSE源码SHA一致；25核心依赖与测试venv逐项相等；113路径契约/healthz200 | readiness-final-api-image-receipt.json；原API镜像同门禁明确拒绝 |
| 旧资源与负向门禁 | 两前端镜像8个JS/CSS逐字节同集；碰撞/symlink3项通过；非法selector退出64且无产物 | retained-assets-receipt.json、readiness-final-invalid-selector-build.log |
| 清理与隔离 | 自有真实服务及镜像测试容器/网络全清，8专用端口无listener，原栈仍运行 | readiness-final-real-chain-cleanup.json、readiness-final-packaging-cleanup.json |

合成浏览器实际覆盖400章节、2万/5万Unicode编辑、51672点250帧、重放去重、滚动暂停/跟随、409草稿保留、组合输入不误提交、真实PNG/WebM持久化后解码播放、reduced-motion及URL回收、反馈文件跨路由、键盘焦点环与390px视口。React/Vue A/B性能数据与最终LHE补验分开记录，不作“Vue必然更快”的承诺。

真实浏览器通过TLS实际登录，触发Rabbit真实入队/worker调用本地模型HTTP，编辑计划确认到写作done；活动任务Vue↔React同源切换恢复会话/主题/脏草稿而不重复入队；短篇资源优先、明确手动开始、实际worker完成和刷新恢复；反馈multipart与授权blob、真实TOTP管理登录/3图表及双rail单次退出。最终255条AgentRun中143模型行均fixture-local，其余112内部行零token；fixture记录143次实际HTTP且仅该模型，无外部模型调用。

## 已关闭的确认缺陷

1. 同owner续期/重验让密码变更结果被错误忽略；保护后续有效登录和换账号，独立边界回归通过。
2. 初始化晚到章节/任务历史覆盖新任务；增加项目、账号、生命周期与启动代际所有权校验。
3. Plan functional ListField原生change把Event写入数组导致确认崩溃；真实input/change/blur先RED后修复。
4. 文风MainField相同原生事件透传导致禁用表达字段丢失；同源RED修复、独立复核。
5. 两rail同时emit与调用onLogout，一次点击实际双调用；2RED后修复，最终Workspace/Admin各1真实POST200。
6. 后端SSE把完成后的observer尾帧误当新一轮任务，跳过done并永久等待；17边界先16RED/1GREEN后全GREEN，相关95与独立17通过，原真实失败事件在新handler上复验通过。实际queued/running续跑与严格游标语义保留。

镜像selector原本忽略Vue、旧资产裸覆盖风险、验收清理失败仍可报绿也已修复并独立复核。API镜像验收另以无真实容器的故障注入确认“创建后CLI失败”仍会尝试回收，不会误报通过。

## 历史失败与边界

- 初次新库fullpytest误带fixture平台配置，11failed/21errors；保留失败日志，仅修隔离库/env后受影响92项及完整1966项通过，没有改断言或放宽产品规则。
- Docker曾异常停滞，自有构建取消130不计成功；临时broker曾zombie，恢复broker完成真实测试后原zombie最终也rm0。未重启daemon/未动其他项目服务。最终重新构建三镜像全部成功，无残留运行资源。
- 1skip为SDK消融评测硬编码localhost15432/myink身份，本轮隔离28432新库不能满足，明确未通过。5xfail是基线已有冲突语义检测sample5–9，明确不算passed，不属于前端迁移引入问题。
- 真实SSE尾事件由异步observer轮询产生，不是“每5章复盘”条件。确定性修复复验使用原样保留的真实worker59帧，新任务另证实时流式；未注入Redis帧。
- 未执行生产DNS/公网证书签发、真实手机硬件IME、长期旧客户端在线窗口、付费模型创作质量。已执行本地可信CA验证、Chromium组合事件/窄屏及真实模型HTTP传输链路，不能混称这些外部事项已通过。
- 当前仓库无gateway/go.mod，Go入口不适用。未运行占用固定myink-test端口的整合脚本，采用等价实际检查和专用资源；ci-local文案已准确标注额外浏览器/候选镜像入口。

## 替换与回退约束

发布另需明确授权。必须同步使用含本轮SSE修复的API，不能仅换前端后沿用已知有重放缺陷的旧API。没有schema/浏览器存储格式变化，React回退可继续使用修复后的API，不清作品和草稿。当前运行生产未切换；本迁移分支默认已Vue，最新镜像见main-cutover-fixes.md。历史候选镜像与回退镜像已分别构建且共享保留资产窗口。正式发布前固定授权提交/镜像身份并读取当时实际运行旧镜像，重新准备该次窗口，不能将本次8个文件理解为覆盖所有未来版本。详见preview-and-rollback.md。

- vue: `myink-caddy:vue-ready-final-20261026` / `sha256:3eb69714f94c5065e26a16f95a4fba66ec7718ca2d73b5cd9c297c2f3d3ba674`
- react: `myink-caddy:react-ready-final-20261026` / `sha256:32513ef95870cb847d796c5bf4fe6d021194a4afc15b69007301633f5a6d7335`
- api: `myink-api:vue-sse-ready-final-20261026` / `sha256:9b5fb658fd5b6c5fb4c36e7ed74e207bcd6d48364c29a23be1bfbc863cd32b9b`
