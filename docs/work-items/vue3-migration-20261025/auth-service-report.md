# Vue authentication service implementation report

2026-10-25，Task 1；工作分支 `codex/vue3-migration`。未提交、推送、合并或发布。

## 改动

- `web/vue/src/session.ts` 保留原有接口，新增导出的 `SessionScope` / `LoginResult`、只读 `notice`、密码登录、邀请注册、MFA交换。
- 使用既有真实API封装；密码、邀请码与MFA挑战不写入storage。身份采用服务器响应，认证/MFA晚回用generation和实际storage token双重防护。
- 提前5分钟续期，每60秒检查、前台可见时立即检查；网络失败保留已验证会话至硬到期，旧后端缺token/有效期时保持原会话。
- 同账号storage更新在后台验证，保留上一次服务器验证的角色与状态，不把缓存角色作为已验证权限。同账号token轮换不取消业务请求；换号、退出和dispose会取消该账号历代token的在途请求。
- 退出有5秒独立截止时间；即使fetch替身未响应AbortSignal也能本地清理并提供notice。旧退出晚回不清除新账号。
- 新增 `web/vue/src/session.auth.test.ts`；既有session测试未改动。

## TDD与命令结果

1. 首次写测试时使用了重复web路径，写入失败且Vitest提示无测试文件；已纠正路径，该次不计RED证据。
2. `npm run test:vue -- vue/src/session.auth.test.ts`：实际RED，12/12失败。缺少login/register/completeMfa、未续期、同账号storage进入checking、离线退出未清理、超时退出未完成。
3. 实现后 `npm run test:vue -- vue/src/session.test.ts vue/src/session.auth.test.ts`：20/20通过。
4. 增补异常续期挂起回归后定向运行：15通过、1失败；旧renewal abort后不settle导致新账号永远无法续期。清空被撤销的renewal引用后24/24通过。
5. 最终 `npm run test:vue -- vue/src/session.test.ts vue/src/session.auth.test.ts`：2文件、28/28通过。覆盖密码/MFA/邀请、无storage事件的认证/续期/退出晚回、旧token401、角色缓存篡改、轮换不中断请求、历代token取消、失败重试/硬到期/旧后端/visibility/dispose、退出离线和超时。
6. `npx eslint --config eslint.vue.config.mjs vue/src/session.ts vue/src/session.test.ts vue/src/session.auth.test.ts`：退出码0。
7. `npx oxlint vue/src/session.ts vue/src/session.test.ts vue/src/session.auth.test.ts`：退出码0。
8. `npm run typecheck:vue`：退出码0（运行两次均通过）。
9. `npm run lint:vue`：首次运行失败，错误来自并行UI开发中的 `LoginPage.vue`，5处input缺少自闭合；未修改其他代理文件，交主代理统一复验。

按分工未运行完整Vue/React suite、构建、浏览器或真实服务集成；主代理负责集成验证。未运行项不作为通过。Hindsight本机服务连接失败，按项目规则跳过。

## 独立审查前补充

主代理指出dispose退出deadline和异步catch/storage读取风险后，先补实际RED：dispose后仍有1个5秒timer；expiry tick的storage异常直接漏出；validation rejection catch里的storage异常导致start Promise拒绝。分别修复dispose清理logoutTimer、tick异常边界、validation/renewal rejection中的存储读取边界。timer测试最初断言把fake microtasks计入，改为advance(0)后验证实际1个deadline；expiry测试最初误解Vitest advance返回值，改为直接await（RED已明确是storage异常）。最终31/31定向通过，session ESLint/Oxlint与typecheck再次通过。其余完整检查仍交主代理统一完成。

## 独立审查 P2 修复：退出时存储不可用

独立审查复现logout finally中clearSession/removeItem异常会让Promise拒绝并卡在checking。新增getItem/removeItem × 正常响应/5秒超时4项测试，实际RED全部因Error('storage disabled')逃出而失败。退出catch不再读取storage；最终清理使用身份检查与存储操作的异常边界，异常时仅清理内存、终止旧请求、显示unavailable与存储错误，并明确提示无法确认浏览器凭据已清除；无法读取身份时绝不尝试删除未知storage。另补其他标签已写入账号b、此时getItem不可用的回归，确认内存清空且b仍完整保留。

最终 `npm run test:vue -- vue/src/session.test.ts vue/src/session.auth.test.ts`：2文件36/36通过。session ESLint、Oxlint、`npm run typecheck:vue`再次退出码0。既有正常/失败退出晚回新账号回归仍通过。完整suite/build/browser仍由主代理执行。完成后停止写session文件。

## 最终整合审查 P2 修复：401清理异常

新增缓存校验返回401且Storage.removeItem抛错的测试，实际RED：start Promise拒绝，栈位于revalidate的401 clearSession。新增局部failClosedStorage用于onUnauthorized、401分支与logout存储清理失败：invalidate阻断随后晚回，清内存/旧请求，设unavailable和明确存储error/无法确认凭据删除notice。保留身份检查，不盲删未知账号。另加旧校验401期间storage已切到b的回归，确认b存储未删除。

最终命令：session定向38/38通过；`npm run test:vue`完整6文件100/100通过；`npm run lint:vue`通过；`npm run typecheck:vue`通过。以上均为本次实际运行退出码0。构建与浏览器由主代理负责，本文未声称已运行。完成后停止写文件。
