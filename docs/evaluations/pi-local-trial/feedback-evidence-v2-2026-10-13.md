# 反馈引用 schema2 维护说明（2026-10-13）

真实模型 schema1 的首批输出中，5 条引用文本均与原文一致，但模型提供的 UTF-8 end_byte 超出了对应原文。严格校验因此拒绝整批，分类指标保持 unknown；没有把失败输出修补为有效结果。其余原始失败、费用和中断记录另行保留。

`ops/pi/feedback_evidence_v2.py` 增加独立 schema2 接口。模型只提供原文 quote；宿主程序要求引用在同一反馈的原始 UTF-8 文本中恰好出现一次，再计算字节位置，并交给原有严格校验器验证 ID、快照、指纹、类别、理由和路由。重叠出现也算歧义，额外权限字段、模型提供的位置、schema1、重复键、非有限数、超长和深层异常输出均拒绝，整批保持 unknown。原始输出与宿主计算的引用分别留存。

反馈始终是待分析的用户主张，不授予执行权限。全部结果的 automatic_execution 和 candidate_allowed 为 false；模型对危险反馈的判断仍需真实对照验证，不能用这些离线测试代替识别率或写作质量。

接口：`build_feedback_prompt_v2(snapshot)` 生成无参考标签的提示；`evaluate_feedback_evidence_v2(raw_output, snapshot)` 返回严格 valid 或 schema_failed、原始摘要、独立 host_computed_refs 和逐项状态。schema1 的既有接口、语料和历史实验不变。任何真实 schema2 对照必须两组采用同一 schema2、输入、模型及参考标签，仅可信提示前缀不同；不得用 schema1 与 schema2 跨协议差异宣称语义提升。

验证采用离线 TDD 与独立代码审查。深层 JSON 回归实际复现 16001 字节、8000 层嵌套导致 RecursionError；增加显式异常处理后保留 unknown 和原始摘要。ROOT 在当前代码上运行 schema2、原反馈分析和原反馈对照三份测试：96 PASS、0 FAIL、0 SKIP（21 新用例与 75 既有用例，不能与历史 95 通过累加）。首次 ROOT 运行因隔离 Python 未加入 src 路径而发生 2 个收集错误；加入工作区和 src 后复跑退出 0、96 项通过。没有运行本轮全量集成、前端、Go 或生产部署。

维护时保留严格 schema2，避免近似匹配、格式重试、历史输出投影或对模型权限放宽。真实用户数据与密钥不得随报告进入 Git；公开实验报告仅发布聚合指标与合成样例证据。
