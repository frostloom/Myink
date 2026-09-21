# Jev 判定层：接入点评估与决策

2026-09-21。评估把 Jev（TypeSafe 的判定模型：不生成文本，只在封闭选项集上输出带概率的类型化决策）引入审核体系的位置，以及它能否替换现有各层。

本文是**决策记录**，不是施工单。结论部分不随代码演进失效；具体行号只作检索锚点。

## 结论

1. **Jev 不能替换 L2、单章 audit、全局审计的卷推进维度**——这三者都必须产自然语言内容（引文 / 理由 / 建议 / 恢复方案），Jev 按定义不产。
2. **Jev 唯一合适的落点是两个目前不存在的维度**：桥段「刻意呼应 vs 偷懒重复」、文风「偏离作者基线 vs 正常」。二者都是有限枚举 + 零散文产出 + 输入短、判据局部。
3. **这两个维度不是新增功能，是补完原设计**——API 层、响应契约、`record_report` 的入参、`_run_kind_llm` 的签名全都为多维度预留好了，只是只有卷推进一路被接通。
4. **接入前必须先探测端点**（见「接口缺口」）。Jev 的实际请求/响应形状、是否容忍 `reasoning_split`、中文判断力都还没有实测数据；探测不通，整个方案不成立。
5. **新维度天然不阻塞**：全局审计的 findings 只落进 `GlobalAuditReport`，不参与章节路由（`batch_graph.py:413-414` 只把它塞进 batch state）。这是结构保证，不依赖 severity 取值——比「靠 `hint` 不阻塞」硬。

## 现状：四层审核与各自的阻塞档位

| 层 | 实现 | 判定产物 | 阻塞档位 |
|---|---|---|---|
| L1 确定性 | [l1.py](../src/myink/validation/l1.py) 等 11 项检查、13 个检出点，零模型 | Finding（severity 五档） | **critical 硬阻塞**（走 revise / needs_review）；**major 仅记录** |
| L2 语义 | [ledger_l2.py](../src/myink/validation/ledger_l2.py)：确定性预滤 → 1 次 LLM → 本地守卫 | Finding（`major/structural`） | **硬阻塞**（`summary.l2_major` 被路由直读） |
| 单章 audit | `node_audit` + [SYSTEM_AUDIT](../src/myink/workflow/prompts.py) | `AuditVerdict{pass\|rewrite\|replan}` + reasons + findings 建议 | 规则层放行后才生效 |
| 全局审计 | [global_audit.py](../src/myink/validation/global_audit.py)，每 K≈30 章一批 | 目前只有 `drifted\|behind`（卷推进） | **不阻塞**（不进章节路由） |

L1 的 13 个检出点按严重度分布：

- `critical` — `_realm_checks`（境界越界 ×2）、`_alive_checks`（死而复生）、`faction_check`（阵营敌对）
- `major` — `power_inflation_check`（战力通胀）、`relation_ledger_check`（关系台账自洽 ×2）
- `minor` — `_old_value_ledger_check`、`_relation_change_ledger_check`
- `hint` — `foreshadow_debt_check`、`plot_thread_debt_check`、`bridge_repeat_check`、`style_repeat_check`

