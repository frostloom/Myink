# 第二轮继续评审 — 2026-10-26

范围为当前未提交Vue迁移工作树，对照基线a96066c43b41e535da4b73e260a998ba9350c415及brief；无生产改动、提交或共享服务操作。上一轮AccountPage/EnvironmentPage修复保持通过。

## 规范/质量轴：1项P2

session.ts229把所有generation变化都当作密码操作过期。同账号、同token仅重新校验会话，pending changePassword返回成功后也会早退，authenticated状态与密码字段留在页面，没有重新登录提示。后端auth.py491–515成功修改密码会递增auth_version撤销已有凭据。同token校验情景是Vue新增generation guard回归；同owner token轮换情景旧React也有，只作同一缺陷的补充证据。应保持跨账号/真正新登录保护；不能把修复简化为盲目清掉任何后来有效的新凭证。

实际复现：web/vue/src/review-second-session.test.ts，两项expected anonymous实际authenticated；原session.account3项通过。独立规范审查已核对并复跑，见review-second-standards-20261026.md。

## 功能规格轴：1项P2

WorkspacePage.vue285–287初始全项目任务历史查询只核对projectId，未核对taskStartVersion；309–314能将活动任务换成迟到历史结果。同一作品已启动新任务时，历史快照迟到仍会夺走任务上下文。违反brief107“切任务旧回包无效”；旧React也有该漏洞，应标记为本轮明确契约尚未实现的继承问题，而非最近续期修复引入。

实际复现：web/vue/src/pages/review-second-spec-history.test.ts。主代理补强为已有12个confirmed章，历史快照采于旧第13章尝试仍running时、网络迟到，新第13章任务已发起后才返回；不要求两个真实任务同时运行。回包后active task从task-13变task-old，因选中旧optimistic id不存在，时间线显示chapter-none，正文中心回到选章空态。最后保留新task-13的断言实际失败。原先空列表/旧第3章测试同样RED，但最终证据采用上述更自然的重试场景。见review-second-spec-20261026.md。

## 主代理验证

实际重跑review-second-session、pages/review-second-spec-history、session.account及review-audit-standards-account共4文件：**3项失败、11项通过，无skip，exit1**。3失败对应上述2个独立缺陷。规范轴此前资源/后台7文件71项通过，无新增确定资源问题。不把未形成自然产品入口的state-only导航猜测列为缺陷，相关人工断言未保留。

本轮只新增/补强复现测试与报告。两个发现均OPEN，未修改生产、旧测试或通过放宽断言隐藏失败；此前541GREEN是上一轮历史记录，不代表当前含新用例的测试套件通过。未重跑完整构建、浏览器或后端集成。
