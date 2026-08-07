# Ai Ink 数据契约（JSON Schema）— Phase 0

> **用途**：定义核心对象的 JSON Schema，作为 Pydantic 强校验（plan.md §3 已确认决策）的蓝本。保证 **extract 抽取输出 / 校验器读取 / 数据库存储** 三方字段一致，杜绝阶段 1 编码期返工。
>
> **版本**：v0.1（2026-08-05，Phase 0 草案）。落地为 Pydantic model 时以本文件为准，字段增删需同步本文档 + plan.md §6.4 / §11。

## 约定

- 所有业务表带 `project_id`（多租户双键硬隔离，plan.md §14.1）；
- 所有事实 / 事件 / 关系 / 状态带 `source_chapter` + `confidence`（证据链可追溯，plan.md §8.7）；
- 时间窗字段：`valid_from` / `valid_to`（`null` = 当前有效），支撑状态翻转与"已失效"判定；
- 枚举字段（`field`、`conflict_type`、`severity`、`status` 等）与 plan.md §6.4 / §7 / §8 一致。

---

## 1. CharacterState — 人物状态台账一行（追加式）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "CharacterState",
  "type": "object",
  "required": ["project_id", "character_id", "chapter_seq", "field", "new_value", "source_chapter", "confidence"],
  "properties": {
    "id":              { "type": "string", "format": "uuid" },
    "project_id":      { "type": "string", "format": "uuid" },
    "character_id":    { "type": "string", "format": "uuid" },
    "chapter_seq":     { "type": "integer", "minimum": 1 },
    "field":           { "type": "string", "enum": ["location","injury","realm","power","item","knowledge","goal","identity","alive"] },
    "old_value":       { "type": "string" },
    "new_value":       { "type": "string" },
    "source_chapter":  { "type": "integer", "minimum": 1 },
    "confidence":      { "type": "number", "minimum": 0, "maximum": 1 },
    "valid_from":      { "type": "integer", "minimum": 1 },
    "valid_to":        { "type": ["integer","null"], "minimum": 1 }
  }
}
```

- **追加式，只追加不覆盖**（plan.md §7.7）：当前状态 = 按 `chapter_seq` 最近一条有效记录（查询时物化）；
- `alive` 作为独立字段，死亡 / 复活显式记录，防"死而复生"类错误。

## 2. Character — 人物静态基底（长期事实）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Character",
  "type": "object",
  "required": ["project_id", "name", "realm_cap"],
  "properties": {
    "project_id":     { "type": "string", "format": "uuid" },
    "name":           { "type": "string" },
    "aliases":        { "type": "array", "items": { "type": "string" } },
    "race":           { "type": "string" },
    "origin":         { "type": "string", "description": "出身" },
    "realm_cap":      { "type": "string", "description": "境界上限（战力硬约束）" },
    "personality":    { "type": "string", "description": "性格基调/目标（人设漂移审计基线，plan.md §8.6）" },
    "base_attrs":     { "type": "object", "description": "JSONB 基础属性" },
    "version":        { "type": "integer", "description": "乐观版本号（plan.md §7.6）" }
  }
}
```

- 只存**不易变**信息；易变状态一律进 `character_states`（plan.md §7.7）。

## 3. ChapterPlan — 章节计划（规划 agent 输出）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ChapterPlan",
  "type": "object",
  "required": ["goals", "scenes", "characters", "expected_events", "hard_constraints"],
  "properties": {
    "project_id":      { "type": "string", "format": "uuid" },
    "chapter_seq":     { "type": "integer", "minimum": 1 },
    "goals":           { "type": "array", "items": { "type": "string" }, "description": "推进主线/支线" },
    "scenes":          { "type": "array", "items": { "$ref": "#/definitions/Scene" } },
    "characters":      { "type": "array", "items": { "$ref": "#/definitions/CharacterPresence" } },
    "hooks_to_plant":  { "type": "array", "items": { "type": "string" }, "description": "本章要种的伏笔" },
    "hooks_to_resolve":{ "type": "array", "items": { "type": "string" }, "description": "须命中池中开放伏笔（plan.md §7.9）" },
    "expected_events": { "type": "array", "items": { "type": "string" }, "description": "预期事件（大纲-正文偏差比对输入，plan.md §8.6）" },
    "hard_constraints":{ "type": "array", "items": { "type": "string" }, "description": "本章必须遵守的硬约束" }
  },
  "definitions": {
    "Scene": {
      "type": "object",
      "required": ["location_id", "participants", "goal"],
      "properties": {
        "location_id":   { "type": "string", "description": "地点名（规划产物是 LLM 直接输出，只认识名字不持库内 id；id 归一化发生在落库候选 §7.5）" },
        "participants":  { "type": "array", "items": { "type": "string" }, "description": "人物名列表" },
        "goal":          { "type": "string" },
        "time":          { "type": "string", "description": "场景时间点（多线对齐用）" }
      }
    },
    "CharacterPresence": {
      "type": "object",
      "required": ["character_id", "expected_state"],
      "properties": {
        "character_id":   { "type": "string", "description": "人物名（非 UUID，同 Scene.location_id 理由）" },
        "expected_state": { "type": "object", "description": "从状态台账取的要求状态（位置/伤势/境界）" }
      }
    }
  }
}
```

## 4. Event — 剧情事件（中期记忆）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Event",
  "type": "object",
  "required": ["project_id", "summary", "participants", "source_chapter", "confidence"],
  "properties": {
    "id":              { "type": "string", "format": "uuid" },
    "project_id":      { "type": "string", "format": "uuid" },
    "summary":         { "type": "string" },
    "participants":    { "type": "array", "items": { "type": "string", "format": "uuid" }, "description": "必须归一为 canonical id（plan.md §7.5）" },
    "location_id":     { "type": "string", "format": "uuid" },
    "timeline":        { "type": "string", "description": "剧情内时间（相对/绝对）" },
    "related_threads": { "type": "array", "items": { "type": "string", "format": "uuid" }, "description": "关联剧情线" },
    "source_chapter":  { "type": "integer", "minimum": 1 },
    "confidence":      { "type": "number", "minimum": 0, "maximum": 1 },
    "promoted_to_fact":{ "type": "boolean", "default": false, "description": "事件→事实升格（plan.md §7.3）" },
    "version":         { "type": "integer" }
  }
}
```

