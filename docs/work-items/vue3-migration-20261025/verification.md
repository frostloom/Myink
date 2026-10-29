# Vue迁移首阶段验证记录

对象：`/Users/a1/.codex/worktrees/myink-vue3-migration/Myink`，分支`codex/vue3-migration`，基线`a96066c43b41e535da4b73e260a998ba9350c415`，成果为未提交工作区差异，不把HEAD当作实现版本。

## 范围

已实现：单锁双构建、Vue独立root/深链、会话恢复与服务端验证、长短篇作品列表与草稿/删除、未迁移路由显式提示、全路由登记门禁、72份旧测试追踪、React/Vue CI入口。

未实现/发布阻断：登录/注册/MFA界面、滑动续期、完整游客壳/侧栏/反馈、主题媒体交互、创建流程、编辑器/SSE工作台、管理员。Vue只用于迁移预览，生产默认仍React。Pi不处理。

## 基线与测试先行

- React迁移前：72文件599项测试通过；build退出0；lint退出0但有12条既有warning，构建有既有大chunk warning。
- 首次Vue空实现：14项中13项失败，覆盖会话信任/网络/切号和列表行为，随后实现并转绿。
- App空实现：26项全部失败，随后实现认证闸门/明确pending路由并转绿。
- 曾有测试定位错误：列表与侧栏同时显示旧版作品，查询改为main范围，未修改产品行为掩盖失败。
- 路由对照测试最初未标准化React通配符（/*），修正后独立验证漏路由门禁：临时删除/admin/users/:userId，测试以明确缺失路由退出1，finally恢复文件。
- 初次Vue lint的TS解析错误已复现并修正独立TS parser；不是关闭lint规则绕过。

## 已运行的浏览器与配置检查

- Vue合成Chromium：11项通过，回执`/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-vue-browser-KmX2BP/receipt.json`。
- React原合成Chromium：第一次失败于未模拟writing-resources/updates和writing-resources，并非业务代码回归。补齐完整契约fixture后通过，保持unknown_routes必须为空的断言。失败回执保留`/tmp/myink-react-browser-vue-foundation-20261025/receipt.json`，通过回执`/tmp/myink-react-browser-vue-foundation-20261025-fixed/receipt.json`。
- 开发服务器5174实际请求/、/long、/short、/projects/example/settings均200且返回Vue main.ts，不是React main.tsx；已停止此测试服务器。
- Node语法检查两个浏览器脚本通过；git diff --check通过。
- 浏览器仅loopback合成API/SSE，不证明真实API/RLS/worker/队列/数据库或生产发布。没有调用真实模型。
- 原React源码与生产Docker入口未修改；新增Vue依赖使三个既有传递依赖小版本变化（nanoid/postcss/source-map-js），需两套完整检查。

## 最终门禁

最终npm ci后两套lint/test/build复验、独立审查结果在本记录后续追加。未运行完整Python/Go/Docker集成，不报告其通过。依赖安装有既有/传递依赖audit提示，本轮未自动执行audit fix或扩大升级范围。

## 最终复验与审查（2026-10-25）

- 干净`npm ci`退出0。
- React `npm run lint`退出0（12条基线warning未扩大）；`npm test`72文件599项通过；`npm run build`退出0（既有大chunk warning）。React产品源码无变更。
- Vue `npm run lint:vue`退出0；`npm run test:vue`4文件49项通过；`npm run build:vue`含vue-tsc/node配置类型检查，退出0。
- 最终Vue Chromium 11项通过，回执`/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-vue-browser-8kNDfB/receipt.json`。React Chromium 10项通过，回执仍见上述fixed目录。
- 路由门禁临时移除管理员users路由时明确失败，恢复后通过。所有72份旧测试均在coverage.md登记。
- 全量类型检查曾报路由对照测试静态导入React TSX的TS6142；改用Vite eager glob运行期读取真实路由，显式RouteObject类型；未关闭Vue类型检查，最终构建通过。
- 新增会话校验中到期测试先失败（checking而非anonymous），修复request_aborted时重新同步存储后通过；新增旧401不得清新账号、切号旧列表晚回及卸载后旧删除回包测试通过。
- 切号测试曾捕获已卸载的旧main DOM并等待该节点，修正为每次重查当前main；未修改产品代码掩盖此测试定位问题。
- 独立只读审查及修复后复核均未发现P1/P2；静态审查不是测试证据，真实服务集成仍未运行。
- `scripts/ci-local.sh`增加Vue lint/test/build门禁（仅修改检查入口，本轮没有运行会启动/清理服务的完整脚本）；GitHub CI加入两套浏览器检查。
- `git diff --check`与浏览器脚本Node语法检查通过；本地CI脚本bash语法检查通过。

结论：首阶段“双构建+会话恢复校验+作品列表+防遗漏门禁”通过上述范围验收；完整Vue迁移、真实服务集成与发布仍未完成。成果未提交、未推送、未合并、未发布。没有改Pi或生产Docker入口，原目录未提交工作保持在原处。
