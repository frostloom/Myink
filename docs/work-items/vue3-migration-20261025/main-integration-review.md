# Main集成与React替换复审（2026-10-26）

历史结论：目前不建议直接将这批改动按“main已默认替代React”放行。候选已执行的测试/镜像证据有效，但复审确认2项P2需关闭，并需完成默认入口切换。此前笼统“全部门禁完成、无关键遗漏”的结论需要收紧。

当前更新：两项P2与默认入口切换已完成，见[修复与最终复核](main-cutover-fixes.md)。下文保留修复前评审证据，不代表当前开放问题。

## 对象与方法

main与迁移HEAD均为a96066c43b41e535da4b73e260a998ba9350c415；实际迁移都在codex/vue3-migration未提交工作区。审查git diff main --及git ls-files --others --exclude-standard，不能用空的main...HEAD差异冒充已审迁移。主工作区仅有既有未跟踪.DS_Store及docs/work-items，未修改。当前没有可直接通过分支merge带入的迁移提交；这属于提交准备状态，不是产品缺陷。

独立两轴：Standards检查AGENTS/协作规则及代码正确性，Spec对照brief/coverage/最新main替代目标。只读源审查与轻量故障注入，不重跑完整测试，不创建真实服务，不修改产品。

## Standards：1项P2

**[P2] 资产提取helper在create结果不确定时跳过回收**。scripts/prepare-frontend-assets.py:37-38只在docker create成功返回后才created=True，finally:58依赖该标记。若daemon已创建临时容器，但CLI报错或超过60秒，标记仍false，rm -f -v不会执行，可能残留容器及Caddy匿名卷。

本轮以原helper复制到TMP，用fakeDocker让create创建资源标记后退出70；helper退出1且标记残留。没有真实容器，不表示前轮已清环境存在残留。原始回执main-review-partial-create-receipt.json；独立Standards复核确认。应在尝试create之前登记唯一名称的清理责任，失败路径仍回收并正确记录不存在/回收失败；同仓库api-image-smoke.py已用该模式。

其余静态审查未确认新增Vue业务代码阻断。独立node merge测试3/3通过；另一组定向Vue测试在加载阶段因沙箱EPERM无法写node_modules/.vite-temp，未实际运行，不计通过也不计产品断言失败。没有为此修改配置或扩大权限跑整库。

## Spec：1项P2

**[P2] 约定的浏览器与屏宽矩阵未完成**。brief.md:174明确要求Firefox/WebKit关键编辑、下载、媒体、路由冒烟，以及390/768/1440屏宽。web/scripts/vue-browser-smoke.mjs:95及所有其他浏览器入口仅chromium.launch，现存回执没有Firefox/WebKit执行证据；脚本实际屏宽390/1440（真实链路1600），也没有768执行记录。

这是未验证而不是已证明这些浏览器失败，不能用Chromium564组件测试/真实业务11来替代。应保留现有Chromium证据，补Firefox/WebKit所列关键行为及768布局回执，或经明确决策变更支持范围并披露，不能维持“完整方案全部门禁通过”的表述。

## 最新替代目标还需要的集成收口

- web/package.json:7-11的dev/build/lint/test/preview、web/index.html的main.tsx、vite.config.ts仍指React。brief.md:176要求正式切换后默认命令覆盖共享TS+Vue，保留*:react回退入口。
- caddy/Dockerfile:12与docker-compose.yml:251仍默认FRONTEND_VARIANT=react。因此当前代码作为隔离候选符合先前授权，但直接并入main/按旧默认构建不会替代React。需有明确Vue默认入口变更和相应主线CI验证。
- 旧公开资产被Git忽略，干净checkout只有.gitkeep；本地已验三镜像与8文件窗口不等于仓库自动生成保留资产。按runbook获取/捕获当时实际旧镜像并复验，同时发布SSE补丁API；React回退继续使用修复API，不动schema。
- 整理精确迁移文件后按授权提交，再评审实际提交差异/主线构建；当前main与HEAD无漂移，未发现已提交源代码合并冲突，未来提交前仍需重新核对main。

规范1项P2，需求1项P2；没有把跨轴发现混作测试失败，也没有把正常待提交状态列为代码缺陷。本轮不提交、合并、推送或发布。
