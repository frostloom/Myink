# Replacement readiness：两项 P2 修复开发记录

2026-10-26，工作树 `codex/vue3-migration`；保护全部已有未提交迁移。未提交、推送、合并、发布或操作共享运行服务。开发角色至本报告完成后停止写入，等待独立验证。

## 文件范围与行为

仅生产 `web/vue/src/session.ts`、`web/vue/src/pages/WorkspacePage.vue`；对应回归 `web/vue/src/review-second-session.test.ts`、`web/vue/src/pages/review-second-spec-history.test.ts` 及本报告。

- 密码成功操作不再被普通同账号 revalidate 的 generation 变化吞掉。成功 login/register/MFA 维护独立 loginVersion，使旧密码操作不能清理后来已完成的新登录。原 token 仍在 storage 时结束会话并显示重新登录提示；storage 已换 token 时重新向服务端校验，而不盲目清理。撤销凭证变 anonymous 并补密码修改提示，仍有效的新凭证保留；不同账号受 owner/正常 revalidate 保护。
- Workspace 初始章列表后的自动选章及初始全项目 listTasks 查询均绑定 taskStartVersion。新任务开始后旧初始化链不能再改变选章或任务。同步 workspaceVersion 绑定 owner/project 的每次变化，防止 A→B→A 迟到响应复活；loadChapters 的状态更新及初始恢复链也拒绝已卸载页面。
- 不改变原有 saved active write、已有任务恢复、optimistic chapter 与相关 materialization 行为。

## RED 证据

1. 修改前实际运行 `npm run test:vue -- vue/src/review-second-session.test.ts vue/src/pages/review-second-spec-history.test.ts`：2 文件、3 tests 均失败；两个 session expected anonymous/actual authenticated，history expected task-13/actual task-old，符合原发现。
2. 增加后来同 owner/不同 owner 有效登录与有效跨 tab token 后运行：3 failed/2 passed。新跨 tab 用例证明旧实现没有在成功密码操作后重新验证新 token。
3. 加入 renew、初始化恢复、项目往返、卸载等边界后，临时撤掉新 token 与 Workspace 初始化/生命周期守卫并立即恢复：5 failed/6 passed。失败为 rotated token、有效跨 tab token、renew revoked token、初始迟到历史、项目往返历史；恢复后9关联文件95 tests通过。该次临时撤守卫运行不是完整恢复旧生产实现，故不将它称为全部原始缺陷复现。
4. 初始新增迟到章节 fixture 使用了无效 ChapterStatus `unreviewed`，类型检查确实报错；已修正为产品实际 `awaiting_review` 并重新通过类型检查。此错误仅在测试 fixture，不是产品问题。

## GREEN 验证

- 关联9文件：95 tests passed（session、auth、account、Workspace普通/live、历史回归、WorkspaceLifecycle、WorkspaceExportLifecycle）。
- `npm run test:vue`：75文件552 tests passed，exit0；该完整运行在最后补充账号往返1例之前。
- 最后账号往返边界增加后，两缺陷文件重跑：2文件12 tests passed，exit0。
- `npm run typecheck:vue`：修正fixture后通过；最终账号往返追加后再运行亦通过，exit0。
- ESLint + oxlint 针对上述4代码/测试文件通过；最终账号往返追加后再运行亦通过，exit0。
- 无 skip。未运行构建、React回归、浏览器、Python/Go、真实链路；这些由总流程独立测试角色承担，不能从本报告推断通过。

## 覆盖边界

同 token revalidate；同 owner token轮换撤销；定时renew轮换撤销；后来成功同账号与其他账号登录；来自另一tab仍有效的新token；原密码变更/换账号保护。初始化原任务恢复；新任务后迟到历史；迟到awaiting_review章；项目往返；账号往返；卸载后迟到章节不再启动恢复查询。原9文件还覆盖已有会话和Workspace恢复行为。

Hindsight recall 服务不可达（curl exit7），已按项目规则跳过。

## 后续真实TLS发现：functional字段的原生change透传

独立真实链路在`/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-vue-chain-browser-uIbIrn/receipt.json`记录构建`index-CyxwGv2c.js`通过登录、真实入队以及Vue↔React恢复，但Plan编辑后未发confirm POST，页面进入RouteBoundary，实时写作等待超时。开发读取receipt/failure.txt后追踪`ListField`→label→StructuredTextField的事件边界。

新增`ChapterPlanPanel.test.ts`真实`input`→原生bubbling `change`→`blur`→确认测试，修复前**1 failed/7 passed**，并产生`TypeError: items.join is not a function`。根因是functional `ListField`的`onChange`未声明为props且默认继承到根label，原生change再次调用该回调，把Event写入goals。

最小修复为`ListField.inheritAttrs = false`，保持既有结构化解析与业务回调。未给join增加兜底掩盖类型污染。

