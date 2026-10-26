# Main默认Vue修复与最终复核（2026-10-26）

最新状态：发布安全P2已修复并完成新产物验收；见[safe-update-fixes.md](safe-update-fixes.md)。下文保留对应历史阶段事实。

当前更新：再次复审发现发布安全需求遗漏，两项P2待修复；详见[再次复审](recheck-release-safety.md)。下文为此前已执行结果，不能据此放行发布。

结论：两项原P2已关闭，本迁移分支已默认Vue，技术验收可进入授权后的提交/合入准备；未提交、推送、合并或部署。原main-integration-review.md保留历史发现，本报告更新当前状态。

## 修复与验证

- 资产提取helper创建前登记清理责任。fakeDocker部分创建失败先RED后GREEN；成功、确认不存在、真实清理失败共4项通过，独立复核另跑4/4。未以真实Docker故障破坏环境。
- 默认dev/build/preview选择原生Vue，默认lint/test覆盖共享TS和Vue；显式*:react保留原生React。Docker/Compose默认Vue。保留Vue dist-vue、React dist输出路径。
- 默认lint/build通过，共享30文件191测试与Vue76文件564测试通过；React lint/build通过、72文件599测试通过。根Vue项目类型检查通过。Vue7条、React12条既有lint警告保留。配置/资产合并Node5测试通过。
- Chromium156.0.8078.4、Firefox157.0、WebKit27.2，各28冒烟+10工作台+26readiness，9组全部通过，页面错误和未知请求门禁为零。覆盖390/768/1440、真实Markdown下载字节、视频持久化刷新后解码播放（WebKit MP4，其余WebM）、编辑/路由/SSE重连与去重。
- 默认镜像构建不传FRONTEND_VARIANT，实际Vue LHE；显式react镜像实际React BDxd。各7项运行门禁通过，旧Cvlt/LHE资产可取、cache/深链/API隔离通过，cleanupErrors=[]。当前无自有myink-image-smoke容器或网络残留。
- 应用JS仍为8ace8616b0dc484c661be17834853f6a81fc1c95f4179f185173f46a2f12f51a，与既有真实TLS业务11项所验字节一致。本轮未改业务Vue/shared运行时代码和SSE后端；既有Python1966passed/1skip/5xfail及真实链路证据沿用，明确没有本轮重跑后端。

## 实验与边界

WebKit临时隐私上下文的IndexedDB拒绝File/Blob写入；独立最小实验确认普通上下文可存储，矩阵统一使用独立普通临时profile。不声称隐私模式媒体持久化通过。测试PNG修正原无效CRC；完成态fixture发送实际终态、刷新前等待状态/网络结束，消除了React也存在的WebKit原生中断错误；未过滤pageerror，保留中途断线/游标/去重断言。失败的先前矩阵不计通过，最终回执位于main-cutover-evidence/browser-matrix。

## 独立最终复核

由独立fresh-context reviewer只读审查实际dirty/untracked源码，核对计划Review Focus、默认/回退入口、CI和9组实际回执，独立跑helper4/4。未发现Important/Critical；没有复跑重型浏览器或Docker，镜像结论来自主代理实际执行。

P3暂缓：browser-matrix.mjs子进程超时可能绕过临时profile的finally回收，留下仅含合成测试数据的目录。正常完成路径正确，本轮未超时。后续可由父进程管理profile生命周期；不影响产品运行。

## 发布前条件

当前仍为本地未提交工作树，main未改变。实际发布必须另获授权、固定提交和镜像身份，并同步含SSE补丁的API。Git忽略的旧assets不会自动进入干净checkout：必须按runbook从当时运行旧镜像重新捕获并复验保留窗口。现有8文件窗口仅代表本轮证据。没有schema或存储格式迁移，React回退继续使用修复API。

最新镜像：
- Vue myink-caddy:vue-main-default-20261026 / sha256:e0f4ed1caeadad7b8ef130265924193360cfda7fd443b9432863268dd9a7bf67
- React myink-caddy:react-main-rollback-20261026 / sha256:7a5ced55e3f1195af23f7faa93c0c19cef891c9d04dc978560f196a9523532c6
- API沿用myink-api:vue-sse-ready-final-20261026 / sha256:9b5fb658fd5b6c5fb4c36e7ed74e207bcd6d48364c29a23be1bfbc863cd32b9b

实际日志、嵌套回执和截图在main-cutover-evidence；build-provenance.json明确源码摘要算法与文件集，旧摘要保留build-provenance-pre-cutover.json。
