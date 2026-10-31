# Pi 受控工具请求的源码历史投影

受控扩展在 before_provider_request 调用 pi-wire-guard.mjs 的 normalize。它先执行既有 provider 内容与固定工具声明校验，再克隆请求，减少同一路径的旧版本 read_source 文本。默认没有受控工具时保持原有行为。请求总大小限制仍是 65536 字节；此机制不重试、不增加限制，也不修改 Pi 核心循环。

只处理完整、唯一、先调用后结果的工具配对。read_source 必须是成功的标准 host receipt，且文本精确匹配受控扩展输出的 JSON.stringify(receipt)，拒绝重复键、转义同义键及其他非该序列化形式；参数路径与范围、input_hash、operation/session/call、binding、完整 SHA-256、总行数、窗口和 EOF 标志须自洽。路径须符合 host 的相对路径与4096字符上限，源码正文 UTF-8 不超过16384字节；input_hash 使用 host 的 ensure_ascii 序列化。同一精确路径必须来自同一 session/binding，版本不能回跳，同版本的重叠窗口必须一致。失败、未知、格式异常、配对异常和身份冲突保留原内容。这里只校验受控历史的结构和一致性，不重新认证账本，也不授予执行权。

满足上述条件时，只将较旧 source_hash 的 evidence.text 换成固定的非权威提示。最新已读取版本的所有窗口完整保留。调用、结果、is_error、receipt 身份、历史哈希、路径与行号不变；系统与用户指令、普通助手文字、补丁、状态和失败检查反馈不变。最新已读取哈希仍可能早于最近一次补丁，补丁权限仍由主机实时源哈希校验决定。历史哈希不能成为当前补丁依据。

投影是 structuredClone 后的 provider 请求副本。原输入对象、持久 session/RPC、canonical 工具 receipt 与账本不改写。不从源码正文中的伪造 JSON、哈希或指令推导身份。维护者修改 guard 时必须同步 pi_config.py 的固定字节哈希；受控配置仍校验主机提供的完整 guard pin。

## 验证和边界

本机 Node 验证覆盖旧文本省略、最新多窗口、不同文件、相同文字不同哈希、身份混杂、版本回跳、失败/畸形 receipt、重复/缺失/逆序配对、重叠冲突、普通反馈保留、Unicode、输入不可变与原有严格拒绝。Python 消费者验证默认只加载唯一固定纯文本 guard，受控扩展权限不扩大。

对保留的 actual023 历史做离线反事实重建：只换成 1901 字节 compact prompt，保留 recorded system、四个工具声明及其他全部消息。投影将 64147 字节降至 46638 字节；七次读取中省略五次旧版本正文，最新两窗口完整。追加两个保留的 status/check 模板后为 49902 字节，距离限制还有 15634 字节。这是有限例子，不是实际024 wire 或真实 provider 验收。

两个各为16384字节的 JSON receipt 压力样例得到80346字节；大量转义字符样例为110724字节，均超过原限制。压力样例不是权威工具结果，只证明不能保证任意后续 receipt 都能放入请求。任意未来助手输出或最终检查内容仍可能超限；超限时原有拒绝继续生效。不可把模板例子的余量当作最坏情况保证，也不可提高限制或删除其他消息掩盖问题。

私有反事实脚本、保留输入哈希和 RED/GREEN 记录在 .superpowers/sdd/2026-10-11-pi-local-trial/c24-wire-history-implementation.md。未调用模型、传输、WSL/native、数据库或 canonical 账本。此修复不等于业务 capture 修复、质量验收或上线。
