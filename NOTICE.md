# 第三方来源与许可声明

Myink 整体以 **AGPL-3.0** 发布，许可全文见 [LICENSE](LICENSE)。

本文列出本仓库中来自其它开源项目的部分、上游版本与许可。上游提交号是撰写本文件时的版本。

---

## 一、移植的代码

### Narcooo/inkos — AGPL-3.0

上游：<https://github.com/Narcooo/inkos>，提交 `091048383f411eb99948a8764f42b6fd13006f9b`

| 本仓库 | 上游 | 性质 |
| --- | --- | --- |
| `src/myink/providers/think_tag_stripper.py` | `packages/core/src/llm/think-tag-stripper.ts` | TypeScript 到 Python 的移植。三态机器（`detecting` / `inside` / `passthrough`）、`push` / `flush` 接口、"只剥响应起始处的完整 think 块、正文中间的同名标签不动、起始处未闭合的块也不剥"这套判定，均来自上游。本仓库把标签对从 `<think>` 一种扩展到四种，并新增 `isolate_response_body`。 |
| `tests/test_think_tag_stripper.py` | `packages/core/src/__tests__/think-tag-stripper.test.ts` | 用例名逐条对译自上游，顺序一致。 |

改动日期：2026-09。

### 行为对齐（非代码移植）

以下位置实装了与上游相同的规则，代码为本仓库自行编写，注释中标注了来源：

- `src/myink/providers/deepseek.py` —— 思考字段与正文分家；正文只剩思考链时丢弃并重试。
- `src/myink/providers/openai_compatible.py` —— `reasoning_split`；可关闭思考的模型显式关闭。

### 设计参考

- `web/src/pages/NewProjectPage.tsx` —— 一键建书（设定草稿与大纲草稿并行）、AI 起名。
- `docs/SHORT-FORM.md` —— 短篇管道设计，文中引用了上游 `packages/core/src/pipeline/short-fiction-runner.ts` 等路径。

---

## 二、参考的知识库内容

### lingfengQAQ/webnovel-writer — GPL-3.0

上游：<https://github.com/lingfengQAQ/webnovel-writer>，提交 `35ea435c0d3fc0c69d49145cf741a3c478f24629`

**原样收录**：`src/myink/third_party/webnovel-writer/` 下的题材模板与素材表是该仓库文件的逐字副本，
上游 GPL-3.0 全文随附于同目录 `LICENSE`。按 GPL-3.0 第 5 条在此声明来源与日期。

收录范围（78 个文件，约 1.1MB）：

- `templates/genres/` —— 37 个题材模板
- `templates/output/` —— 13 个产出模板（大纲总纲、卷节拍表、卷时间线，设定集的主角卡/女主卡/主角组/反派/世界观/金手指/力量体系，复合题材融合逻辑等）
- `templates/golden-finger-templates.md` —— 金手指模板
- `references/*.md` —— `genre-profiles.md`（13 条数值权重）、`reading-power-taxonomy.md` 等
- `references/{csv,index,outlining,review,shared,taxonomy}/` —— 素材表与索引，含 `桥段套路.csv`、`写作技法.csv`、`人设与关系.csv`、`场景写法.csv`、`金手指与设定.csv`、`爽点与节奏.csv`、`命名规则.csv`、`题材与调性推理.csv`、`裁决规则.csv`

**未收录**：上游的 `agents/`（13 个 agent 提示词）、`skills/`（48 个 skill 定义）、`hooks/`、`evals/`、`dashboard/`。这些是上游自己的编排与面板，与 Myink 的编排重复，未搬入。

**接进生成的方式**：语料不进 DB、不进提示词全文。`read_genre_reference` 工具（`src/myink/workflow/tools.py`，定位与读取在 `src/myink/reference_corpus.py`）让 Writer 按需读——提示词里只放本书题材的文档路径与小节清单（`genre_catalog.reference_hint()`）。

改动日期：2026-09。

**本仓库自写、非取自上游**：

- 六个精调题材的写章附加层（`genre_catalog.py` 的 `_REFINE`）为本仓库自写。其中修仙、规则怪谈、知乎短篇三个题材与上游同名 profile 方向一致；狗血、年代、现实三个上游没有对应条目。
- 37 个题材根包（`genre_catalog.py` 的 `PACKS`、前端镜像 `web/src/lib/genrePacks.ts`）的字段文字为本仓库重写，与上游模板逐字重合的句子数为 0（已核对）。

**参考结构而非转录的来源**（这些不是文件副本）：

- **题材别名** —— `genre_catalog.py` 的 `_ALIASES` 18 条全部取自上游 `references/taxonomy/genre-index.csv` 的 aliases 列（逐条核对，18/18 命中）。
- **主辅题材 7:3** —— 取自上游 `templates/output/复合题材-融合逻辑.md`（"占比建议：7:3"）与 `scripts/data_modules/genre_profile_builder.py`（主辅冲突时优先保证主题材的读者承诺）。落在 `compose_fields()` / `format_prompt()`。
- **番茄榜单接口形状** —— 取数端点（host、路径、`aid`、`side_type` 取值、`data.result[]` 字段名）取自上游 `packages/core/src/agents/radar-source.ts` 的 `FanqieRadarSource`。请求与归一代码为本仓库自写，落在 `src/myink/integrations/fanqie.py`。

**未接进来的部分**：上游 `references/genre-profiles.md` 里那套数值权重（钩子类型、每章爽点密度、微兑现下限、节奏停滞章数）没有接进生成逻辑——该文件自标 "Fallback Only"，声明只用来调建议、不做硬性裁决。文件本身已随语料收录，未被代码读取。

---

## 三、明确非移植

`src/myink/worker/lock.py` 的租约锁为本仓库自研，只借鉴通用的分布式租约锁原则，非外部项目移植。

---

## 许可兼容性

AGPL-3.0 与 GPL-3.0 单向兼容：GPL-3.0 的内容可以并入 AGPL-3.0 的作品，反向不行。所以本仓库用 AGPL-3.0 一个许可即可同时覆盖上述两类上游，无需再叠加 GPL-3.0。

本项目源码仓库：<https://github.com/frostloom/Myink>
