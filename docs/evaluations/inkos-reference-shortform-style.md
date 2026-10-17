# inkos 调研报告：短篇对话式创作与文风抽取

调研对象：inkos v1.7.0（`E:\github项目\ai小说助手\inkos`，pnpm monorepo：`packages/core`（引擎）、`packages/cli`、`packages/studio`（Web 前端 + Hono 后端）。只读调研，未修改任何文件。

---

## 一、短篇对话式创作的前端与交互

### 1. UI 形态

Web 应用（React + Vite + Zustand + Tailwind，服务端为 Hono）。
- 前端入口：`packages/studio/src/main.tsx` → `App.tsx` → 页面在 `packages/studio/src/pages/`
- 聊天主页面：**`packages/studio/src/pages/ChatPage.tsx`**（所有会话 kind 复用同一页面，通过 `sessionKind` 区分：`"book" | "book-create" | "short" | "play" | "script" | ...`）
- 关键点：**inkos 没有独立的“短篇聊天页面”**。短篇会话（`sessionKind === "short"`）就是同一个 ChatPage，只换空态提示文案：

```tsx
// packages/studio/src/pages/ChatPage.tsx:860-865
const emptyGuidance = (() => {
  if (currentSessionKind === "short") {
    return isZh
      ? "说一个短篇方向、标题灵感、人物压力或核心冲突，我会走 InkOS Short 生成正文、简介和封面。"
      : "Describe a short-fiction direction, title hook, pressure, or core conflict to run InkOS Short.";
  }
```

输入区、消息列表、模型选择器全部与长篇建书共用一套。

### 2. 对话区 / 输入区的具体形状

**消息列表**（ChatPage.tsx:927-1023）：
- 消息区 `max-w-3xl mx-auto space-y-4`，居中一列，窄栏。
- 用户消息右对齐带气泡底色，助手消息左对齐无气泡（`packages/studio/src/components/ai-elements/message.tsx:37-66`：`from === "user" ? "is-user ml-auto items-end" : "is-assistant items-start"`，用户消息 `bg-secondary rounded-lg px-4 py-3`）。
- 助手消息按 **parts 顺序渲染**：thinking（可折叠 Reasoning）→ tool 执行卡 → text。文本用 streamdown 渲染 Markdown，**正文字体是宋体衬线**：

```tsx
// packages/studio/src/components/ai-elements/message.tsx:328-336
<MessageResponse> = memo(...) => (
  <Streamdown
    className={cn(
      "size-full text-[17px] leading-[1.72] font-['SimSun','Songti_SC','STSong',serif] [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&>p+p]:mt-4",
```

**输入区**（ChatPage.tsx:1058-1279）——一个自包含的“卡片式复合输入条”：
- 外壳：`rounded-xl bg-secondary/30`，内部三段：顶部（选中 skill/附件 chips，有内容时出现）→ 中部主行（+ 号、📎 附件、textarea、圆形发送按钮）→ 底部一行（模型选择下拉，`border-t` 分隔）。
- textarea：`rows={1}`，随内容自动增高到 **200px 上限**（ChatPage.tsx:576-581：`el.style.height = "auto"; el.style.height = ${Math.min(el.scrollHeight, 200)}px`），类名含 `resize-none max-h-[200px]`。
- 有**独立圆形发送按钮**（ArrowUp 图标，`w-8 h-8 rounded-lg bg-primary`，ChatPage.tsx:1173-1183），在 loading 且输入为空时图标切换为 Square（停止），点击即 `abortSession`。
- 键盘处理（ChatPage.tsx:1167）：

```tsx
// packages/studio/src/pages/ChatPage.tsx:1167
onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void onSend(input); } }}
```

- **Enter 发送，Shift+Enter 换行。注意：ChatPage 自己的 textarea 没有做 IME 组合态处理**；inkos 的通用组件 `PromptInputTextarea` 做了，但 ChatPage 没用它：

```tsx
// packages/studio/src/components/ai-elements/prompt-input.tsx:965-996
const [isComposing, setIsComposing] = useState(false);
...
if (e.key === "Enter") {
  if (isComposing || e.nativeEvent.isComposing) {
    return;
  }
  if (e.shiftKey) {
    return;
  }
  e.preventDefault();
  ...
  form?.requestSubmit();
}
```

