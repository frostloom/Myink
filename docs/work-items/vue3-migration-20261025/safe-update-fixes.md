# 发布安全修复验收（2026-10-26）

结论：再次复审的两项发布安全P2已关闭；三个专项独立评审及最终fresh-context复核均无Important/Critical。本地技术门禁通过，可进入授权后的提交/合入准备。没有提交、推送、合并、部署或替代现有服务；Pi未处理。

## 修复

1. React与Vue均只提示版本更新，不自动reload。用户确认前明确提醒章节、建书/短篇、管理员表单、反馈附件、主题预览和存储失败时复制/导出；取消保留当前页面。
2. 共享API的POST/PUT/PATCH/DELETE用计数器保护，包括认证、后台修改、FormData上传，直到响应解析完成；并发写入、失败、中止都正确释放。写入期间更新按钮禁用，确认后再次检查锁；原生beforeunload提醒保存中离开。GET与SSE不被当作写入。
3. Vue轻量表单scope覆盖全部实际内存变更表单，检查响应式数据而非DOM事件，因此点击新增、结构化数组和程序修改也受保护。路由更新、同组件query/params变化、关闭/刷新、保存失败与账号恢复均有回归。嵌套表单统一一次确认；保留章节备份失败、主题与反馈附件保护。成功保存后的预期跳转显式放行。清单见web/vue/src/composables/MEMORY_FORMS.md。
4. 两套Vite产物均生成内容绑定的release.json及相同HTML meta；探针核对schema/client/id/entry与实际module script，混合发布不提示切换。开发页没有生产身份时不探针。旧客户端兼容入口明确固定assets/index-[hash].js，构建插件拒绝不兼容命名。版本JSON/HTML无缓存，hashed assets仍immutable。

## 实际验证

| 门禁 | 本轮结果 |
| --- | --- |
| 保存锁回归 | 4项先3RED/1GREEN，再全GREEN；含响应解析、并发失败、abort、只读 |
| 更新与构建回归 | Vue/React守卫行为先RED后GREEN；release/plugin8GREEN，包含真实临时Vite构建及不兼容入口RED→GREEN |
| 表单专项 | 13文件179GREEN；核心离开保护、短篇未发送内容提交、手动登录路由均曾RED后修复 |
| 默认完整测试 | 共享34文件205passed；Vue78文件576passed，无stderr异常或跳过 |
| React完整回退 | 76文件613passed，无跳过；共享测试重复运行不累计独立覆盖 |
| lint/types/build | 默认Vue和React均exit0；Vue9条warning（含2条测试多组件warning），React12条既有warning；大chunk提示保留 |
| 三个真实引擎 | Chromium156.0.8078.4、Firefox157.0、WebKit27.2，各28冒烟+10工作台+26readiness+10发布安全，全12组GREEN |
| 新发布安全浏览器 | 实际Vue↔React产物：混合manifest/HTML拒绝提示、不自动刷新、取消保留输入、延迟API期间禁切换/关闭提醒、失败后解锁、确认后切到实际另一运行时 |
| Caddy镜像 | 默认Vue及显式React各10项GREEN，版本配对/no-store、深链/API隔离、原生runtime、3个旧资产哈希实取；entry字节与本地浏览器所验一致 |
| helper/Node门禁 | 4项清理故障回归、5项实际配置/安全合并全GREEN；diff --check通过 |
| 清理 | 两镜像cleanupErrors=[]；自有容器与网络剩余0 |

旧长文、下载字节、真实PNG与WebM/MP4刷新持久化/解码、390/768/1440导航、SSE断线游标/去重、409草稿保护等在新Vue产物上重新执行。临时普通profile彼此隔离，不声称隐私模式持久化通过。

首次完整Vue运行虽575passed但发现测试使用jsdom未实现的confirm，已针对预期放弃输入的用例明确接受并断言，修复未初始化router的测试夹具；最终576passed且无该输出，不隐藏console。首次Firefox发布测试在切换完成前读取上下文而失败，补等待新release/runtime真正挂载后，最终3引擎矩阵均通过；原失败不计GREEN。

## 最新身份与证据

- Vue：index-Bk-yDMAg.js，SHA256 c41dd3e9a0437f8de4c4bc9fdfd14a064cd69f1ba561970d67dad65ef203bfb7。
- React：index-BcR2NWy9.js，SHA256 367fa00ffc632a82b810e02c93025b76a16dd1a72efee92829440239c41befb6。
- 默认Vue镜像：myink-caddy:vue-safe-update-20261026 / sha256:86ef365e222c89bb05067f6c767dd08b5fc988f40d0ac43874be25b12977f1b8。
- 安全React镜像：myink-caddy:react-safe-update-20261026 / sha256:1a0f2232cf1ac9ca1c1c6bcac006bed9b7280720bd20a842014b07ababf27fb4。
- 版本身份、源码算法/文件集及所有产物SHA见build-provenance.json；修复前摘要保留build-provenance-pre-safe-update.json。所有新测试、截图、镜像及清理回执见safe-update-evidence。
- 旧公开资产窗口现在10个文件，保留原实际运行Cvlt、此前LHE及两套新产物，详见safe-update-retained-assets.json。实际发布仍须捕获当时运行旧镜像；Git忽略资产不自动进入干净checkout。

## 独立复核与边界

三个专项代码审查均通过；最终fresh-context审查核对26个表单文件SHA、12组浏览器回执、镜像运行证据和父代理新增QA工具，无新增阻断或minor。reviewer仅只读并运行diff --check，没有冒称重跑重型门禁。

本轮前端产物已改变，不能把此前LHE真实TLS11项声称为新Bk产物的实测。本轮重跑的是完整前端、3引擎受控API/SSE与实际Caddy镜像；未重启隔离API/worker/数据库或重复跑全后端。后端源码未变，原1966passed/1skip/5xfail与真实模型HTTP链路证据保留原身份；API仍需配套此前SSE修复镜像9b5fb658...，无schema/存储格式变化。

已知P3暂缓：预算恢复成功保留输入值，可能保守多提示一次“未保存”；浏览器矩阵被硬超时终止时可能遗留合成profile目录。两者均非数据丢失或本轮运行清理失败。

旧旧版React标签页不能自动获得安全守卫。正式发布必须先发安全React过渡版本并确认活跃用户保存/导出、关闭重开，然后经授权切Vue；30秒等待不是收敛证据。休眠标签页仍须保留旧资源。真实用户至少一周观察、硬件输入法和生产切换未执行。完整顺序见preview-and-rollback.md。
