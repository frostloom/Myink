# 管理员默认配置与高级设置验收

日期：2026-10-21（Asia/Shanghai）。开发分支 `codex/admin-control-plane`，工作区 `/Users/a1/.codex/worktrees/myink-admin/Myink`。最终代码提交 `c7ea467`；API 契约提交 `25277cf`。

## 交付行为

管理员集中设置模型路由、默认思考、预算和扫榜，普通用户无需填写连接或凭据。`/environment` 兼容原链接，入口名为高级设置，每次进入默认折叠；用户原有调整能力保留。普通工作区任务预算技术详情也默认折叠，预算暂停与投递修复操作仍可直接使用。

每个偏好按明确个人覆盖、平台默认、原部署/内置默认解析。false/0 是真实覆盖，旧账号已保存值保留；逐字段保存和恢复默认不清除其他偏好或未保存草稿。已有任务继续使用原预算快照。权限、平台配额及后台模型规则保持。

管理员就绪诊断检查六个实际角色的有效配置、协议、地址、凭据解密和默认值，不向供应商发请求。付费生成、入队与续跑前拦截缺失配置；worker 执行时重查，配置失效会保存 `PLATFORM_NOT_READY` 并发布失败终态，普通用户收到统一安全提示。永久认证/无效请求错误不反复重试，408/429/5xx/传输故障沿用最多四次尝试及原退避、预算和流式重置。

## 测试与独立审查

开发按 Superpowers 设计、计划、测试驱动、独立审查、复验执行。三阶段均先观察有意义的失败，再实现。Task1/2 独立审查通过。Task3 全量回归暴露13个旧测试未提供模型前置条件，仅使用现有 provider fixture 修复并保留原断言，173项针对性回归及独立复审通过，生产检查未放宽。

最终整轮审查发现三项 Important：跨区/同区其他字段草稿丢失、默认工作区预算详情暴露、入队后配置失效缺少错误与终态通知。统一修复在 `c7ea467`，对应 RED 为前端6失败/12通过、真实 worker 配置失效1失败；GREEN 为前端18、worker1，扩大后端240。最终独立复审三项均 ADDRESSED，无新增 Critical/Important 或其他遗留发现。

最终源代码检查：

| 检查 | 结果 |
| --- | --- |
| `python -m pytest tests/ -q` | **1689 passed, 1 skipped, 5 xfailed, 2 warnings, 2 subtests passed**，158.18秒，exit0 |
| `npm test`（web） | **60文件，487 passed**，exit0 |
| `npm run lint`（web） | exit0；12条既有警告 |
| `npm run build`（web） | TypeScript/Vite成功；既有大于500kB chunk提示 |
| `myink contract export` + 对已提交契约diff | 99条路径，无差异 |
| `python -m compileall -q src tests` | exit0 |
| `python scripts/evaluate.py validate` | 20审计案例、40目录条目、8检索和2对比条目合法 |
| `git diff --check` | 无空白问题 |

全量后端日志 `/private/tmp/myink-admin-final-pytest-3.log`。最终前端日志 `/private/tmp/myink-final-fixes-frontend-full.log`、`myink-final-fixes-frontend-lint.log`、`myink-final-fixes-frontend-build.log`。这些日志保留本地，完整结果以上表为准。

1个跳过来自评测对照集成测试：它要求额外明确授权的localhost:15432数据库身份及MYINK_EVALUATION_SYSTEM_ID，本轮使用独立25432环境。5个预期失败是原冲突样例5—9的未实现检测机制，没有改为通过。2个后端警告为 Starlette/anyio弃用提示、HS512负例测试密钥长度提示。12个lint警告和包体积提示均为既有项，不报告为零警告。

## 实际浏览器验收

使用实际构建产物与 FastAPI、管理员和普通账号、专用数据库 `myink_admin_browser` 与Redis1；自动测试使用另一数据库/Redis0，均处于本轮临时服务中。

- 普通首页没有模型/预算配置表单；高级设置进入及重新进入均折叠，主动展开可调整，真实键盘空格可折叠。
- 个人请求上限7保留；管理员默认改为120请求/8元后，用户请求仍7、费用随平台变8；逐项恢复后请求变120。
- 重置扫榜超时20至10时，未保存预算9、扫榜条数30、思考开启均保留；保存预算后其他两项草稿仍保留。
- 普通账号直接访问管理配置被拒绝；管理员能修改默认值、查看并刷新六角色诊断。
- 缺失配置时普通短篇请求返回503通用提示，输入保留。随后以专用管理员连接查询 projects、agent_runs、tasks均为0，账号平台使用计数为0，Redis账户模型准入键为空；未产生模型调用或队列任务。
- 加入虚构公开连接并指定writer默认后，六角色本地诊断均就绪；没有点击供应商探针或发送生成请求，因此没有真实供应商认证/连通性验收。
- 桌面及390px移动截图已目视检查，两会话脚本错误为空。预算详情隐藏/展开及暂停、投递不确定恢复由交互回归覆盖；worker入队后失效由真实隔离DB/Redis回归覆盖。

截图位于 `/private/tmp/myink-admin-advanced-collapsed.png`、`myink-admin-advanced-mobile.png`、`myink-admin-readiness.png`、`myink-admin-unavailable.png`。

## 自主决定与取舍

1. 依据用户“不再提问、自主提交推送”授权跳过方案确认停顿；方案及提交可追溯，方向改变时成本为修改开发分支。
2. 保留主动展开的历史任务详情和必要预算恢复操作，隐藏默认技术详情；若需进一步隐藏，需追加界面调整。
3. 保留摘要、复盘、全局审计既有非阻塞降级，未发现新增付费绕过；改变它涉及独立流程行为变更。
4. 就绪检查保持本地静态范围，保存/主动探针保留原地址守卫；扩大范围需要额外检查及相应联网授权，静态就绪不保证供应商持续可用。
5. 无模型调用的手动建书继续可用；如要全部禁用，需另行收紧准入策略。

## 交付与隔离

只提交并推送管理员分支，不合并main、不部署、不接触生产数据。原始main保持已有状态，无关`.DS_Store`保留；Pi由其独立会话维护。本轮临时浏览器与测试服务在验收后清理，用户要求的管理员worktree保留。

HTTPS远端检查曾发生连接失败，已有SSH认证正常；最终推送与远端SHA核对使用同一GitHub仓库的SSH连接，不修改全局或仓库remote配置。Myink Hindsight库记录产品决定、阶段及最终交付；不记录密码、密钥或token。
