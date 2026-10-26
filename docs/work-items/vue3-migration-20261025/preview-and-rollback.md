# 候选构建、同源兼容与回退准备

本轮只交付独立候选，没有提交、推送、合并或发布。`web/dist`为React，`web/dist-vue`为Vue。本迁移分支的Caddy/Compose默认构建Vue，React必须显式选择。

## 本地预览

在`web`执行`npm run dev`（`dev:vue`仍可用），固定5174端口。该入口默认代理到localhost:80，**端口不隔离后端数据**。自动浏览器验证用loopback fixture或独立临时API，不使用生产账号和作品做破坏性测试。

## 构建身份

运行`npm run build:vue`包含严格类型检查；Vite实际chunk module检查禁止React/旧TSX进入候选。入口保持`/assets/index-<hash>.js`，HTML主题首屏初始化保持。未提交工作区的HEAD只能代表基线，不能假装是最终实现身份；验收报告记录当次JS/CSS哈希及源文件内容摘要。正式发布前应在授权提交后重新构建并记录commit、lockfile和产物摘要。

## 同源数据与旧客户端

新旧共用原`src/lib`API与存储协议，不批量清空localStorage/sessionStorage/IndexedDB。账号、主题、背景、建书草稿、活动任务和章节草稿继续使用原键。5173/5174端口的存储隔离不能证明线上同源兼容；正式切换前需把独立验收域名依次指向新旧产物，演练已有会话、草稿、主题背景及活动任务的往返恢复。

Vue版本探针只提示更新，不自动刷新编辑器；手动刷新仍经过原生beforeunload。部署时必须保留旧hash资产至旧客户端窗口结束，HTML使用重新验证策略，hash资产使用不可变缓存。不要用删除旧assets强迫旧客户端切换。

## 发布与回退门槛

获得发布授权后才进行：固定新旧镜像/产物身份→备份部署配置→隔离域名根与深链→登录/MFA/跨账号→长短篇创建与资源优先→计划/流式/审核/恢复→草稿409→媒体/移动端→旧客户端刷新提示→同源新旧双向恢复→切换入口。回退只恢复已核实的旧镜像/资产与HTML指向，不改数据库schema、不清浏览器草稿、不把当前未提交工作区当成回退版本。

本报告早期范围已由readiness-real-chain.md扩展到实际模型HTTP替身/队列/worker/DB/SSE及本地可信CA TLS。生产DNS、公网签证、长期在线窗口与真实手机硬件仍不在已执行范围内。最终以readiness报告中的逐项状态为准。

## 可复现的候选与回退镜像准备

以下为准备步骤；本轮不执行线上切换。先固定当前运行镜像ID和需支持的历史客户端版本，从其镜像只提取公开assets；不可只依赖“相同Git基线”，线上当前实际index-Cvlt329b.js已和本地React构建不同。

```sh
python3 scripts/prepare-frontend-assets.py --image <当前运行React镜像ID> --image <先前候选镜像ID>
docker build -f caddy/Dockerfile --build-arg FRONTEND_VARIANT=vue -t <Vue候选标签> .
python3 scripts/prepare-frontend-assets.py --image <Vue候选镜像ID>
docker build -f caddy/Dockerfile --build-arg FRONTEND_VARIANT=react -t <React回退标签> .
```

将候选Vue资产也加入React回退镜像，保证Vue旧页面在回退窗口仍可加载原hash。生成资源是公开构建输出，目录被Git忽略，来源与SHA应保存在交付回执；不能把空.gitkeep当作已准备旧资源。安全合并门禁会拒绝同名不同内容及符号链接，构建失败时应调查原因。未来每次切换都要重新读取实际运行镜像并更新资源窗口，不能认为本次6个文件覆盖所有未来版本。

镜像与Compose默认Vue；回退必须显式FRONTEND_VARIANT=react。正式发布需要授权后固定提交、产物/镜像ID、部署配置和回滚镜像，不直接覆盖local标签作为唯一退路。回退保持同域名/API/schema/浏览器存储，仅恢复已验证React入口和保留的公开assets。

## 本轮SSE后端补丁的发布依赖

真实重连验收发现原后端在终态后的observer summarize/metrics尾帧导致重放漏掉终态、连接挂起，属于已有共享后端缺陷。候选一并修复src/myink/api/routes_sse.py；实际上线需使用含该修复的API版本，不能把新前端指向旧SSE实现后声称所有重连边界已覆盖。没有schema/存储格式更改，React回退仍兼容修复后的API；回退前端时无需回退该修复或清理作品数据。新API镜像及新后端实际重连回执需列入最终provenance。

## 已准备并实际验收的本地镜像

这些是本轮未提交候选的本地标签；没有推送到registry、没有替换运行服务。镜像ID与全部构建/运行回执见build-provenance.json。正式发布按授权固定提交与registry身份后执行。

| 用途 | 本地镜像 | 已验证行为 |
| --- | --- | --- |
| Vue候选 | myink-caddy:vue-ready-final-20261026 | LHE原生Vue＋历史Cvlt/BDxd/Cyxw/Ddk资产窗口 |
| React回退 | myink-caddy:react-ready-final-20261026 | BDxd原生React＋LHE Vue资产窗口 |
| 同步API补丁 | myink-api:vue-sse-ready-final-20261026 | SSE终态尾帧修复、25核心版本一致、113路径契约与healthz通过 |

两前端镜像目前包含完全相同的8个JS/CSS文件，只有入口/运行时选择不同；因此回退选上表React镜像并继续用已修API。模板不会替你猜未来线上旧版本，每次发布前仍需要重新捕获当时应保留的旧资产。

可复现镜像门禁：在web用`node scripts/frontend-image-smoke.mjs --image <前端镜像> --expected vue|react --required-asset /assets/<应保留入口>.js`；在跑过pytest的同Python环境从根目录用`python scripts/api-image-smoke.py --image <API镜像> --output <回执JSON>`。自动测试仅运行自建临时容器，清理失败会使门禁失败；不调用实际生产数据库。


## 安全更新过渡顺序（本轮修复后）

这里只记录操作约束，本轮没有发布授权，也未部署。

1. 固定授权提交、API补丁和双向公开资产窗口。最新技术验收入口为safe-update-fixes.md与build-provenance.json；此前LHE镜像是历史证据，不是本轮新守卫的产物。
2. 实际发布先选择安全React过渡入口：显式FRONTEND_VARIANT=react（本轮已验myink-caddy:react-safe-update-20261026）。该入口只提示更新、用户确认后刷新，保存中禁切换。Vue构建默认入口不会自动替用户完成这一过渡。
3. 在获准的发布流程中通知并确认活跃用户保存/导出、关闭重开；已有旧React标签页不会自行获得新逻辑，存储失败的纯内存草稿无法由服务器补救。休眠/离线旧客户端仍有残余风险，等待30秒不能证明收敛；继续保留它们需要的旧资产。
4. 经明确切换授权再使用Vue默认镜像（本轮已验myink-caddy:vue-safe-update-20261026）；版本探针同时读取release.json与HTML并验证同一release，混合发布只保留当前页面、不自动刷新。Caddy实际无缓存版本响应已验。
5. 回退使用安全React入口及本轮Vue资源并集，继续使用修复后的API，不清库、不删除草稿、不重复提交任务。正式发布时须重新捕获当时实际运行镜像；本轮10文件窗口不能替代未来资产核对。
6. 完成约定至少一周的真实运行观察与长短篇/管理/断线/回退流程后另行决定清理。自动化合成矩阵不冒充线上观察期。