路由规则见 `route_after_audit`（[chapter_graph.py:45-74](../src/myink/workflow/chapter_graph.py#L45-L74)）：`l1_critical or l2_major` 先短路；只有规则放行才读 audit 的 verdict。

**一处既有错配**（与 Jev 无关，但同一张表里看得见）：L2 是概率性判定却被当成硬阻塞，字数门禁是确定性判定却只在软层（`_LEN_LOW_RATIO = 0.8` / `_LEN_HIGH_RATIO = 1.3`，[service.py:24-25](../src/myink/validation/service.py#L24-L25)）。另外该模块 docstring 写「超长比过短更伤（水漫金山）」，但阈值是 -20% 就触发、+30% 才触发——数字与说法相反。

## 判据：什么判定能交给 Jev

四条的合取：

1. **除选项外零自然语言产出**——判定结果就是那个枚举值，不需要模型再写理由、引文、位置或建议。这一条是硬门槛：需要散文的判定无法「只取选项」，强行取会丢掉下游必需的信息。
2. **判定集有限且封闭**——选项能事先穷举，模型不得自造新选项。
3. **输入短、判据局部**——被判定对象的判据集中在少量文本里，不需要全局上下文或跨章推理。Jev 单次判定 ~p50 230ms，靠的是小输入；输入一长，成本与延迟优势同时消失。
4. **存在能证伪的评测集**——有标注样本可以算出检出率与误报率。没有这条，换层就是凭感觉。

合成一句话：**「Jev 能接管的判定 = 有限枚举的选项 + 除选项外零自然语言产出 + 输入短且判据局部 + 有可证伪的评测集。」**

只满足前两条不算——L2 的 `valid|invalid`、audit 的 `pass|rewrite|replan`、卷推进的 `drifted|behind` 选项集都是封闭的，所以「闭集」本身没有区分力。

## 逐层对照：为什么换不掉

| 候选 | 卡在哪一条判据 | 说明 |
|---|---|---|
| L2 正文-台账语义比对 | ① 零散文 | 守卫要求 evidence 是正文的**逐字子串**（[ledger_l2.py:146](../src/myink/validation/ledger_l2.py#L146)）。引文只能由模型产出，确定性侧无法合成——判据本身依赖「把正文原句摘出来」这个生成行为。 |
| 单章 audit | ① 零散文 + ② 闭集 | `AuditVerdict` 除 verdict 外还要 reasons、findings 的 suggestion、重规划目标。路由消费的正是这些散文（`semantic_block` 依据 findings 的 severity）。 |
| 全局审计·卷推进 | ① 零散文 | 每条 finding 强制要 `reason` + `recovery`，守卫会丢弃缺任一者（[global_audit.py:159](../src/myink/validation/global_audit.py#L159)）。 |
| 全局审计·人设漂移 | ③ 输入短 | 需要对照 `characters.personality` 基线 + 跨章语境，判据不局部。（该项的落地状态见下节脚注。） |
| L1 全部 13 项 | 无需模型 | 已经是零模型的确定性检查。Jev 在这里没有任何可替代的东西——用模型替换查表是净亏。 |

反过来看，L1 里那两个**看起来**像语义判定的点（`_alive_checks` 的死而复生、`bridge_repeat_check` 的近邻重复）之所以留在 L1，是因为它们的判据已经被压成了确定性形式：前者查台账 `alive` 字段，后者只做向量近邻 + 词表豁免。它们**误判的来源恰恰是判据被压得太狠**（假死、无标记的刻意呼应），而修这个的方向不是换模型，是把语义判断补到独立的维度上——也就是下面这两个。

## 接入点：桥段呼应 + 文风漂移

### 为什么是这两个

| | 桥段呼应 | 文风漂移 |
|---|---|---|
| 判定集 | `echo`（刻意呼应，正常）\| `repeat`（偷懒重复，恶性） | `ok` \| `drift`（偏离作者自身基线） |
| 除选项外的产出 | 无 | 无 |
| 输入 | 一对事件摘要（各一到两句）+ 向量距离 | 基线摘录若干 + 当前样本摘录 |
| 判据局部性 | 单对判定，不需全书语境 | 单样本对基线判定 |
| 现有覆盖 | L1 只有词表豁免，无标记的呼应会误报 | L1 只数高频句式/词，不比对基线 |
| 评测集 | 样例 37（阴性） | 样例 38（阳性）/ 39（阴性） |

两者都是「正常创作手法 vs 质量问题」的二分，恶性侧才出 finding，良性侧直接丢——不产 finding 就不需要解释，这正是「零散文」能成立的原因。

### 这是补完，不是新增

以下四处都已就位，只差实现：

- [routes_global_audit.py:47-49](../src/myink/api/routes_global_audit.py#L47-L49) 已经在读 `summary["bridge"]` / `["style"]` / `["volume"]`
- `GlobalAuditSummaryOut` 已有 `bridge` / `style` / `volume` 三个可选字段（[schemas.py:327-329](../src/myink/api/schemas.py#L327-L329)）
- `record_report` 的 `kind_errors` 参数与 `if kind_errors: summary["errors"] = ...` 分支从未被任何调用方使用
- `_run_kind_llm` 的命名与签名（`detail` 里带 kind 信息）本就是为「多维度共用 runner」写的，当前只有卷推进一路调用

### 判定契约

模型只允许输出封闭选项，不得产理由、引文或建议：

```json
bridge: {"judgments": [{"key": "...", "verdict": "echo" | "repeat", "confidence": 0.0-1.0}]}
style:  {"judgments": [{"key": "...", "verdict": "ok" | "drift",   "confidence": 0.0-1.0}]}
```

prompt 中明示：不确定 → 取良性选项（`echo` / `ok`），宁缺毋滥。

### 确定性守卫

与卷推进的 `normalize_and_verify_findings` 有本质区别：**那里校验逐字引文，这里不能**——这里的证据是确定性侧自己合成的（如「窗口第 N 章事件 X 与第 M 章事件 Y 高度相似，余弦距离 0.xxx」），根本没有引文可校。守卫只校验封闭集成员资格：

- `key` 必须落在预滤集里（挡模型伪造 key）
- `verdict` 必须是恶性侧（`repeat` / `drift`）；良性侧直接丢弃，不产 finding
- `confidence >= MIN_CONFIDENCE`（0.6，复用 [global_audit.py:25](../src/myink/validation/global_audit.py#L25)）
- 按 key 去重，保留最高置信度

产出的 finding：`severity="hint"`、`scope="structural"`、`source="L2"`、`conflict_type` 为 `bridge` / `style`。注意 `ConflictType` 目前**没有** `bridge`（[contract.py:25](../src/myink/schemas/contract.py#L25)），需要补。

### 预滤集（空集 ⇒ 零调用）

仿 `run_ledger_l2` 的空判定集短路（[ledger_l2.py:182-183](../src/myink/validation/ledger_l2.py#L182-L183)）：

- **bridge** — 复用 L1 的向量近邻机器（encode + `PgvectorStore().search(level="event")`，`distance < 0.3` 且章距 ≥ 10）。只复用向量机器，**不继承** L1 的「每章至多一条」和「含标记词则整章豁免」语义——这里要的是完整候选对，豁免与否正好是要判的东西。是否用 `_has_callback_marker` 预剪掉带标记的对可作为可调常量（剪了省成本，代价是遮住 L1 与 L2 的分界）。
- **style** — 基线 = 窗口之前已确认章节的确定性摘录；样本 = 窗口内已确认章节摘录。**基线为空 ⇒ 空集**（首个窗口无锚点，中性跳过，零调用）。

一处实现约束：`encode` 必须留在 `l1` 模块内，因为测试通过 patch `myink.validation.l1.get_embedder` 注入假 embedder（[test_flow.py:129-135](../tests/test_flow.py#L129-L135)）。抽公共函数时把 encode 一起搬走会让这个 patch 失效。

## 接口缺口

| 缺口 | 现状 | 影响 |
|---|---|---|
| **端点形状未探测** | 未实测 | 决定是「加个角色名即可」还是「要写 provider 适配器」 |
| **`reasoning_split` 无条件注入** | [openai_compatible.py:47](../src/myink/providers/openai_compatible.py#L47) 对**所有非 deepseek 主机**注入 `extra_body["reasoning_split"] = True` | 端点若拒绝未知字段会 400。最可能的拦路虎 |
| **`_run_kind_llm` 硬编码 `make_chain("audit")`** | [global_audit.py:218](../src/myink/validation/global_audit.py#L218) | 加维度前必须先泛化成显式传 `role` / `result_key`，否则把 `audit` 指向 Jev 会**顺带改掉卷推进的模型选择** |
| **测试打桩单点** | `tests` 通过 patch `ga.make_chain` 打桩 | 所有 `make_chain` 调用必须留在 `global_audit.py`；维度模块自行 import 会让打桩失效 |
| **未配置角色是静默的** | 未配置 → `MissingModelProvider` 报错，但错误目前只进 `summary` | 前端必须把 `summary["errors"]` 显示出来，否则 Jev 没配是**看不见的**——最阴的坑 |

生产环境下 fallback 链长度恒为 1（多模型降级已裁撤，`DEFAULT_ROUTES` 为空），所以 Jev 失败是显式报错，不会静默降级到一个更贵的大模型。

关于 `judge` 角色是否加进 `_ROLE_INHERIT`（[providers/__init__.py:34-37](../src/myink/providers/__init__.py#L34-L37)）：**建议先不加**。加了会继承到普通模型上，Jev 悄悄退化成大模型，A/B 的隔离性就没了；不加则未配置时明确报错、维度非阻断地进入休眠态。

## 评测协议

现有 `spec/conflict-samples.md` 提供 40 例标注样本与检出率/误报率口径，`tests/test_conflict_sample_suite.py` 是可运行的度量工具。Jev 的验证沿用同一协议，加一臂对照：

- **A 臂** = Jev 连接；**B 臂** = 普通大模型（`json_mode`、低温）作对照。两臂喂同一份 prompt 契约。
- 记录每样本的 verdict / confidence / 是否命中预期 / tokens / 耗时 / 成本；聚合检出率、误报率、两臂一致率、p50 延迟、总成本。
- 阴性样本上误报率 > 0 即非零退出。
- 仿 [eval-logic.py](../scripts/eval-logic.py)：必须显式 `--live`，直调 provider，不碰数据库，结果写 `docs/evaluations/`，不进 CI。

**启动门槛**：先做端点探测，用真实 prompt 契约跑已标注片段（样例 37 那一对期望 `echo`，样例 38 期望 `drift`，样例 39 期望 `ok`）。这三例不全对，方案不成立，不必往下走。

## 未决问题

1. **bridge 维度目前没有阳性样本**。样例 37 是**阴性**（无标记的刻意呼应 → 期望不检出），样例 14 是 L1 侧的阳性。也就是说 bridge 现在只能测误报率，**检出率不可测**。补一例阳性（两个无标记的近重复事件 → 期望 `repeat`）会牵动 `POSITIVE_COUNT` 26→27、`DETECTED_COUNT` 21→22 以及样例文档的度量说明——与「评测集扩展不是现在」的决定相冲突。要么本次补这一例，要么明确承认 bridge 只有误报率。
2. **无大纲项目的行为变化**。现在 `run_global_audit` 在无大纲时零调用早返回（[global_audit.py:239-244](../src/myink/validation/global_audit.py#L239-L244)）；补完两个维度后会变成「无大纲但 bridge/style 有集时照发调用」，对这类项目**新增成本**。可接受吗？（有 cap 与空集短路控制上限。）

## 落地顺序

端点探测 → `judge` 角色管道 → **`_run_kind_llm` 泛化（全量测试全绿为 checkpoint）** → bridge 维度 → style 维度 → 接线 → A/B 评测与阈值调优。

关键 checkpoint 是第三步：卷推进的行为必须逐字节不变，再往下加维度。

## 附注：盘点中发现的两处既有问题（与 Jev 无关）

1. **文档与代码漂移**：[spec/conflict-samples.md](../spec/conflict-samples.md) 声称样例 12（人设漂移）、37（桥段呼应）、38/39（文风漂移）对应的全局审计 L2 维度「已落地（2026-08-12 / 08-13）」，并指向 `global_audit.py` 的「人设维度 / 桥段维度 / 文风维度」。**实际代码只有卷推进一路**：`normalize_and_verify_findings` 只接受 `drifted|behind`，`run_global_audit` 只调一次卷推进。现有三个样例测试是靠守卫丢弃非法 verdict、或靠无大纲早返回来「通过」的——假通过。本文这两个维度做完，那个声称才真正成立，届时应把措辞与度量数字一并对齐。
2. **audit 是唯一做路由决策却没有真实评测覆盖的语义层**。样例套件里 `AuditStub` 把它整体打桩，所以路由质量（verdict 分布的准确度）目前没有任何数据。另外 `validate → audit` 是无条件边（[chapter_graph.py:115](../src/myink/workflow/chapter_graph.py#L115)），而 `route_after_audit` 本来就会在 `l1_critical or l2_major` 时短路——改成条件边可以省掉一批注定被丢弃的 audit 调用，顺带能量出「多少比例的章节根本不需要 audit」。