### 3. 「提议建书」和「方案卡」的呈现方式 —— 关键结论

**不是浮层/弹窗/模态。是嵌在聊天流里、随消息滚动的内联卡片。**

inkos 的机制：模型的系统提示词要求它**不要用普通文字写确认卡**，而是调用 `propose_action` 工具（含 action / instruction / shortRun payload）。前端把 tool 执行渲染成一张卡片（`ToolExecutionSteps.tsx` 的 `ProposedActionPreview`），用户点「继续执行 / 取消」。

```tsx
// packages/studio/src/components/chat/ToolExecutionSteps.tsx:512-560
const resolution = resolvedProposals[details.execId];
const locked = resolution !== undefined;
return (
  <div className="mx-3 mb-3 mt-1 rounded-xl border border-primary/25 bg-primary/5 px-4 py-3.5">
    <div className="text-[17px] leading-6 font-semibold text-foreground">{details.title ?? tr("确认执行", "Confirm action")}</div>
    {details.summary && (
      <div className="mt-1.5 whitespace-pre-wrap break-words text-[15px] leading-7 text-muted-foreground">{details.summary}</div>
    )}
    <div className="mt-2.5 whitespace-pre-wrap break-words rounded-lg bg-background/70 px-3 py-2.5 text-[15px] leading-7 text-muted-foreground">
      {details.instruction}
    </div>
    ...
    <button ... data-testid="confirm-action" onClick={() => onProposedAction?.(details)}
      disabled={!onProposedAction || streaming || locked} ...>
      {streaming ? tr("执行中…", "Running…") : details.targetRoute ? tr("打开入口", "Open entry") : tr("继续执行", "Continue")}
    </button>
    <button ... onClick={() => onRejectProposedAction?.(details)} ...>{tr("取消", "Cancel")}</button>
```

卡片特性：
- 属于 stream 里的 tool part，**永久留在会话历史中**，可折叠容器 `<Collapsible>`（`PipelineExecution`，ToolExecutionSteps.tsx:687-764）内，标题行显示工具名 + 耗时 + 状态徽章。
- **一次性锁**：确认/取消后 `markProposalResolved(execId, ...)`，卡片锁定，按钮替换为「已执行 / 已取消」静态文案（ToolExecutionSteps.tsx:505-537 注释写明 "one-shot: once confirmed or rejected the card locks so the production action can't be re-fired"）。
- 确认按钮在 streaming 中显示「执行中…」并 disabled。

**「方案卡」内容 instruction 字段承载**（后端系统提示定义了必须包含哪些要素）：

```text
// packages/core/src/agent/agent-system-prompt.ts:191-196 (buildShortPrompt)
你是 InkOS Short 助手。当前入口只负责把独立短篇或短篇封面需求聊清楚，然后让用户确认。

可用工具：propose_action、ingest_material、retrieve_material。短篇成品用 action=short_run；只做封面用 action=generate_cover。用户上传或提供参考资料时先归档/召回相关资料，但不要直接生成成品。核心冲突和主角压力明确时必须调用 propose_action，不要用普通文字手写确认卡。用户说“先确认/确认后再写”时，propose_action 就是确认卡，仍然调用它，不要先用普通文字整理一遍再等用户二次确认。
instruction 必须自包含：题材方向、标题/暂定名、主角压力、核心冲突、情绪回报、封面视觉方向或目标短篇路径。生成完整短篇时同时填 shortRun：direction、chapters、charsPerChapter、cover；charsPerChapter 只能是每章 900-1200 字，不是整篇总字数。
标题或封面视觉缺失时可以自行拟一个工作版本写进 instruction；只有题材、主角压力或核心冲突太空时才问一个关键问题。不要创建长篇 books/ 项目，不要启动互动世界，不要把短篇转成长篇建书。
```

（agent-system-prompt.ts:199-205 为对应英文版。）

