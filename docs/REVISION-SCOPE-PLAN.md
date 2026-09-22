# 局部修订通道施工单：把已有的 `scope` 接上路由，让小事别再全章重写

配套阅读：[`spec/state-flow.md`](../spec/state-flow.md) §1（单章子图）/ §3（混合路由）/ §10（工具边界）、
[`docs/JEV-JUDGE-LAYER.md`](JEV-JUDGE-LAYER.md)、[`NOTICE.md`](../NOTICE.md) §一（inkos 来源声明）。

本文是**施工单**（现状核对 → 改哪里 → 按什么顺序）。动机来自一次对 inkos 的对照阅读：
它把「审稿发现的问题该小修还是重写」做成了 typed 字段 + 两条输出通道，Myink 现在的
答案是「一律重写」。

---

## 一、现状核对：谁持什么工具，以及唯一的修复动词

工具注册表只有一份，[`src/myink/workflow/tools.py:35-77`](../src/myink/workflow/tools.py#L35-L77)，
5 个**全部只读**：`inspect_character` / `inspect_foreshadows` / `inspect_plot_threads` /
`inspect_facts` / `read_genre_reference`。

| 节点 | role | 工具 | 位置 |
|---|---|---|---|
| `plan_cast` / `plan_chapter` | Planner | 无 | [nodes.py:785](../src/myink/workflow/nodes.py#L785) / [:831](../src/myink/workflow/nodes.py#L831) |
| `write` | Writer | 5 个只读 | [nodes.py:914](../src/myink/workflow/nodes.py#L914) |
| `extract` | Memory | 无 | [nodes.py:950](../src/myink/workflow/nodes.py#L950) |
| `audit` | Audit | 5 个只读 | [nodes.py:720](../src/myink/workflow/nodes.py#L720) |
| `revise` | Writer | **无** | [nodes.py:1037-1046](../src/myink/workflow/nodes.py#L1037-L1046) |
| `summarize` / `global_audit` / `ledger_l2` / `reflexion` / `book_setup` | 各自 | 无 | — |

两条要认清的事实：

1. **「Audit 不持写工具」不是 Audit 特殊**——整个系统不给任何 LLM 写工具，写库只在 `persist`
   编排层。这条是 [`spec/state-flow.md:155`](../spec/state-flow.md#L155) 写死的边界，不要动。
2. **`revise` 没有只读工具是设计如此**，不是漏配：[`spec/state-flow.md:67`](../spec/state-flow.md#L67)
   的「用到的工具」一栏写的就是 `—`。但同节点的 `write` 持全套只读工具，而 `revise` 拿到的
   只有 prompt 里塞进去的 `unresolved`——**修订时它没法自己核实任何东西**。这条本轮不改，
   只记在这里。

于是修复路径只剩一条：`audit` 报问题 → `route_after_audit` 判 `revise` → `node_revise`
**重写全章**。证据是 [`prompts.py:585`](../src/myink/workflow/prompts.py#L585) 的要求
——「输出修订后全文与 RESPONSES」，以及 [`chapter_graph.py:130`](../src/myink/workflow/chapter_graph.py#L130)
的 `revise → extract`，即改完必须重跑整条 `extract → validate → audit`。

---

## 二、代价：小事全章重写为什么是问题

audit 报一条「林砚的剑名前后不一致」，当前代价是：

```
重生成 ~3000 字全章 → 重抽取 extract → 重校验 validate（含 L2 语义比对）→ 重审核 audit
= 最多 4 次 LLM 调用（L2 判定集为空时零成本短路，见 spec/state-flow.md §2 的 validate 行）
```

其中**重生成全章是这条链里最贵的一次**（`_MAX_TOKENS["revise"] = 8192`，
[nodes.py:125](../src/myink/workflow/nodes.py#L125)），而它本可以只是一次几十 token 的补丁。

三个具体后果：

1. **预算被小事吃掉**。`max_revisions = 2`（[config.py:65](../src/myink/config.py#L65)）是共享的。
   措辞级问题先烧一轮，真正需要重写的结构问题就只剩一轮。而 `max_replans = 1`
   （[config.py:66](../src/myink/config.py#L66)）比它更紧。
2. **整章重写本身是风险**。原本没毛病的地方也可能被改坏，而 Myink 没有「退回上一版」的机制——
   [`review.py:33-35`](../src/myink/workflow/review.py#L33-L35) 已经处理过「原稿进入人工修订
   后旧候选失去依据」这类连带伤害，说明这个问题在本仓库是真实发生过的。
3. **改坏了看不出来**。`route_after_audit` 只比 `revision_count`（轮次），不比质量。修订版本
   比原稿差的时候，代码里没有任何地方知道。

---

## 三、Myink 已有的半成品：`scope` 字段（**这轮最重要的发现**）

**结论：`Finding.scope: "local" | "structural"` 已经存在，全链路都在老实标注它，
但没有任何一行代码读它做决策。** 所以这不是「加字段」，是「把已有字段接上路由」。

### 3.1 它确实存在

- 契约层：[`schemas/contract.py:179`](../src/myink/schemas/contract.py#L179)
  `scope: Literal["local", "structural"] = "local"`
- 持久层：[`models/validation.py:39`](../src/myink/models/validation.py#L39)
  `scope`，`default="local"`
- 前端类型：[`web/src/types.ts:219`](../web/src/types.ts#L219) 有 `scope`，但**没有组件读它**

### 3.2 它确实在被标注（而且标得不糙）

规则层每条 finding 都显式给了 scope，且区分是认真的：

| 位置 | 例子 |
|---|---|
| [`validation/l1.py:360`](../src/myink/validation/l1.py#L360) | 正文命中禁用词表（`prose_ban_check`）→ `critical` / **`local`** |
| [`validation/service.py:55`](../src/myink/validation/service.py#L55) | 字数出区间（§6.9 门禁）→ `major` / **`local`** |
| [`validation/l1.py:387`](../src/myink/validation/l1.py#L387) | 战力越界 → `critical` / **`structural`** |
| [`validation/l1.py:414`](../src/myink/validation/l1.py#L414) | 人设崩（台账已死却写存活）→ `critical` / **`structural`** |
| [`validation/l1.py:280`](../src/myink/validation/l1.py#L280) | 关系重复 → `major` / **`structural`** |
| [`validation/service.py:87`](../src/myink/validation/service.py#L87) | 剧情线 → `major` / **`structural`** |
| [`validation/l1.py:227`](../src/myink/validation/l1.py#L227) | 伏笔提示 → `hint` / **`local`** |
| [`validation/global_audit.py:174`](../src/myink/validation/global_audit.py#L174) | 全局审计 → **`structural`** |

注意 `l1.py:360` 这一条：**critical 但 local**——一个禁用词，改一句话就解决了。这正是
「硬约束强度」与「改动范围」是两件事的证据。当前路由把 severity 当成了范围，所以它和
「人设崩」一样被推去**重写全章**。这是本文要解决的浪费里最典型的一例。

**顺带一个准确性提示**（Phase 3 别踩）：`service.py:55` 的字数门禁是 `major`/`local`，
但它**既不是 `critical`，也不计入 `l2_major`**——[`nodes.py:675`](../src/myink/workflow/nodes.py#L675)
的 `l2_major` 只统计 **L2** 的 major。所以规则层不会强制字数问题走 revise，它进 `unresolved`
靠 audit 的语义层 verdict 带出去。**这是现状，Phase 3 加分支时不要顺手把它改成强制性**——
那是另一个话题（「字数算不算硬约束」），不是本文的范围。

LLM 层也已经在产出它：[`prompts.py:143`](../src/myink/workflow/prompts.py#L143) 的
`SYSTEM_AUDIT` 输出格式里就写着

```
"scope": "local|structural"
```

（`_check_audit` 用 `AuditVerdict.model_fields` 过滤，`findings` 的类型是 `Finding`，
所以模型给的 scope 会被正常解析进来。）

### 3.3 它确实没人用

- [`chapter_graph.py:45-74`](../src/myink/workflow/chapter_graph.py#L45-L74) `route_after_audit`
  只看 `summary.critical` / `summary.l2_major` / `revision_count` / `replan_count` / `verdict`
  —— **`scope` 一次都没出现**。
- [`prompts.py:574-577`](../src/myink/workflow/prompts.py#L574-L577) 的 `finding_lines`
  渲染 `conflict_key / severity / conflict_type / evidence / suggestion` —— **不渲染 `scope`**。
  所以修订 Agent 根本看不到这个字段。
- 全仓 `grep` 消费 `scope` 的地方只有两处**测试断言**
  （[test_bridge_repeat.py:204](../tests/test_bridge_repeat.py#L204)、
  [test_ledger_l2.py:356](../tests/test_ledger_l2.py#L356)）和一处无关的
  `request.scope`（[routes_admin.py:83](../src/myink/api/routes_admin.py#L83)）。

### 3.4 陷阱：默认值是 `"local"`

`Finding.scope` 的默认值是 `"local"`（[contract.py:179](../src/myink/schemas/contract.py#L179)）。
模型漏填、或将来某条新规则忘了标，**结构性问题会静默变成局部问题**。

所以 §七 的第一条硬要求是：**消费 `scope` 之前必须先把这个默认值改掉**（改成必填，
或改成 `"unknown"` 并让路由对 unknown 保守处理）。这条不做，接上路由就是接了个静默误判。

---

## 四、inkos 的参考实现

上游：[Narcooo/inkos](https://github.com/Narcooo/inkos)，AGPL-3.0，提交
`091048383f411eb99948a8764f42b6fd13006f9b`——**与 [`NOTICE.md`](../NOTICE.md) §一 里
已经钉住的提交号相同**，所以这不是新引入的上游。许可同为 AGPL-3.0，无兼容性问题。

### 4.1 审稿输出多一个 typed 字段

`AuditIssue` 带 `repairScope?: "local" | "structural" | "unknown"`
（上游 `packages/core/src/agents/continuity.ts:38`），prompt 里的定义（同文件 :477 / :519）：

```
"local"      措辞、段落形状、小重复、句段级小修
"structural" 主线偏离、时间线断裂、场面/回报缺失、人物逻辑崩、视角/信息边界失败
             → 或任何需要重写场景/整章的问题
"unknown"    确实判不出来时
```

### 4.2 修稿 Agent 按 scope **关掉一半能力**

`resolveAutoOutputMode`（上游 `agents/reviser.ts:602-626`）把 scope 翻成三种输出模式：

| 条件 | 模式 | 指令 |
|---|---|---|
| 阻塞项全是 `local` | `patch-only` | 「你**必须**只输出 PATCHES——不要整章改写」 |
| **任一** `structural` | `rewrite-only` | 「**禁止**输出 PATCHES，这类问题不能靠补丁修复」 |
| 混合 / `unknown` | `allow-full` | 两种都允许，模型自选 |
| 只有 info | `patch-only` | 最多润色 |

两个设计细节值得抄：

- **不从自然语言猜意图**：上游注释明确写「Unknown scope is intentionally not guessed from
  natural-language labels」——`unknown` 就是 `unknown`，不拿 issue 的措辞去猜。
- **解析阶段二次确认**：模式只是「许什么」，实际产出还要过 `parseOutput`
  （上游 :330-371）——`patch-only` 下若模型交了 `REVISED_CONTENT`，**不采纳**；
  `rewrite-only` 下若只交了补丁，**不采纳**，返回原稿。模式是硬门，不是提示。

### 4.3 补丁是**确定性应用**，模型不能借补丁之名重写

上游 `packages/core/src/utils/spot-fix-patches.ts`：

- 格式 `TARGET_TEXT` / `REPLACEMENT_TEXT`，逐块正则解析（:15-32）
- 应用顺序：精确匹配（:110-122）→ 空白归一化模糊匹配（:124-151）→ 都不中则**跳过这一个**
- **要求唯一命中**：`tryExactMatch` 里第二次 `indexOf` 命中就判失败（:118-119）
- **应用率 < 50% 整份退回原稿**（上游 `reviser.ts:337`）：防止「打了十个补丁只中一个」也算修过
- `rewrite-only` 下**明确不回退到补丁**（:350-352，注释：结构问题不能安全打补丁，
  返回原稿不改）

### 4.4 用分数决定留哪一版

上游 `pipeline/chapter-review-cycle.ts`：

```
DEFAULT_MAX_REVIEW_ITERATIONS = 1    默认只修一轮
PASS_SCORE_THRESHOLD         = 85    过了就不修
NET_IMPROVEMENT_EPSILON      = 3     涨分不足 3 分 → 丢弃新版
```

每轮修完重跑 audit 取 `overall_score`，最后在所有快照里挑**最高分且字数在合法区间内**的那版
（:292-317）。改坏了自动回退——**这正是 Myink §二 第 3 条缺的东西**。

### 4.5 另一条完全独立的线：交互 Agent 持写工具

上游的 TUI/CLI 交互 Agent（不在 pipeline 里）**是持写工具的**，包括 `patch_chapter_text`
（`agent/agent-tools.ts:3422`，工具集注册在 `agent/agent-session.ts:978`）。但它的落盘动作是
（`interaction/edit-controller.ts:363-402`）：

```
归档旧版本 → 写入补丁后正文 → 清掉该章 runtime 文件 → markChapterForManualReview
```

即**打完补丁标记待人工复核**，不静默继续。这条与 Myink 的候选池有直接关系，见 §五。

---

## 五、Myink 不能照抄的地方（**动手前先想清楚这一节**）

### 5.1 记忆层是 DB 台账 + 候选池状态机，不是从文件重建

上游的记忆是文件：`current_state.md` / `particle_ledger.md` / `pending_hooks.md`。
补丁改完正文，**清掉 runtime 文件重新结算**就一致了——文件是派生物，重建是廉价且幂等的。

Myink 的记忆是 `facts` / `character_states` / `relations` / `events` 的**追加式时间窗台账**
加上 `memory_candidates` 候选池状态机（[`spec/state-flow.md:64-68`](../spec/state-flow.md#L64)）。
补丁改了正文却跳过 `extract`，会产生两个方向的静默分叉：

- **台账 vs 正文**：正文里已经不成立的句子，台账还按旧稿记着。
- **候选池 vs 正文**：池子里躺着按旧稿抽出来的候选，
  [`review.py:32-35`](../src/myink/workflow/review.py#L32-L35) 已经把这类「失去依据的旧候选」
  处理过一轮，说明这是真实会发生的。

### 5.2 L2 是「正文 vs 台账」的语义比对，补丁可能正好动了那根引信

[`validation/ledger_l2.py`](../src/myink/validation/ledger_l2.py) 的判定集来自 extract 候选，
比对的是**正文与台账的语义差**。一个「local」的措辞补丁（比如把「他左手持剑」改成「右手」）
完全可能翻转一条 L2 结论。所以「local 补丁 → 跳过 extract」这个推论在 Myink 不成立。

### 5.3 现在这条全链重跑是**正确性保证**，不是浪费

[`chapter_graph.py:129-130`](../src/myink/workflow/chapter_graph.py#L129-L130) 的注释写得很清楚：
「修订改变了正文：重新抽取记忆并校验，不能持旧候选/旧报告审核新稿」。收窄重跑范围就是
在削弱这条保证——所以 §十 才把它单列成一个需要你决策的 Phase，而不是顺手改掉。

---

## 六、验收目标

1. `scope` 的默认值被改掉（不再有「漏填 = local」的静默路径）。
2. 全 `local` 的发现走**补丁通道**，不再重写全章；产出正文的**未触及部分逐字不变**。
3. 含 `structural` 的发现**仍然走原路**（全章重写 + 全链重跑），行为逐字不变。
4. 补丁的应用是**确定性**的：唯一命中、模糊兜底、应用率不足则整份退回原稿。
5. 补丁通道的重跑范围**收窄但记忆层不与正文分叉**（具体选项见 §十）。
6. 新增预算与 `max_revisions` **分离**，小事不再吃重写额度。
7. 全量测试（对齐 CI：`EMBED_ENABLED=0`）全绿。

---

## 七、Phase 1 · 修默认值 + 补丁确定性层（零 LLM 风险，先做这个）

### 7.1 先堵住 `scope` 的默认 `local`

[`contract.py:179`](../src/myink/schemas/contract.py#L179) 与
[`models/validation.py:39`](../src/myink/models/validation.py#L39)：

```python
# 之前：漏填静默变 local，将来拿它做路由就是静默误判
scope: Literal["local", "structural", "unknown"] = "unknown"
```

新增 `"unknown"` 并让路由对 unknown **保守处理**（当 structural 走全章重写）。DB 列已有
`default="local"`，是否需要 migration 取决于是否要改 DB 默认——**建议只改 Python 侧**，
DB 默认留作历史行的兜底（`scope` 已经落库的历史数据不应被改写）。

### 7.2 新增补丁确定性层

新建 `src/myink/workflow/patches.py`（纯函数，无 IO、无 LLM）：

```python
def parse_patches(raw: str) -> list[Patch]:      # 解析 === PATCHES === 块
def apply_patches(original: str, patches) -> ApplyResult
    # ApplyResult: applied / content / applied_count / skipped_count / rejected_reason
```

行为对齐上游 `spot-fix-patches.ts`：

| 行为 | 要求 |
|---|---|
| 精确匹配 | 命中且**唯一**才用；不唯一即判失败 |
| 模糊兜底 | 空白归一化后匹配，映射回原文位置；目标短于 ~10 字不做模糊（太容易撞） |
| 单个失败 | **跳过这一个**，不整份放弃 |
| 整份失败 | 应用率 < 50% → 返回原稿 + `rejected_reason` |
| 空补丁 | 返回原稿、`applied=False` |

**这一阶段完全不接 LLM**，纯函数 + 单元测试就能验收（对齐 CLAUDE.md「cover new pure functions；
prefer Vitest for new tests」——Python 侧用 pytest，顶格 `test()`，见 §十二）。

---

## 八、Phase 2 · `revise` 分两条输出通道

### 8.1 新增补丁模式的 system prompt

[`prompts.py:132`](../src/myink/workflow/prompts.py#L132) 旁边加 `SYSTEM_REVISE_PATCH`，
与 `SYSTEM_REVISE` 并列。要点（照抄上游 `reviser.ts:411-412` 的分流指令口径）：

- 只改审稿意见指出的具体句子/段落，**其余内容原封不动**
- 修改范围限定在问题句及其前后各一句
- 禁止改动无关段落；禁止借补丁之名重写
- 做不出补丁就**留空 PATCHES**，不要硬凑
- 输出格式：

```
=== FIXED_ISSUES ===
(逐条说明修了什么)

=== PATCHES ===
--- PATCH 1 ---
TARGET_TEXT:
(必须从原文精确复制、能唯一命中的原句或原段)
REPLACEMENT_TEXT:
(替换后的局部文本)
--- END PATCH ---

=== RESPONSES ===
[{"conflict_key": "...", "outcome": "fixed|cannot_fix|dispute", "note": "..."}]
```

### 8.2 `node_revise` 按 scope 选通道

[`nodes.py:1029-1063`](../src/myink/workflow/nodes.py#L1029-L1063) 改成：

```python
mode = resolve_revise_mode(state)   # "patch" | "full"
```

其中 `resolve_revise_mode` 是个**纯函数**，规则对齐上游 `resolveAutoOutputMode`
（§4.2 那张表），输入是 `unresolved` + `audit_verdict.findings`，输出是模式。
`unknown` 归 `full`（保守）。

解析阶段要做二次确认（对齐上游 `parseOutput`）：patch 模式下若模型交了 `=== CONTENT ===`
全文，**不采纳**，走 §7.2 的 `apply_patches`；补丁全失败则**保留原稿**并记
`rejected_reason`，不要退回让模型整章重写（那等于没有这个功能）。

### 8.3 工具那栏

`revise` 现在没有只读工具（§一）。补丁模式**不需要**它，本轮不加。

---

## 九、Phase 3 · 预算与路由

### 9.1 预算分离

[`config.py:65-67`](../src/myink/config.py#L65-L67) 新增：

```python
max_patches: int = 2   # 补丁轮次上限（比重写便宜，但也不能无限打）
```

理由见 §二 第 1 条：补丁轮次不该吃 `max_revisions`。

### 9.2 `route_after_audit` 加一个出口

[`chapter_graph.py:45-74`](../src/myink/workflow/chapter_graph.py#L45-L74) **只加分支，
不改现有优先级**：

```
现在：① L1 critical / L2 major → revise   ② 预算用尽 → needs_review
      ③ verdict → pass / rewrite / replan
```

**关键约束：规则层「L1 critical 不被绕过」的语义绝不能动。** `l1.py:360` 的禁用词类
critical 是 `local`，它仍然要修——只是改走补丁通道，**不是放行**。所以新增的分支是
**在①内部选通道**，不是把①的命中条件改成「local 才修」：

```
① L1 critical / L2 major
   ├─ 全部 local 且 patch_count < max_patches → patch
   └─ 含 structural（或 unknown）           → revise（现状，逐字不变）
```

`node_route` 的 `record_plain` detail（[chapter_graph.py:80-85](../src/myink/workflow/chapter_graph.py#L80-L85)）
要补上 `revise_mode` / `patch_applied` / `patch_skipped`，否则前端流转图看不出走了哪条通道。

### 9.3 补丁轮次也用 `reset` 清瞬态

[`chapter_graph.py:24-42`](../src/myink/workflow/chapter_graph.py#L24-L42) 的
`node_reset_replan` 处理的正是「残留状态短路」问题。补丁轮次回到 `extract` 前，
`unresolved` / `audit_verdict` 的处理方式要跟着确认（补丁只解决了一部分 finding 时，
剩下的必须留到下一轮，不能被清掉）。

---

## 十、Phase 4 · **重跑范围（最需要你决策的一步）**

补丁改完正文后回到哪里？三个选项：

### 选项 A · 补丁后照旧全链重跑（`patch → extract → validate → audit`）

- **改动最小**：`chapter_graph.py` 的那条边完全不动，只多一个通道选 prompt。
- **正确性最强**：§五 的两条分叉都不存在。
- **收益**：省下的只是「全章重写」那一次生成（通常是整条链里最贵的一次——8192 token 上限
  的正文生成 vs 一次补丁生成）。extract / validate / audit 照跑。
- **代价**：省不到「4 次调用 → 1 次调用」那么夸张。

### 选项 B · 补丁后只跑 `validate → audit`，跳过 `extract`

- **收益最大**：3 次调用省掉 extract。
- **必须解决的问题**：§5.2 的 L2 引信——补丁可能正好动了台账依赖的那句话。
  可行的判据：**补丁触及的段落是否命中 extract 候选的证据区间**
  （`Finding.evidence[].quote` 逐字来自正文，可比对补丁落点）。
- **风险**：判据一旦有漏，就是静默分叉，而且分叉要到后续章节才显形。
- **建议**：如果选 B，**补丁轮次必须同时把该章标记为待复核**（对齐上游
  `markChapterForManualReview`，§4.5），让分叉有机会被人看到。

### 选项 C · 只把 `local` 补丁用在**不触及台账**的一类上

比如只允许 `conflict_type == "style"` 且 `severity == "hint"` 的发现走 B 路径，
其余仍走 A。**范围最窄，代价是收益也最窄**。

**倾向**：先做 A（Phase 1–3 就能独立上线），把 B 作为后续独立一轮——
理由是 A 的收益已经覆盖「最贵的那次调用」，而 B 的正确性论证需要 §5.2 那个判据先被测试钉住。

---

## 十一、Phase 5 · 观测与前端

- `scope` 已经在前端类型里（[types.ts:219](../web/src/types.ts#L219)）但没被渲染。
  补丁通道上线后，审核面板应该能看出「这条是局部修的 / 那条触发了全章重写」。
  这是**你之后自己改**的地方，本文只标注位置。
- [`web/src/components/ReviewFlow.test.tsx:187`](../web/src/components/ReviewFlow.test.tsx#L187)
  的 fixture 里已有 `scope: 'local'`，改动时注意同步。
- 注意本仓库的现行约定：**界面不放提示性小字**，能并进标签的并进标签
  （见提交 `8ae8487`）。通道名要做成标签/徽章，不要加灰色说明文字。

---

## 十二、Phase 6 · 测试

### 新增（Phase 1，纯函数，无 LLM）

1. `test_apply_patch_exact_unique` —— 精确命中且唯一 → 替换成功，**其余字节逐字不变**。
2. `test_apply_patch_ambiguous_rejected` —— TARGET_TEXT 在原文出现两次 → **拒绝该补丁**。
3. `test_apply_patch_fuzzy_whitespace` —— 只差空白 → 模糊命中，落点正确。
4. `test_apply_patch_skip_individual` —— 3 个补丁中 1 个不中 → 中 2 个，`skipped_count == 1`。
5. `test_apply_patch_below_threshold_rejects_all` —— 命中率 < 50% → **返回原稿**，带 `rejected_reason`。
6. `test_apply_patch_empty_returns_original` —— 空补丁 → 原稿 + `applied=False`。

### 新增（Phase 2）

7. `test_resolve_revise_mode_all_local_is_patch` —— 全 local → `patch`。
8. `test_resolve_revise_mode_any_structural_is_full` —— 含 structural → `full`。
9. `test_resolve_revise_mode_unknown_is_full` —— unknown → `full`（保守）。
10. `test_patch_mode_ignores_revised_content` —— patch 模式下模型交了全文 → **不采纳**，
    走补丁路径。
11. **`test_l1_prose_ban_critical_still_repaired`** —— `l1.py:360` 那条禁用词
    `critical`/`local` 的发现**仍然被修**（改走补丁，不是放行）。这条是防止 §9.2 被
    误实现成「local 就不修」的核心回归。

### 现有测试

- [`tests/test_review_routing.py`](../tests/test_review_routing.py) 的
  `test_independent_route_budgets`（参数化的 6 个 case）**必须全部保持原样通过**——
  它是路由优先级的锚点。
- [`tests/test_conflict_sample_suite.py`](../tests/test_conflict_sample_suite.py) 是当前
  工作树里正在改的文件之一，**本计划不碰**。
- [`tests/test_ledger_l2.py:356`](../tests/test_ledger_l2.py#L356) 的 `scope == "local"`
  断言：若 Phase 1 改了默认值，确认这条断言仍然成立（它断言的是**被 audit 覆盖后的值**，
  应不受影响，但要跑）。

---

## 十三、回归面（这些**不该**被这次改动碰到）

- **规则层优先级**：L1 critical / L2 major 不被绕过、`max_revisions` 的语义。
  `route_after_audit` 只加分支，不改①的命中条件与顺序。
- **`persist` 的确认分流**（[nodes.py:1068](../src/myink/workflow/nodes.py#L1068) 起）：
  `needs_review` 怎么判、候选怎么落，本轮不动。
- **工具边界**：不给任何 LLM 加写工具；`revise` 本轮也不加只读工具。
- **`spec/state-flow.md` §3 的路由伪代码**：Phase 3 落地后要同步更新，否则文档与代码分叉。
- **工作树里正在进行的未提交改动**（`src/myink/validation/l1.py`、`service.py`、
  `genres`/风格相关文件、`web/src/pages/SettingsPage.tsx` 等）——本轮**完全不碰**。
  注意 `l1.py` 与 `service.py` 恰好是本文引用最多的两个文件，**开工前先确认那批改动已落地**，
  否则行号会漂。

---

## 十四、风险

| 风险 | 影响 | 处置 |
|---|---|---|
| **`scope` 默认 `local` 未先修** | 结构性问题被判局部 → 补丁修不了 → 白烧一轮 | Phase 1 §7.1 是硬前置，不得跳过 |
| **补丁改坏原文**（模糊匹配落错位置） | 正文损坏且不易察觉 | 唯一命中 + 目标过短不做模糊 + 应用率门槛；测试 1–6 钉死 |
| **记忆层与正文静默分叉** | 要到后续章节才显形 | §十 选 A（全链重跑）即无此风险；选 B 必须标记待复核 |
| **`local` 被误实现为「不修」** | critical 被放行，硬约束失效 | 测试 11 专项钉死 |
| **补丁轮次吃重写预算** | 真需要重写时没额度 | Phase 3 预算分离（`max_patches`） |
| **上游代码许可** | 面试作品的法律瑕疵 | 无：同为 AGPL-3.0，且提交号已在 [NOTICE.md](../NOTICE.md) §一声明。**但只借鉴设计，不复制代码**；若将来有逐字移植，按 NOTICE.md §一 的格式补一条 |
| **行号漂移** | 施工单对不上代码 | 工作树有未提交改动（见 §十三），开工前重新核对 |

---

## 十五、落地顺序

```
Phase 1  scope 默认值 + patches.py（纯函数）   ← 零 LLM 风险，可先独立落地
   ↓  测试 1–6 绿
Phase 2  resolve_revise_mode + SYSTEM_REVISE_PATCH + node_revise 分路
   ↓  测试 7–11 绿
Phase 3  预算分离 + route_after_audit 加分支 + node_route 记账
   ↓  test_independent_route_budgets 六个 case 原样通过
Phase 4  重跑范围（§十 选 A / B / C）           ← 决策点，建议先 A
Phase 5  前端呈现通道（你自己改）
Phase 6  全量测试 + 同步 spec/state-flow.md §3
```

**Phase 1 与 Phase 2 必须同批**：只落 `patches.py` 没有调用方是死代码；
只加 `resolve_revise_mode` 而没有确定性应用层，等于让模型自由发挥。

---

## 十六、待你确认

1. **重跑范围选 A / B / C？** 见 §十。倾向 A 先上，B 单独一轮。
2. **`scope` 默认值改成 `unknown` 还是改成必填？** 见 §7.1。
   改成必填更硬（漏填直接报错），但要确认 audit 的 JSON 解析失败不会连累整章。
3. **补丁通道要不要重写预算也设上限？** 即 `max_patches` 是否与 `max_revisions` 共享总轮次上限，
   还是完全独立。§9.1 按完全独立写的。
4. **补丁轮次要不要在 `agent_runs` 里单独记 role？** 现在 `revise` 的 role 是 `"Writer"`
   （[nodes.py:1038](../src/myink/workflow/nodes.py#L1038)），补丁通道是同一 role 还是新开一个。

---

## 附一：这次计划**不**做的事

- **不给任何 LLM 写工具**。补丁是「模型产出文本 → 服务端确定性套用」，落库仍只在 `persist`。
- **不动 `write` 节点**。`write` 是首次生成，不是修订，没有「保持原文不变」的诉求。
- **不动 `replan` 分支**。replan 是「谁出场」的问题（[chapter_graph.py:11-12](../src/myink/workflow/chapter_graph.py#L11-L12)），
  与修订范围是正交的两件事。
- **不引入评分回滚机制**（上游 §4.4 那套）。Myink 现在没有 `overall_score` 这个概念，
  引入它是一次独立的、涉及 audit 输出契约的改动。本轮只在 §二 记下这个缺口。
- **不给 `revise` 加只读工具**（§一 第 2 条）。
- **不碰短篇、不碰扫榜**。

## 附二：和「Jev 判定层」的关系

[`docs/JEV-JUDGE-LAYER.md`](JEV-JUDGE-LAYER.md) 是一份**决策记录**，结论是：Jev
（封闭选项集上输出带概率的类型化决策、不产文本）**不能替换 L2 / 单章 audit / 全局审计**
——这三者都必须产自然语言内容；它唯一合适的落点是两个目前不存在的维度
（桥段「刻意呼应 vs 偷懒重复」、文风「偏离作者基线 vs 正常」）。

**与本文是正交的**：Jev 管「新增哪个判定维度」，本文管「已有判定怎么处置」。

但有一处**同源的问题**值得并读。Jev 文档「现状」一节自己点出了一处既有错配：

> L2 是概率性判定却被当成硬阻塞，字数门禁是确定性判定却只在软层

这和本文 §三 是同一个病的两个面：**Myink 现在用 `severity`（多严重）代替了
`scope`（该改多大范围）去做路由决策**。本文给的是「范围」这一半的答案；Jev 文档给的是
「确定性 vs 概率性该不该当硬阻塞」那一半。两者都落地后，
[`chapter_graph.py:45-74`](../src/myink/workflow/chapter_graph.py#L45-L74) 的路由条件
应该复盘一次——但**不要在同一批里改**，否则出问题分不清是谁的。
