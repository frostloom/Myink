# Vue 迁移第二轮规格评审 — 2026-10-26

范围：creation/short/workspace/task恢复；基线HEAD `a96066c43b41e535da4b73e260a998ba9350c415`，直接阅读未提交与untracked实现。已检查AGENTS，无更深web指令；已读brief、coverage、progress、renewal-fix-verification。未改生产代码、旧测试或提交；Hindsight两秒超时，跳过。

## P2：初始化任务历史慢回可覆盖刚发起的任务

规格：brief.md:107 “慢快照不能覆盖新SSE状态；切任务/切书后旧回包无效。”

生产位置：`web/vue/src/pages/WorkspacePage.vue:270–315`，缺少校验285–287、覆盖状态309–314。初始化在章节列表之后查询全项目任务，返回时只比较projectId；没有像按章历史查询那样捕获并核对taskStartVersion。

触发：打开长篇时初始任务历史请求延迟。请求快照中的第3章旧任务已在服务器结束，作者随后成功开始第13章任务；旧历史响应此时才返回。handleTaskStart已增加taskStartVersion并接管task-13，但初始化回包仍把activeTaskId改成task-old，selectedCid切回第3章，正文视图/时间线及Plan操作跟随旧任务，丢失当前任务展示上下文。服务器新任务仍运行，不能把此问题误称为服务器取消或已证实重复生成。

实证：新增 `web/vue/src/pages/review-second-spec-history.test.ts:135`。deferred listTasks保持初始回包，真实WorkspacePage处理新任务回调后先断言`timeline-task-13-chapter-13`存在；释放旧回包后该断言失败，实际DOM为`timeline-task-old-chapter-3`。运行 `cd web && npm run test:vue -- vue/src/pages/review-second-spec-history.test.ts`：1项失败，exit1，无skip；最终复跑同样1失败，输出在`/tmp/myink-second-spec-result.log`。测试沿用已有工作台替身，只控制API时序，没有改写生产逻辑。

旧React `web/src/pages/WorkspacePage.tsx:269`也存在同一漏洞，因此这是未满足已批准迁移契约的继承缺陷，不宣称Vue新引入。应对初始化整段恢复使用任务启动代次校验，确保旧回包无效。

## 限制

同URL仅更改history.state的人工实验未找到自然产品入口，不列缺陷，不保留该RED断言。未重新运行完整门禁或真实worker/模型；本轮单项RED不能由先前541项通过覆盖。上一轮Account/Environment续期及旧final/workspace审查关闭项未重复报告。
