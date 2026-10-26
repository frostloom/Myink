# Pi 私有任务包草稿 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans inline. 用户已要求自主判断下一步、不逐项确认；保留未提交，不新建开发分支。

**Goal:** 把多轮真实开发中手工复制候选、冻结gold测试和提取case清单的重复步骤固化为仅生成私有草稿的仓库工具。
**Architecture:** 新ops/pi/task_package.py复用development_inputs的路径/JSON/完整树摘要规则。默认check只读；freeze在全新700目录复制source/src和test.py，校验输入与副本未漂移后，以已同步关闭的600临时文件排他原子发布task-draft.json。静态AST库存只是hint，不是baseline或权限。
**Tech Stack:** Python标准库、pytest；已有Pi启动器和隔离checker不改。
**Spec:** 本文件下述固定接口与边界是本轮小范围设计；沿用docs/pi/local-development-launcher.md现有执行/审批协议。

## 固定接口与边界

- check(request_path)和freeze(request_path)，CLI python -m ops.pi.task_package --request ABS [--freeze]。默认不写任何输出/账本，不启动Docker/模型，不import源或测试。
- request严格schema pi-task-package-v1，恰有schema/task_id/problem/source_path/source_sha256/test_path/test_sha256/files/root。绝对非链接路径；request/test600及父目录700；root不存在且parent700、与所有输入不重叠。source根恰含src，树原规则10000files/64MiB/拒绝链接特殊文件。test≤1MiB、普通单链接文件；hash64小写hex；task_id沿用有界目录身份；problem非空≤2000；files1..8唯一有效src内既有文件。
- AST仅提取顶层类中直接test_*方法的sorted fixed_development_tests.Class.method提示，1..1000、不重复；不能从静态提示宣称精确运行库存（继承/load_tests仍须真实checker判定）。语法/大小错误拒绝，不执行测试内容。
- freeze先排他mkdir新root700；source复制保留符号链接用于后续拒绝，不跟随输出链接；副本所有目录700/文件600，原source/test/request不变。前后重验输入及副本；只有完成后原子发布task-draft.json。发布前失败保留私有未完成目录，无草稿完成标记；发布后别名清理错误披露staging_retained=true，不伪报提交失败，不自动删除/覆盖或重试。
- draft schema pi-task-package-draft-v1，含新副本路径/摘要、task_id/problem/files、test_case_hints、inventory_status=static_unverified、requires=[fresh_isolated_baseline,fresh_run_identity,independent_reviews]和origin来源，不包含审批、费用、运行时或可执行配置。现有prepare_template必须直接拒绝该schema。
- 不读取/改写真实凭据或策略、不创建预算、不重放旧cycle，不自动选择候选、不宣称旧verified可复用；本轮不执行新付费请求，不改产品代码。

## Task1 — TDD实现草稿API/CLI

- [x] 写ops/pi/tests/test_task_package.py，先观察缺失模块导致的明确失败。
- [x] 实现最小新模块：检查无副作用、不执行源/gold；私有精确副本；sha/权限/链接/目录范围/库存异常；已有输出不覆盖；复制时漂移不出完成标记；CLI默认只读/显式冻结。
- [x] 跑定向测试及已有development_inputs/source_locator/template_preflight/adapters回归。

## Task2 — 实例验收、独立最终审查、文档

- [x] 用封存已审010源5ab3a...和250项固定gold，实测默认检查不写、显式冻结副本字节一致/静态250提示；普通产品不修改。用原隔离checker验证冻结gold及源250通过仅作为fresh check证明，不把绿色baseline包装为待修复目录。
- [x] 跑完整Pi离线CI标记检查与4Node脚本；不重复无关产品1905/Go/前端。新模块改变runtime闭包，下次真实执行必须重新冻结，不复用a7be旧批准。
- [x] 一名独立最终reviewer检查本轮模块/测试/说明与实际证明，修复阻断并验证；不委派实现。
- [x] 更新启动器说明/readiness与评估，核对原账本/策略/凭据/产品源和既有dirty文件不变，保留所有新改动未提交。

Ruling: 输出定义为草稿而不是自动续跑授权，因为历史unit失败常无成功phase认证，不能把结果JSON里的verified/failed库存当新的可信审批。代价是之后仍需现有隔离基线和独立审查，但复制与静态清单可自动化。

完成：50新测试/106定向/2574Pi+19未选/4Node，当前模块真实250副本fresh隔离检查通过。唯一独立P2以4项RED→GREEN关闭，原审查拒绝记录保留。产品和原账本未变，0新模型费用，未提交发布。
