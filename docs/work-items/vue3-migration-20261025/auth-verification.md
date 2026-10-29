# Vue 认证迁移验证记录（2026-10-25）

## 对象与边界

工作区`/Users/a1/.codex/worktrees/myink-vue3-migration/Myink`，分支`codex/vue3-migration`，基线HEAD `a96066c43b41e535da4b73e260a998ba9350c415`。成果为首阶段与本轮认证的未提交差异，不把HEAD当作实现版本。未提交、推送、合并、发布；不处理Pi，React仍生产默认入口。

本轮实现：登录、邀请注册、MFA二步验证、公开/login、服务端已验证角色落点、会话续期/到期/前台检查、跨账号与旧令牌保护、离线/超时退出。AccountPage改密与MFA设置界面、工作台、后台、主题媒体仍pending；不是完整Vue迁移。

## Superpowers执行及独立审查

计划`docs/superpowers/plans/2026-10-25-vue3-auth.md`，台账`.superpowers/sdd/2026-10-25-vue3-auth/progress.md`。认证服务与UI在不相交文件范围并行实现，任务接口预先冻结，集成后统一复验；独立服务、UI审查和修复复核均只读。

- 服务最初12项RED；后续增加续期挂起、存储异常/退出期限和跨账号轨迹，最终session定向36项通过。详细命令见auth-service-report.md。
- UI最初App3项及登录页13项RED；MFA切号清挑战、未知路径管理员落点均补RED→GREEN。详细命令见auth-ui-report.md。
- 浏览器新真实登录验收在旧dist-vue缺少用户名表单时退出1，RED回执`/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-vue-browser-twsJEY/receipt.json`。
- 独立服务审查P2：removeItem/getItem抛错使logout拒绝并卡checking。新增4个RED及新账号保护用例后修复；存储不可判断时不盲删凭据，清内存并明确提示，不能声称删除已成功。审查者原/tmp探针1/1复验通过。
- 独立UI审查P2：校验不可用页遗漏React的退出按钮。新增offline验证→退出→offline撤销仍本地退出的RED后恢复按钮；复核已解决。
- Fixture非阻断缺口同轮修复：未知无令牌请求被通用401遮盖。探针先RED401!=500，前置path+method白名单后独立复核通过；UI启动前的自测条目单独记录，不清理真实UI请求。

## 最终命令证据

- `npm run lint`退出0，保留12项既有React warning；`npm test`72文件599项通过；`npm run build`退出0，既有chunk大小warning保留。
- `npm run lint:vue`退出0；`npm run test:vue`6文件100项通过；`npm run build:vue`含vue-tsc/node配置类型检查，退出0。
- 原React合成Chromium回归退出0，10项通过；回执`/tmp/myink-react-browser-vue-auth-20261025/receipt.json`。
- 最终Vue合成Chromium22项通过，回执`/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-vue-browser-BMZdeo/receipt.json`；整合终审的401存储异常P2已RED→GREEN并通过范围复核。
- `git diff --check`和浏览器脚本Node语法检查退出0。

## 尚未验证

没有运行真实API/数据库/RLS/Redis/RabbitMQ/worker/Caddy链路、真实双标签浏览器或生产发布；跨标签时序当前由组件/服务测试模拟storage事件，续期由fake timers/可见性事件验证。浏览器使用真实Vue构建+loopback合成API，无真实账号/模型/数据库写入。全量Python/Go/Docker CI未运行，不声称通过。

## 决策说明

沿用已批准迁移设计后直接执行细化计划，避免重复批准；保留未提交成果不强行提交以制造审查区间，因此审查读取工作区及未跟踪文件。代价是记录以测试命令/文件范围为准，不能仅靠HEAD识别实现。没有遗留已确认P1/P2待处理。

## 整合终审补充

终审发现缓存校验401且removeItem抛错时仍可使start拒绝。新增真实RED后引入局部failClosedStorage，统一失效化在途操作、清内存、停止旧请求、unavailable和明确提示；新增旧校验401期间换b不删b的回归。最终服务38项、全Vue100项通过。整合审查者范围复核确认P2已解决，无新增P1/P2。独立服务/UI/整合审查中已确认问题均关闭；没有延后处理的审查建议（fixture非阻断项也同轮修复）。

主代理最终复验：Vue lint退出0、6文件100测试通过、vue-tsc/node类型检查及Vite构建退出0；候选入口index-Y5Rlifw5.js。原React源码、后端/Pi及生产Docker入口均无本轮修改。
