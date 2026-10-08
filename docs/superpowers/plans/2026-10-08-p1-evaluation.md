# P1 Evaluation Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, task-by-task. 本轮不自动提交、推送，不使用子代理开发；按 requesting-code-review 技能进行一次只读审查。

**Goal:** 复用既有案例，交付统一审核评测、离线判分/复核/报告和首次 15 例真实模型基线。

**Architecture:** 独立 evaluation 包，不改变生产工作流；薄 CLI 调用同一 audit prompt。数据、执行状态、自动证据检查和人工复核分开。

**Tech Stack:** Python、Pydantic、现有 OpenAI SDK、pytest；JSON/JSONL/独立 HTML。

**Spec:** [评测设计](../../EVALUATION-DESIGN.md)

## Constraints and rulings

- 保留已有未提交改动；仅追加相关文件，不提交。
- 用户已批准 DeepSeek 15 例审核，最多 20 次请求、估算上限 5 元；单次 SDK 请求禁自动重试，调用前预留最大估算费用。
- 保留 40 例规范；样例迁移用 AST 读取已有常量，不执行旧评测脚本。
- 第一轮 A–D；E 复用本轮已授权执行的恢复证据并提供离线检查。F 对照、向量召回等需新实验范围，明确列后续，不混入这 15 个审核任务。
- 未经人类复核的模型判断是 provisional，不发布 confirmed 指标。不得虚构复核人。

## Review focus

- 伪造引文或错误章号不得成为匹配候选。
- rewrite 的无关 finding、重复 finding 和额外误报必须显式处理。
- 非法 JSON 是 completed 输出失败；请求失败、预算中止不进入条件质量分母但进入整体运行分母。
- 新 run 不覆盖；离线 score 不调用 API；review 必须绑定原始结果哈希。
- 密钥不得进产物；未知价格不得用 0 宣称免费；重试不得绕过调用上限。

## Tasks

- [x] 1. `tests/test_evaluation.py` 先写格式、证据、复核、状态统计、预算和产物保护失败用例；运行确认失败。
- [x] 2. `src/myink/evaluation/cases.py` 实现严格格式、来源/指针/分组校验；`evals/` 保存 15 例、40 例 catalog 和配置。
- [x] 3. `scoring.py` 实现 `score_case(case, result, review=None)`；`reporting.py` 实现离线聚合与 HTML，正式和暂定指标分离。
- [x] 4. `runner.py` 实现无 live 无请求、单次请求预算、逐条保存、manifest；`scripts/evaluate.py` 实现 validate/plan/run/score/report。
- [x] 5. 跑离线测试、15 例真实基线、静态 HTML/链接检查（浏览器 file 协议受限，未作视觉验证）；保留原始输出与失败，检查无密钥。
- [x] 6. `evals/README.md` 写可用命令、复核及维护；更新设计实施状态、路线图和验收记录。

Verification: 聚焦 pytest，无业务服务；真实模型实验使用固定文本，无作品数据库。新增 CI 只运行无 API 的格式/离线检查。真实模型结果不混入 P0 的 97 项回归数字。