确认后（ChatPage.tsx:765-801 `handleProposedAction`）：先 `markProposalResolved` 锁卡，然后把 `instruction` **作为一条新消息发给同一个或新 short session**，后端 short 会话收到 `confirmedIntent="short_run"` 后的提示词变成"唯一动作：立即调用 short_fiction_run"（agent-system-prompt.ts:159-174）。

**短篇方案（大纲）本身的呈现**：`short_fiction_run` 工具跑完 outline→draft→review→package 流水线，前端在 tool 卡内展示结果卡 `ShortFictionResultPreview`（封面图内嵌到卡片：ToolExecutionSteps.tsx:289-320），展开后可见各阶段 stage 进度（思考中 Xs / 字数，ToolExecutionSteps.tsx:67-75）和实时日志。真正的"方案卡"（大纲全文）不弹窗，是流水线产物落盘 `shorts/` 下的 Markdown，正文卡内可预览。

### 4. 对话轮次与发送锁

- **严格交替**：store 层有硬锁——`sendMessage` 入口（`packages/studio/src/store/chat/slices/message/action.ts:386-390`）：

```ts
sendMessage: async (sessionId, text, options?: SendMessageOptions) => {
  const trimmed = text.trim();
  ...
  if ((!trimmed && attachments.length === 0) || !session || session.isStreaming) return;
```

  session `isStreaming` 为 true 时**直接丢弃新发送**（不是禁用输入框——textarea 始终可编辑，可先打字）。
- 追问策略：inkos 规定一次只问**一个**关键问题；propose_action 必须在"核心冲突和主角压力明确"时被调用，不闲聊。
- 但注意 ChatPage.tsx:708-734 `onSend`：**发送时如果仍在 loading，会先 abort 当前流再发送**（`if (loading) { await abortSession(activeSessionId); }`）——即用户可以通过再按一次发送来打断/重置模型回复，这相当于「发送按钮在流式期间是停止键」。层的锁和 this 行为并存：action.ts 层面的检查 `session.isStreaming` 使得 sendMessage 期间再 send 会 return……实际两条路径都存在：输入为空时按钮变停止、有内容时 abort 再发。

---

## 二、文风（文笔）设定与抽取

### 1. 全部实现位置

| 文件 | 内容 |
|---|---|
| `packages/core/src/agents/style-analyzer.ts` | 纯统计指纹抽取（不用 LLM） |
| `packages/core/src/models/style-profile.ts` | StyleProfile 类型定义 |
| `packages/core/src/pipeline/runner.ts:2376-2547` | `generateStyleGuide()`：LLM 定性分析 + 统计兜底；`initImitationBook()`（:1055-1065）；`buildDeterministicStyleGuide()` |
| `packages/core/src/agents/writer-prompts.ts:761-777` | 文风指南 / 文风指纹注入写作提示词 |
| `packages/studio/src/pages/StyleManager.tsx` | 文风分析前端页（粘文本 → 分析 → 导入到书） |
| `packages/studio/src/pages/ImportManager.tsx`（imitation Tab） | 仿写建书入口 |
| `packages/studio/src/api/server.ts:5553-5583, 5756-5799` | `/api/v1/style/analyze`、`/books/:id/style/import`、`/imitation/init` |
| `packages/core/src/agent/agent-tools.ts:122-133, 279-296` | `propose_action` 的 `style_imitation` action（双路由到 `import:imitation` 或 `style` 页） |
| `packages/core/src/prompts/short-fiction.ts` | 短篇正文提示（含写作手法提醒，见后） |

### 2. 抽取维度与提示词原文 —— 核心结论

inkos 的文风抽取**核心是"写作的文笔/风格"**——叙事声音、对话、场景描写、节奏、用词、情绪表达这些**笔触特征**，完全不涉及题材/情节/方案内容。提示词完整原文如下（两份都要：定性 LLM 分析 + 统计指纹）。

**主提示词（中文，LLM 定性分析；`packages/core/src/pipeline/runner.ts:2435-2462`）：**

