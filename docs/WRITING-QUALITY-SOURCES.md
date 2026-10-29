# 写作质量：资源链路、来源选择与通用文风

2026-10-29，用户要求先发布已验收界面，然后核对题材、规则、文风是否参与写作，并从 GitHub 寻找合适表达/创作规则。用户选择“自然表达与网文推进兼顾，按题材调整”。

## 推荐选择

| 来源及锁定版本 | 推荐用途 | 取舍 |
| --- | --- | --- |
| [Chinese Novel Writing Skills：对白](https://github.com/aa15107688191-collab/chinese-novel-writing-skills/blob/fc8be3aaf022f123ee190acd51b7fe4642b06d15/skills/dialogue/SKILL.md)、[正文与场景](https://github.com/aa15107688191-collab/chinese-novel-writing-skills/blob/fc8be3aaf022f123ee190acd51b7fe4642b06d15/skills/fanqie-webnovel-prose/SKILL.md) | 本轮主要参考：人物诉求、潜台词、声音差异，行动与后果的关联 | 不采用上游工作流，不执行其 Skills；不把“前若干字必冲突”、对白功能比例等变成统一门禁 |
| [chinese-webnovel-skills：连续性](https://github.com/tance-mang/chinese-webnovel-skills/blob/ecf552f6930e769d8bbf17818ad3d5a864a7a70b/references/continuity-check.md)、[现实短篇](https://github.com/tance-mang/chinese-webnovel-skills/blob/ecf552f6930e769d8bbf17818ad3d5a864a7a70b/references/warm-realism.md) | 本轮参考：信息来源、行动条件与代价，以及现实/人物叙事的具体处境和克制收束 | 不将温暖结局、第一人称或短句偏好应用到所有作品 |
| [novel-writer-skill：文笔指南](https://github.com/xin-yi33/-novel-writer-skill/blob/d01ba0d157740de1557dbbb084877cc0ab7f3341/novel-writer/references/flows/writing-quality-guide.md) | 备选阅读：细节、留白、节奏、信息差 | 与已有自然表达建议重合，本轮不再额外导入一套规则，避免重复与相互牵制 |
| [natural-writing-skill](https://github.com/yyx20202020/natural-writing-skill/blob/71af993050cc0885eee98c2b421a965e7fde2b43/skills/natural-writing/SKILL.md) | 备选阅读：修改范围及保护作者声音 | 与已有 humanizer 适配重复，保留为后续参考 |

上述提交与实际文件已核验，许可证为 MIT；[第一个来源的许可](https://github.com/aa15107688191-collab/chinese-novel-writing-skills/blob/fc8be3aaf022f123ee190acd51b7fe4642b06d15/LICENSE)与[第三方来源声明](https://github.com/aa15107688191-collab/chinese-novel-writing-skills/blob/fc8be3aaf022f123ee190acd51b7fe4642b06d15/THIRD_PARTY_NOTICES.md)、[第二个来源的许可](https://github.com/tance-mang/chinese-webnovel-skills/blob/ecf552f6930e769d8bbf17818ad3d5a864a7a70b/LICENSE)。MIT 来源署名分别为 Chinese Novel Writing Skills contributors、tance-mang。本轮只参考创作方法，以下中文内容为 Myink 重新撰写，没有收录上游文件、代码、示例正文或完整技能提示词。现有 Humanizer/Humanizer-zh 和 GPL webnovel-writer 的来源继续见 NOTICE.md，不将它们当成本轮新增。

不推荐接入 Guyao146/Specialization-of-Online-Literature-Skill：调研时 LICENSE 的非商用/署名条款表述不一致，且全面禁用对白标签等要求不适合作为通用文笔。

## 本轮实际接入

`writing_quality_resources.py` 提供三个可在管理后台编辑、发布、退回历史版本的独立资源：

- **场景因果与有效推进**：规划、写作和审核；重视行动、阻力、选择及结果，同时允许日常、停顿和心理层次。
- **人物对白与潜台词**：写作和审核；人物的立场、掌握的信息及关系决定表达，避免所有人同腔、互相解说常识和无关装饰动作。
- **题材节奏与承诺兑现**：规划、写作和审核；按已选题材区分升级冒险、悬疑规则、关系情感及现实日常，避免把所有章尾变成悬崖。

这些属于提示词建议，不新增确定性禁词或额外模型调用；审核仍须举证，普通风格建议不得冒充严重剧情问题。作者事实、计划、硬约束、私人文风和题材承诺优先。

“开放收束”指允许情感余味和关系/认知的变化，仍需满足本章推进与既有收尾要求；短篇要完成承诺的终局，不能把未完成剧情当作留白。本轮不静默修改历史已发布的章节衔接规则。

文风库新增三种原创选项，不指定作者、叙事视角或样本人物事实：

| 文风 | 建议用途 |
| --- | --- |
| 自然叙事（通用） | 默认候选；清楚、有分寸，兼顾对话、行动与心理 |
| 明快叙事（情节向） | 冒险、升级、都市等重推进作品；允许蓄势和喘息 |
| 细腻叙事（人物向） | 关系、情感、现实等重人物作品；保持清楚处境和有效进展 |

它们是作者可选档案，不自动替换作品已有私人文风，也不覆盖主辅题材。初始化只为不存在的资源建立首版，管理员已有出版内容不会被 seed 覆盖；已有作品的冻结快照和明确取消选择保持原样，需作者在作品写作资源中选用新资源。新作品按现有默认初始化机制取得已发布创作/表达规则。

## 资源是否真的用上

已核对长篇/短篇的题材及精调、项目选定规则、角色模板和补充、私人文风，都有资源快照与提示词路径。任务准入捕获版本，后续执行和续跑沿用快照，而非随管理员后来的编辑漂移。

本轮复现并修复：长篇初稿与整章改稿此前收到私人文风，但审稿和局部补丁未收到。现在两者也显式接收该档案，角色模板替换和通用资源包装后仍保留；超预算不能静默裁掉档案。

参考资料库与“直接注入规则”不同：提示词提供准确目录和查阅指令，正文由 read_genre_reference 工具按需读取，调用记录在 tool_trace。目录存在不能证明某一轮模型实际读取。测试验证资源到达模型消息，不等于已经证明生成文字更好。

后续质量闭环待办：短篇审纲失败不应静默记为通过；参考资料零读取应显式可观测；短篇改稿后可在预算内核对原问题是否解决。这些应分开验收，避免把增加调用次数当作质量提升。

## 效果验收方法

固定题材、模型、温度、计划和上下文，比较原稿与启用推荐资源后的稿件。至少覆盖强情节、悬疑和人物/现实三类，盲评人物声音、因果/连续性、阅读节奏与表达自然度；同时记录成本、长度、修订次数。未实际执行付费模型对照前，不宣称文学质量、AI 检测概率或商业指标有所提升。

本轮验证：最终 Python 全量 2212 passed、1 skipped、5 既有 xfailed；资源集成相关 167 项通过，独立审查 38 项纯测试通过。覆盖提示词到 provider、角色模板替换后的私人档案、选择/取消选择、旧版本冻结、7 个内置文风的账号目录及上下文超限明确失败。