## 5. Fact — 长期事实

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Fact",
  "type": "object",
  "required": ["project_id", "content", "source_chapter", "confidence"],
  "properties": {
    "id":              { "type": "string", "format": "uuid" },
    "project_id":      { "type": "string", "format": "uuid" },
    "content":         { "type": "string" },
    "category":        { "type": "string", "description": "世界观/身份/归属/关系/规则" },
    "is_hard":         { "type": "boolean", "description": "是否硬约束（恒在 Top-K，plan.md §7.2）" },
    "source_chapter":  { "type": "integer", "minimum": 1 },
    "confidence":      { "type": "number", "minimum": 0, "maximum": 1 },
    "confirm_status":  { "type": "string", "enum": ["pending","confirmed","rejected","expired"] },
    "valid_from":      { "type": "integer", "minimum": 1 },
    "valid_to":        { "type": ["integer","null"], "minimum": 1 },
    "version":         { "type": "integer" }
  }
}
```

## 6. Relation — 人物/势力关系（带时间窗）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Relation",
  "type": "object",
  "required": ["project_id", "source_id", "relation_type", "target_id", "source_chapter", "confidence"],
  "properties": {
    "id":             { "type": "string", "format": "uuid" },
    "project_id":     { "type": "string", "format": "uuid" },
    "source_id":      { "type": "string", "format": "uuid" },
    "relation_type":  { "type": "string", "enum": ["hostile","ally","master_student","located_in","owns","defeated_by","knows","promises","happened_at"] },
    "target_id":      { "type": "string", "format": "uuid" },
    "properties":     { "type": "object", "description": "强度/条件" },
    "confidence":     { "type": "number", "minimum": 0, "maximum": 1 },
    "source_chapter": { "type": "integer", "minimum": 1 },
    "version":        { "type": "integer" },
    "valid_from":     { "type": "integer", "minimum": 1 },
    "valid_to":       { "type": ["integer","null"], "minimum": 1 }
  }
}
```

- 当前关系 = 最新一条 `valid_to IS NULL` 的记录（plan.md §7.8）；
- 敌对/盟友为双向语义，写入时成对落库或查询时双向检查（plan.md §9.3）。

## 7. Foreshadow — 伏笔（状态机）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Foreshadow",
  "type": "object",
  "required": ["project_id", "description", "status", "planted_chapter", "trigger", "related_entities"],
  "properties": {
    "id":               { "type": "string", "format": "uuid" },
    "project_id":       { "type": "string", "format": "uuid" },
    "description":      { "type": "string" },
    "status":           { "type": "string", "enum": ["planted","developing","resolved","dropped"] },
    "planted_chapter":  { "type": "integer", "minimum": 1 },
    "resolved_chapter": { "type": ["integer","null"], "minimum": 1 },
    "trigger":          { "type": "object", "description": "回收条件（结构化）：触发者 + 动作（获得/知道/遭遇）+ 对象（plan.md §7.9）" },
    "related_entities": { "type": "array", "items": { "type": "string", "format": "uuid" } },
    "last_touched":     { "type": "integer", "minimum": 1, "description": "最近推进章节（回收压力计算）" }
  }
}
```

## 8. PlotThread — 剧情线

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PlotThread",
  "type": "object",
  "required": ["project_id", "name", "kind", "status", "priority"],
  "properties": {
    "id":              { "type": "string", "format": "uuid" },
    "project_id":      { "type": "string", "format": "uuid" },
    "name":            { "type": "string" },
    "kind":            { "type": "string", "enum": ["main","side"] },
    "status":          { "type": "string", "enum": ["active","stalled","closed"] },
    "priority":        { "type": "integer", "minimum": 1, "description": "线程债务治理，plan.md §8.6" },
    "progress":        { "type": "string" },
    "participants":    { "type": "array", "items": { "type": "string", "format": "uuid" } },
    "last_progress_chapter": { "type": "integer", "minimum": 1 },
    "open_duration":   { "type": "integer", "description": "开放未推进时长（章节数）" }
  }
}
```