同类审查确认`StyleLibraryPage.vue`的functional `MainField`也有相同label根+onChange。新增自然用户路径：新建→提取文章→编辑禁用表达→change/blur→保存；修复前**1 failed/2 passed**，Event覆盖数组后该字段被editable过滤并消失。用相同`MainField.inheritAttrs = false`修复。`ProfileFields`为Fragment根，其他functional纯展示或只有非原生onNavigateChapter回调，未发现同源原生事件问题；未无关修改。

追加范围仅上述2生产文件、2既有测试文件与本报告，不触碰打包或浏览器harness。修复后两文件**11 tests passed**。测试命令曾附带不存在的`StructuredTextField.test.ts`路径，Vitest仅匹配2文件；本记录不声称存在该第三文件覆盖。最终`npm run typecheck:vue`及这4文件ESLint/oxlint均exit0；ESLint对ChapterPlanPanel既有多组件结构给出2条`vue/one-component-per-file` warning（0 errors），未做无关拆分。完整Vue最终76文件561 tests passed，exit0（Vitest 4.1.12，235.72s，maxWorkers=2；未跳过测试）。必须重建Vue并以新资产身份重新跑真实TLS浏览器链路，旧Cyxw receipt不代表修复版本通过。

## 后续确认：两处Rail重复调用登出回调

`ProjectRail.vue`和`AdminRail.vue`的`leave`同时`emit('logout')`并显式调用`props.onLogout()`。Vue emit会调用同名`onLogout`监听器，即使该名字同时在props声明；因此页面已传`onLogout`时，一次点击触发两次同一函数。未提供prop时只有auth fallback执行一次。

仅修改这2个rail及既有`ProjectRail.test.ts`：新增参数化两rail显式handler单次点击测试和ProjectRail fallback回归。修复前**2 failed/5 passed**，两项失败均为expected once/actual 2 times；修复后移除冗余defineEmits和emit调用，保留原callback/fallback的await，关联Rail/session/auth/AdminTaskDetail **4文件49 tests passed，exit0**。

已确认双调用可能使session.logout第二次invalidate中止第一次，但未将真实浏览器此前502直接归因此缺陷；无新服务端证据支持唯一因果。Ddk资产快照不包含此后修改，实际浏览器验证通过也不能证明新rail修复；后续候选需重建再冻结。未更动打包、harness、session或后端。最终`npm run typecheck:vue`和2rails+测试文件的ESLint/oxlint均exit0、无warning。随后串行完整Vue回归：76文件564 tests passed，exit0，无skip（153.63s）。

全量`defineEmits`/`emit`/`emits`归并扫描剩余仅VersionHistory(close/restored)、ChapterEditor(notFound/saved/memoryChanged)、ConnectionNotices(dismiss)、ProjectsPage(logout)；检查其props与调用路径，均无同名props回调再显式调用的重复分发。

## 后续真实链路：SSE终态之后observer尾帧导致重放挂起

实际隔离worker任务`41d8e6f7-dd07-484f-8c05-9ee4cb2a3c38`共59帧，末尾`persist`→`status done`(1792989433763-0)→`node summarize`(1792989434123-0)。live收到done，但从中间artifact_delta的Last-Event-ID重连一直心跳、没有done，详见`readiness-real-chain-edge-replay-blocker.json`。根因是`routes_sse._replay`把任何后续帧视为续跑，跳过历史终态；observer在done之后正常发布summarize/metrics并不代表任务续跑。

仅后端`src/myink/api/routes_sse.py`及`tests/test_sse.py`追加修改，无Pi/schema/worker/打包/harness修改。新轮worker/入队会明确发布`event=status`的queued/running等状态，因此只有后续权威status才能替代历史终态；普通node/artifact尾帧不能替代。Last-Event-ID已在终态之后时，向前读取最近权威status用于判定收流，保持只发送严格大于游标的帧，不重复旧done的ID。若游标之前已有running续接，则仍开放live流。内部_replay增加closed返回值，供_stream在没有待发terminal时也能正常关闭。

新增17个确定性replay回归：五种终态×metrics/summarize尾帧；awaiting_plan/review×queued/running续跑及最终done尾metrics；游标位于done/metrics时严格不重发旧ID、不进入live；游标已越过running不能误按旧awaiting_review收流。修复前**16 failed/1 passed**，修复后**17 passed，33 deselected**（运行选定新用例而非skip）。`compileall`限定2文件exit0。完整`tests/test_sse.py tests/test_worker.py tests/test_events_api.py -q`在独立专用DB/Redis中串行运行：**95 passed，0 skip，exit0，93.52s**；唯一warning为Starlette BlockingPortal deprecated别名。测试结束已通知真实链路角色释放资源，允许其执行后续隔离全量回归与API镜像重建。
