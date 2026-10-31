# Pi Linux 容器内合成运行接入

使用 writing-plans、executing-plans 内联、TDD、最终独立审查；用户已授权自主实现、提交推送及myink记忆，不再提问。起点7bbf182，沿用Pi worktree与长期分支，不合并main或部署。

目标：固定Linux ARM64 Node24.22.0（官方SHA256）与现有锁文件Pi1.1.0，在已验收容器限制内运行真实Pi，baseline/candidate两槽通过原合同、持久槽位和预算网关。其余28槽NOT_RUN。无真实模型、真实账本、质量结论或生产自治许可。

方案选择：与网络桥接、挂载宿主socket相比，采用network=none和固定stdio消息中继。容器内Python只监听127.0.0.1，收到模型HTTP后发送有界消息到可信宿主；宿主只转发到当前槽位固定loopback网关，不接受客户端URL。宿主持有独立合成Ledger/AnalysisRun/逐槽token/预算/期限，内置MockTransport产生固定SSE；请求仍须完整合同核验、原子预留与结算。Pi在容器内通过原PiAdapter运行，固定system/cwd、无工具、新会话，执行结果由宿主重新评分；完整公开30槽状态及计数。可信中继不是任意工具或付费grant。

获取依赖与执行分离：下载官方固定Node包校验SHA；复制现有package.json/lock到全新私有目录，在专用受限联网安装容器npm ci --ignore-scripts --engine-strict --audit=false，不改原runtime/共享daemon。执行容器readonly、none网络、65534、capdropALL、nnp、384MiB/0swap/.5CPU/64pids、有限tmpfs。只读挂载固定代码快照及Linux运行时，无业务源码/私有账本/凭据/socket。未知创建按精确身份恢复，清理失败blocked。超时/溢出停止整个所属命名空间。

## Tasks

1. 准备固定Linux runtime，记录Node压缩包/二进制、lock、Pi入口和依赖树指纹及版本；安装失败保留证据，不用Mac native包冒充Linux。
2. RED→GREEN新增container_runtime与固定worker：中继严格帧、路由/方法/长度/重复header、EOF/超时、输出上限、精确归属与清理、源/运行时只读、令牌绑定、预算拒绝、宿主重评分，禁止重放/跨槽。最小复用ProbeHost归属控制，不扩大原付费API。
3. 真实Linux Pi两槽合成验收及负例（错误token/正文漂移/重放/预算不足）；完整offline ops、compileall、diff；独立审查覆盖未被单测证明的边界。失败分母和原始证据保留。
4. 更新README、公开无正文回执/验收记录；仅Pi提交推送核对SHA；写入并核验myink记忆。

## Review Focus

- stdio来自不可信容器，必须有界、严格模式、固定唯一当前槽与固定host endpoint；拒绝任意URL/命令/文件读取、重复/迟到/多请求，不能透传provider凭据。
- Pi结果不能只信worker passed；宿主重评分、账本计数/已知settlement和session/退出证据，假回执不能形成付费许可。
- daemon/ID/image/name/label不匹配不得kill/rm；迟到create/attach失败/取消清理保留unresolved身份。
- 依赖安装有网络仅限专用获取容器；实际Pi必须network=none，readonly runtime与代码，写入只在tmpfs。
- shared daemon控制仍有开销，不宣称独立硬实时watchdog或生产容量；本地mock账本与真账本完全分离。

## Success contract

实际Pi1.1.0/Node24.22.0于Linux ARM64执行；两槽各一HTTP/一已知计费模拟attempt、合同有效、新会话、无工具、进程退出并清理；30槽分母保留。paid_requests=0、production_ready=false、automatic_execution=false，不能生成accepted_envelope。尚未验收内容明确列出。