## 9. Finding — 校验发现（L1/L2 统一）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Finding",
  "type": "object",
  "required": ["conflict_key", "conflict_type", "severity", "evidence", "suggestion"],
  "properties": {
    "finding_id":    { "type": "string" },
    "conflict_key":  { "type": "string", "description": "hash(类型+实体+位置)，跨修订轮稳定（plan.md §6.4）" },
    "conflict_type": { "type": "string", "enum": ["faction","power","timeline","location","character","character_state","relation","foreshadow","item_rule","plotline","persona","style"] },
    "severity":      { "type": "string", "enum": ["critical","major","minor","hint"] },
    "scope":         { "type": "string", "enum": ["local","structural"], "description": "冲突作用域，修订分级（plan.md §6.5）" },
    "source":        { "type": "string", "enum": ["L1","L2"], "description": "L1 确定性 / L2 语义" },
    "evidence":      { "type": "array", "items": { "type": "object", "properties": { "chapter": { "type": "integer" }, "quote": { "type": "string" } }, "required": ["chapter","quote"] } },
    "confidence":    { "type": "number", "minimum": 0, "maximum": 1, "description": "仅 L2 需要" },
    "suggestion":    { "type": "string" }
  }
}
```

> **新增冲突类型**（相对 plan.md §8.4 扩展）：`plotline`（剧情线停滞/线程债务）、`persona`（人设漂移）、`style`（文风/AI 味/桥段重复）——对应 §8.6 长线一致性治理。

## 10. MutationCandidate — 记忆候选（待确认池）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "MutationCandidate",
  "type": "object",
  "required": ["kind", "project_id", "source_chapter", "payload"],
  "properties": {
    "id":            { "type": "string", "format": "uuid" },
    "kind":          { "type": "string", "enum": ["event","fact","character_state","relation_change","foreshadow","chapter_summary"] },
    "project_id":    { "type": "string", "format": "uuid" },
    "source_chapter":{ "type": "integer", "minimum": 1 },
    "payload":       { "type": "object", "description": "对应 kind 的对象体（Event/Fact/CharacterState/Relation/Foreshadow/摘要）" },
    "confidence":    { "type": "number", "minimum": 0, "maximum": 1 },
    "status":        { "type": "string", "enum": ["pending","confirmed","rejected"], "default": "pending" }
  }
}
```

- 存 **DB 表**（`memory_candidates`），Redis 只做短期标记（plan.md §5.3 / §7.3）。

## 11. ValidationReport — 校验报告

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ValidationReport",
  "type": "object",
  "required": ["project_id", "chapter_seq", "findings", "summary"],
  "properties": {
    "project_id":  { "type": "string", "format": "uuid" },
    "chapter_seq": { "type": "integer", "minimum": 1 },
    "findings":    { "type": "array", "items": { "$ref": "finding.schema.json" } },
    "summary":     { "type": "object", "properties": {
                       "total": { "type": "integer" },
                       "critical": { "type": "integer" },
                       "resolved": { "type": "integer" }
                    } }
  }
}
```

## 12. RetrievedContext — 召回上下文（recall 节点输出）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "RetrievedContext",
  "type": "object",
  "required": ["long_term_facts", "mid_term_events", "short_context", "entity_snapshots", "token_usage"],
  "properties": {
    "long_term_facts":  { "type": "array", "items": { "type": "object", "properties": { "fact_id": { "type": "string" }, "source_chapter": { "type": "integer" } } } },
    "mid_term_events":  { "type": "array", "items": { "type": "object", "properties": { "event_id": { "type": "string" }, "chapter": { "type": "integer" }, "confidence": { "type": "number" } } } },
    "short_context":    { "type": "array", "items": { "type": "object" }, "description": "上一章摘要 + 上一章候选事件 + 本章开头 + 最近场景（plan.md §7.1）" },
    "entity_snapshots": { "type": "array", "items": { "type": "object" }, "description": "人物/势力/地点当前状态快照（台账最新）" },
    "token_usage":      { "type": "integer" }
  }
}
```

---

## 与实现的关系

- 阶段 1 用 Pydantic `BaseModel` 直接映射上表（`Field` 约束与 Schema 一致），LangGraph 节点间传结构化对象（plan.md §6.4 `ChapterState` TypedDict）；
- Schema 是 extract / plan_chapter / validate 三方输出的唯一契约：**坏数据拒绝但不崩**（plan.md §3 已确认决策）；
- 新增字段（如 `plotline` / `persona` / `style` 冲突类型）已同步 plan.md §8.6 / §8.4，后续一致演进。