```text
你是一位文学风格分析专家。分析参考文本的写作风格，提取可供模仿的定性特征。

输出格式（Markdown）：
## 叙事声音与语气
（冷峻/热烈/讽刺/温情/...，附1-2个原文例句）

## 对话风格
（角色说话的共性特征：句子长短、口头禅倾向、方言痕迹、对话节奏）

## 场景描写特征
（五感偏好、意象选择、描写密度、环境与情绪的关联方式）

## 转折与衔接手法
（场景如何切换、时间跳跃的处理方式、段落间的过渡特征）

## 节奏特征
（长短句分布、段落长度偏好、高潮/舒缓的交替方式）

## 词汇偏好
（高频特色用词、比喻/修辞倾向、口语化程度）

## 情绪表达方式
（直白抒情 vs 动作外化、内心独白的频率和风格）

## 独特习惯
（任何值得模仿的个人写作习惯）

分析必须基于原文实际特征，不要泛泛而谈。每个部分用1-2个原文例句佐证。
```

**英文版同文件（runner.ts:2407-2434）：**

```text
You are a literary style analyst. Analyze the writing style of the reference text and extract qualitative, imitable features.

Output format (Markdown):
## Narrative Voice & Tone
(detached / fervent / ironic / warm / ..., with 1-2 quoted lines from the text)

## Dialogue Style
(shared traits in how characters speak: sentence length, verbal tics, dialect markers, dialogue rhythm)

## Scene Description
(sensory preferences, choice of imagery, description density, how setting ties to emotion)

## Transitions & Connective Technique
(how scenes switch, how time jumps are handled, paragraph-to-paragraph transitions)

## Pacing
(distribution of long vs short sentences, paragraph-length preference, how climaxes and lulls alternate)

## Diction
(signature high-frequency word choices, figurative/rhetorical tendencies, degree of colloquialism)

## Emotional Expression
(direct lyricism vs externalized action, frequency and style of interior monologue)

## Distinctive Habits
(any personal writing habits worth imitating)

Base the analysis on the text's actual features, not generalities. Support each section with 1-2 quoted lines from the original.
```

**用户 prompt 仅一行**（runner.ts:2463-2465）：`分析以下参考文本的写作风格：\n\n${sample}` / `Analyze the writing style of the following reference text:\n\n${sample}`，参数 `temperature: 0.3`。

**同时产出统计指纹。数据结构定义原文（`packages/core/src/models/style-profile.ts:1-16`，全文）：**

```ts
/** Style fingerprint profile extracted from reference text. */
export interface StyleProfile {
  readonly avgSentenceLength: number;
  readonly sentenceLengthStdDev: number;
  readonly avgParagraphLength: number;
  readonly paragraphLengthRange: {
    readonly min: number;
    readonly max: number;
  };
  readonly vocabularyDiversity: number; // TTR (Type-Token Ratio)
  readonly topPatterns: ReadonlyArray<string>;
  readonly rhetoricalFeatures: ReadonlyArray<string>;
  readonly sourceName?: string;
  readonly analyzedAt?: string;
}
```

统计侧 extract 涉及的固定修辞模式表（style-analyzer.ts:9-24，节选）：

```ts
// Common rhetorical patterns in Chinese fiction
const RHETORICAL_PATTERNS = [
  { name: "比喻(像/如/仿佛)", regex: /[像如仿佛似](?:是|同|一般|一样)/g },
  { name: "排比", regex: /[，。；]([^，。；]{2,6})[，。；]\1/g },
  { name: "反问", regex: /难道|怎么可能|岂不是|何尝不/g },
  { name: "夸张", regex: /天崩地裂|惊天动地|翻天覆地|震耳欲聋/g },
  { name: "拟人", regex: /[风雨雪月花树草石](?:在|像|仿佛).*?(?:笑|哭|叹|呻|吟|怒|舞)/g },
  { name: "短句节奏", regex: /[。！？][^。！？]{1,8}[。！？]/g },
];
```

（英文表 EN_RHETORICAL_PATTERNS 见 style-analyzer.ts:19-24）

### 3. 输入与后处理流程

`generateStyleGuide`（runner.ts:2376-2492）：

