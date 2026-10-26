# 续期编辑状态修复验证 — 2026-10-26

范围：AccountPage.vue、EnvironmentPage.vue及对应回归/浏览器测试。保留所有既有未提交迁移改动，无提交、推送、合并或发布。

## 根因与修复

- AccountPage把token更新当作身份切换，clearSecrets并清掉busy/MFA。改为账号owner、服务端确认的管理员权限和登录状态的标量多源watch；这些安全边界变化时同步清理，普通token续期不清表单。
- MFA服务器状态由独立token watcher刷新，不覆盖正在配对的secret/code。已发送的MFA请求按owner+代次归属处理，同owner轮换可接收成功响应；后续请求使用当前token。存储事件尚未送达时，也拒绝属于其他账号或已撤销/未确认管理员权限的存储状态。
- EnvironmentPage的单getter每次返回新数组，session对象轮换也触发load覆盖draft。改成真正的status/userId多source watcher；续期保留未提交偏好和进行中的保存，换账号/退出同步失效旧请求。

## 测试先行证据

原两个审查用例重现RED；补充MFA配对/验证码、当前token、进行中enroll、防重复提交、撤权/换账号/logout隔离、环境保存跨续期后，初跑7项为5失败2通过。修复后7/7通过。

再增加“存储角色已撤销、UI事件未到”的回归，实际7通过1失败；补充stored role/roleVerified检查后8/8通过。

相关AccountPage/EnvironmentPage/session.account加8项新回归，4文件29项通过；独立复审已实际重跑同4文件29项通过，规格与质量批准，见renewal-fix-review.md。

## 完整门禁

最终实际执行结果：

- `npm run test:vue`：73文件、541项通过，无skip。
- `npm run lint:vue`：exit0，7项既有warning，无error。
- `npm run build:vue`：严格类型检查及构建exit0；产物index-DgQ77hkA.js，保留既有大chunk提示。
- `npm run test:browser:vue`：27项通过，新增账号/环境编辑跨同owner revalidation；receipt `/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-vue-browser-fqKe9C/receipt.json`。
- 原工作台浏览器脚本对新dist-vue：10项通过，receipt `/tmp/myink-vue-renewal-browser-20261026/receipt.json`。
- 独立复审：4文件29项通过，无skip，已批准。

两个P2与相邻权限回包条件均已关闭。原React和后端生产文件未改，不把上一轮真实隔离服务回执声称为本次新构建的真实服务重跑。
