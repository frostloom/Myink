# Pi任务包预检与源码定位实现计划

> **For agentic workers:** Use executing-plans inline; final requesting-code-review.

**Goal:** 在第一次付费选题前识别无效任务包，开发初始提示自动提供准确函数位置，减少宿主手工定位和无关全文件读取。
**Architecture:** 复用development_inputs完整静态验证，新增只跳过独立审查文件的template入口，不能作为开发执行许可；FrozenDevelopmentAdapter检查全部catalog模板，handoff在持久analysis claim内部先预检再调用分析，ACTUAL缺预检则阻断，终态重读仍不执行回调。新增只读AST函数索引，启动器写入证据并附于初始提示。
**Tech Stack:** Python3.12 / pathlib / ast / SQLite；现有Linux隔离Pi保持。

用户已要求自主推进常规决策。本轮控制器实现与离线／MOCK验收，不发起新的付费调用，不更改产品、原政策预算、64KiB边界、审查协议、Git或服务器。复用现有Pi工作树，保护已有脏文件。

- [x] Task1：RED覆盖0644输入、缺模板、漂移、整个catalog检查、独立review仍不可缺；提取prepare_template共享验证；FrozenDevelopmentAdapter.preflight接入analysis之前并保留绑定、取消／期限和不重复执行。验证全部development_inputs/maintenance相关测试。
- [x] Task2：RED覆盖decorator/async/嵌套符号、精确file hash、仅允许文件、恶意源码不执行、语法错误／非Python／超大文件明确不可索引、索引有界且标明遗漏、优先Plan目标名；自动注入开发提示和保存source-index-private.json，保留能力范围与阶段认证。验证源码索引及启动器集成。
- [x] 独立最终静态审查，修复阻断；运行完整Pi离线和既有Node边界，验证冻结runtime和LinuxMOCK开发整链（明确不冒充真实付费）。
- [x] 核对原账本逻辑摘要与政策关闭／凭据摘要不变、原产品源码和无关脏文件保持，保存验收报告/readiness和Myink记忆。不提交推送合并部署。

## 技术取舍

预检放在analysis的持久claim内部：成功／阻断回执重读不会触发新的文件检查或模型调用；SIMULATED自定义回调保留兼容，ACTUAL缺可信预检方法阻断。准备开发时仍重新检查并取得独立精确审查。索引只含文件路径／SHA／行数／函数名与行范围，不执行源码、不附带正文；最长8192ASCII字节，优先Plan.behavior提到的函数，明确omitted_symbols。超过1MiB或非Python／语法错误文件保留元数据并注明不可解析，不阻止修复其本身。位置只对初始冻结快照有效，补丁后仍使用read_source和最新hash。

独立审查P2已复现：索引compact预算8152，但提示默认带空格为8819；将实际prompt统一compact序列化，新增密集函数用例检查真正发送提示中的索引片段≤8192。预算约束prompt内索引JSON的ASCII片段；私有缩进证据文件可更大，外层SDK编码仍由原64KiB网关限制。修复时一并移除本轮引入的重复Receipt导入。

验收完成：见 `docs/evaluations/pi-preflight-locator-2026-10-25.md`。记忆服务写入若超时，仅标记结果未知，报告与本地证据为准。