1. **输入是用户粘贴的参考文本全文**（一次性整段，不开多窗口样本），`style-analyzer.ts` 里先做 2 次预处理：按 `[。！？\n]` 切句、按 `\n\s*\n` 切段（style-analyzer.ts:37-45），中文用字符计长、英文用词计长（:48-49）。
2. `analyzeStyle()` 生成统计 profile，**落盘 `style_profile.json`**（runner.ts:2392-2393）。中间 metric 取整/缩放：句长一位小数、TTR 三位小数（style-analyzer.ts:105-115）。高频句首模式取 top5 且要求出现 ≥3 次（:87-93）；修辞特征要求命中 ≥2 处才列出（:98-103）。
3. **统计→定性的分界线是 500 字**（runner.ts:2396-2403）：
   - < 500 字 → **不调 LLM**，直接用 `buildDeterministicStyleGuide(profile,...)` 生成一版手写的统计型指南（文案见 runner.ts:2528-2546，含 "这是一份轻量文风指纹，不是完整仿写圣经" "后续写作优先参考句长、段落长度、节奏波动和可见修辞"），顶部带原因说明。
   - ≥ 500 字 → LLM 定性分析；若内容为空或异常，兜底回统计版（runner.ts:2470-2485）。
4. 定性指南拼上一个通用"写作方法论"节（`buildWritingMethodologySection(lang)`），落盘 **`story/style_guide.md`**（runner.ts:2488-2491）。
5. 分析前后端无校验、无截断：完整 sample 一次 submit。

### 4. 文风在生成时的注入位置

`packages/core/src/agents/writer-prompts.ts:761-777`：

```ts
// Style guide
function buildStyleGuide(styleGuide: string): string {
  if (!styleGuide || styleGuide === "(文件尚未创建)") return "";
  return `## 文风指南\n\n${styleGuide}`;
}

// Style fingerprint (Phase 9: C3)
function buildStyleFingerprint(fingerprint?: string): string {
  if (!fingerprint) return "";
  return `## 文风指纹（模仿目标）

以下是从参考文本中提取的写作风格特征。你的输出必须尽量贴合这些特征：

${fingerprint}`;
}
```

两个 section 被 writer 的 system prompt 显式组装进提示词（writer-prompts.ts:25-93 位置的双次引用 `buildStyleGuide(styleGuide)` 和 `buildStyleFingerprint(styleFingerprint)`，即 writer 与 论/修/打磨多阶段都用）。

**短篇正文不注入 style_guide（**`packages/core/src/prompts/short-fiction.ts`**里 writer prompt 没有任何 reference `reference` 进正文 prompt，只在**方案大纲（outline）提示**里有 `## 可选参考文本`** 一段（short-fiction.ts:106），2 个 outline 调用）。短篇的"文笔"约束是固定的 `buildShortFictionCraftPrompt`（short-fiction.ts:540-568，写作手法提醒：盐溶于汤、Show don't tell、**明喻节制每场景最多1处**、反注水、高潮即场景、回报要有铺垫、配角要有动机、日常细节要变成饵、移动端优先段落短）。完整内文见 `short-fiction.ts:556-568`（中文）/ `:542-554`。

---

## 三、对 Myink 的直接可用结论

1. **短篇页面 = 同一个聊天页**，只换空态提示语；不存在专门的短篇 UI 分支。
2. **方案卡不是弹窗，是流内卡片**：`propose_action` 工具 → 嵌在助手消息下方的一块带左侧主色边框的卡片，永久留在会话里，确认后锁定不可重复用。没有遮罩/动画/居中模态。
3. **确认后切语义模式**：确认卡触发的是"进入短篇 session，一拍脑门直接 short_fiction_run 单 API 全量生成"这种一次性管线，不是逐章逐步对话。
4. **文风抽取的正解是 LLM 分析"文笔"8 个维度**（叙事声音/对话/场景描写/衔接/节奏/词汇/情绪表达/独特习惯），要求每个维度给 1-2 处原文例句佐证，且用 <500 字的阈值决定是否需要调 LLM（短文直接用统计指纹），全量 sample 一次喂给模型取输出。
5. **_statistical fingerprint（style_profile.json）与 qualitative style_guide.md 双轨并行**，前者兜底、并作为后用 fallback。
6. Markdown 正文用宋体渲染、17px/1.72 行距，是聊天页面可读性的定调细节之一。
