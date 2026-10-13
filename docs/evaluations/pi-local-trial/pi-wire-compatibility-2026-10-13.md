# Pi 无工具请求兼容性维护说明（2026-10-13）

011 的首次反馈请求在本地网关返回 400，真实上游 HTTP 调用为 0，累计请求与费用没有增加。该案例已终止，失败、清理及历史账本证据保留。原始 011 入站请求体未留存，因此不能声称已直接观察到其具体 wire 字段，也不能把本地拒绝记作供应商失败。

已固定的 Pi 1.1.0 SDK 默认使用 short cache retention，会给用户或系统文本块加入 `cache_control`。项目网关只接受既定文本字段，因而拒绝该形状。`cacheWarming: 'off'` 仅关闭预热；环境变量 `PI_CACHE_RETENTION=none` 会回落到 short；当前 CLI/RPC 设置没有把显式 retention none 传入 SDK 的路径。零网络 SDK 探针以合成上下文捕获默认请求，复现严格校验拒绝；经原有 guard 投影后通过。这是 SDK MOCK 因果证据，不是实际 011 请求体、供应商响应或模型质量证据。

默认无工具配置现只显式加载 `ops/pi/lab/pi-wire-guard.mjs`，固定原始字节 SHA-256 为 `eea0ee73c584f41624cf12d88141a12e4cfcfb958269731873a2a942996177f7`。该默认入口只注册 `before_provider_request`：以空工具定义移除文本缓存元数据，并固定关闭 thinking；不注册工具，工具块及未知字段仍被拒绝。配置保留无工具、无内置工具和禁止扩展自动发现等参数，没有工具 broker 或 `PI_TOOL_` 授权。私有 producer 与 worker 独立核对唯一固定扩展路径及哈希，拒绝别名、重复扩展和篡改。原 controlled-tools 分支保持不变，网关校验没有放宽。

guard 的固定值绑定原有 3991 字节 CRLF 文件。ROOT 的实际 Git checkout 探针发现，旧 LF blob 在 `autocrlf=false` 下不能满足该 pin。ROOT 仅为 guard 添加 `.gitattributes` 的 `-text` 规则并保留原有字节；Git 批次 `0f9bde0`、`67e217d` 后，ROOT 核对 Git blob 为 3991 字节、上述 EEA 哈希，两种 autocrlf checkout 均一致。此修正只保留换行字节，没有改变 guard 逻辑。

有限离线 TDD 保存了公共缺少固定扩展的 RED 和私有旧规则拒绝固定扩展的 RED。最终公共测试 7 PASS、私有测试 34 PASS，均 0 FAIL、0 SKIP；私有测试包含原 27 个边界用例和 7 个 guard 用例。另有独立 SDK 零网络 MOCK，fetch 与供应商调用均为 0，验证原始拒绝、投影接受、文本及模型参数保留、未知字段和工具拒绝。这些检查不代表真实 Pi 隔离验收或真实模型对照；真实模型结果应由后续独立报告按物理证据给出。

维护 guard 时必须生成新版原始字节 pins，同步配置与私有边界绑定，并验证投影、拒绝路径及跨平台 checkout。不得用新文件、成功运行或新 pins 替换旧案例和旧证据。该说明仅记录兼容性修正，与当前 live gates 的验收独立。
