# Pi 草稿隔离基线 Implementation Plan

> **For agentic workers:** Use executing-plans inline and test-driven-development. 沿用用户自主推进、不逐项确认授权；不提交合并部署。

**Goal:** 将任务草稿接到既有隔离checker，自动生成真实失败库存与可选题目录，减少手工基线脚本。
**Architecture:** 新ops/pi/package_baseline.py复用task_package的静态验证/私有原子发布、development_launcher的固定checker/OwnedHosts，以及unit_feedback和maintenance_handoff的原严格验证。默认check只读；显式execute仅启动一个全新隔离checker，无模型、账本或审批操作。
**Spec:** 本文件固定接口及docs/pi/local-development-launcher.md既有隔离/选题协议。

## 固定接口

- check(request_path)、execute(request_path,cancel=None)，CLI --request ABS [--execute]。request600/parent700，严格schema pi-package-baseline-request-v1，恰有schema/baseline_id/draft_path/draft_sha256/root/docker/endpoint/daemon_id/checker_image_id/deadline_seconds。
- 明确本机unix Docker端点、daemon及immutable checker image，deadline整数1..300秒。默认预检不访问Docker/网络/模型、不写目录。root新700且不与request/draft/source/test、Docker可执行文件或解析后的本机Unix端点重叠。
- draft严格既有schema及字段，private600、parent700，来源路径必须指向同包source/test.py；固定源仅src，无链接/超限，gold600单链接≤1MiB。全树/gold摘要及AST hints与draft一致，静态hints只能作为期望库存，真实checker库存不符直接失败，不能丢弃继承/动态case。
- execute调用原_fixed_check，不在host执行源或gold。执行前后重验request/draft及源/gold，并验证实际check/src副本和gold字节，防止复制漂移。超时/cancel贯穿并收尾OwnedHosts，清理异常即使后续恢复也不能成功。
- 最后原子发布outcome.json，schema pi-package-baseline-outcome-v1。verified只表示完整、0error/skip且资源/输入已核验的基线；不表示unit通过。check_passed单列；eligible_for_selection仅真实失败>0、errors/skips0及精确库存时true；用原_catalog验证后才嵌入catalog列表。绿色基线verified但eligiblefalse；真实失败库存合法但目录超原60,000字节上限时保留verified基线、catalog=[]和catalog_rejection，不提高原限制。错误/跳过/库存不符/资源未知均不入目录。
- 结果不包含Plan、运行时、预算、审批或可执行开发配置。新付费执行仍要新run/cycle、当前runtime、独立审查。不重放已有root，不把新root当未知资源的自动重试；宿主先核对/清理。
- 发布复用已同步关闭后os.link排他提交；临时别名清理失败按原工具披露staging_retained，不伪报已提交结果失败。

## Task1 TDD API/CLI

- [x] 先写默认无副作用、严格输入、真实失败/绿色/错误库存分类、输入与checker副本漂移、取消超时、清理失败/复用拒绝等测试，观察缺失模块RED。
- [x] 实现新模块，不改原checker/审批/费用协议；相关回归通过。

## Task2 实例、最终审查与记录

- [x] 用新工具分别检查250项真实绿色草稿和小型真实失败草稿，隔离验证前者无目录、后者原_catalog接受；0模型调用/费用，拥有容器直接核实清理。
- [x] 完整Pi离线CI与4Node协议脚本，不重复无关产品/Go/前端。新增ops后旧runtime仍不可用，下次付费须重冻。
- [x] 一名独立最终审查者只审本轮范围，阻断以TDD修复并回归；维护文档、评估及输入保护。

Ruling: 先实现无付费基线接力，不自动造审批或根据JSON标记续跑。绿色和有错误的检查都不能伪装成真实失败目录，代价是问题描述/具体Plan与审查仍由可信宿主提供。

2026-10-27完成：44新/192相关/2618Pi+19未选/4Node；六类单独真实实例通过资格验证。独立P2及作者Unix路径守卫5RED→GREEN，旧并发137未完成记录保留。新用户授权后续阶段提交推送Pi分支，main/部署不在授权内。
