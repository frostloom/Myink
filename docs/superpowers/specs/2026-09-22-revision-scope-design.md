# 局部修订设计

依据动手前的现状核对稿实施（该稿未随库保留，见 6849535）；Jev 不在范围内。
用户已授权连续执行并自主调整计划，不再逐阶段等待确认。遇到新增授权或破坏性风险，采用安全替代或暂缓。

## 目标与边界

局部问题只改命中片段，结构问题保留整章修订。任何模型均无写工具；落库仍由 persist 执行。
历史 finding 不回填、不删除；新 Finding/ORM 默认 scope=unknown，漏填保守按 full 处理。
独立 max_patches=2；结构修订 max_revisions 和 replan 原有优先级不变。
补丁用尽转 needs_review，不偷偷升级整章改写，不消耗整章修订预算。
只有存在明确 local 发现且所有阻塞发现均 local 才走 patch；空发现、unknown 或冲突标签走 full。
路由检查原始 report.findings、unresolved、audit findings 的并集，防语义层覆盖结构标记。
若规则 summary 表示有阻塞但缺少对应 finding，保守 full。

## 确定性应用

解析 PATCHES 区段内 TARGET_TEXT / REPLACEMENT_TEXT；拒绝完整 CONTENT/REVISED_CONTENT 输出。
所有定位基于原稿，不能先改前文再用修改产物定位后续补丁。精确唯一命中优先；歧义不得模糊解救。
空白归一化兜底仅用于至少 10 个非空白字符的目标，保留原文索引映射；拒绝重叠范围。
单条失败跳过，成功比例低于 50% 全部回退。空补丁、无变化均保留原稿。
防伪局部重写：单条 target/replacement 最多 600 字，总修改原稿范围不超过 30%；小稿至少允许 100 字。
拒绝信息与应用/跳过条数记入 agent_runs；不得把被拒补丁的 fixed 响应作为已修证据。

## 接线

新增 patch 图节点，仍使用 writer 角色，专用短输出提示词与 4096 token 上限。
patch → extract → validate → audit，重新生成候选及报告，不复用旧候选；这是主动选择原施工单 A。
独立计数保存在 ChapterState；replan 清理瞬态并重置补丁轮次，与既有重写计数一致。
流转面板显示“局部修订”“局部修订并复审”，不新增提示段落。
不改变人工 revise 入口、持久化确认规则、字数硬门禁、工具、长篇首次 write。

## 验收

纯函数精确/模糊/重复/重叠/阈值/超范围/全文拒绝；路由 local critical 不放行、unknown 保守、独立预算。
真实图补丁后重新抽取并复审，原稿未触及文本不变；provider 替身仅替代外部模型。
既有 test_independent_route_budgets 六例原样通过；全 Python、前端测试/lint/build、契约导出及 GitHub CI。
