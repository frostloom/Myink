import type {
  CapturedData,
  SnapshotFinding,
  SnapshotPayload,
  SnapshotSection,
} from './adminApi'

/** 快照详情的子视图。只列出这条快照真有内容的那些，不做空标签页。 */
export type SnapshotSubView = 'prompt' | 'recall' | 'hardRules' | 'style' | 'findings' | 'patch'

export const SUB_VIEW_LABELS: Record<SnapshotSubView, string> = {
  prompt: '提示词',
  recall: '召回文本块',
  hardRules: '硬规则',
  style: '文风',
  findings: '校验发现',
  patch: '补丁',
}

/** 硬约束与文风在渲染后的提示词里各是一个【…】节，靠标签名定位（同 snapshot.py 的口径）。 */
export const HARD_RULE_SECTION = '世界观硬约束'
export const STYLE_SECTION_PREFIX = '文风要求'
/** 硬约束的台账侧来源：带 is_hard 的长期事实（建书时配置的带 source）。 */
export const HARD_FACT_GROUP = 'long_term_facts'

const RECALL_LABELS: Record<string, string> = {
  long_term_facts: '长期事实与硬约束',
  mid_term_events: '中期事件',
  reflexions: '写作经验',
  plot_threads: '故事线',
  open_foreshadows: '开放伏笔',
  recent_openings: '近期章头',
  setting_snapshots: '设定快照',
  entity_snapshots: '实体快照',
  short_context: '近期上下文',
}

function recallLabel(key: string): string {
  return RECALL_LABELS[key] ?? key
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function asRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item): item is Record<string, unknown> => item !== null) : []
}

/** 读出快照的原始输入；`_capture` 是留存标记，不属于内容。 */
export function snapshotPayload(captured: CapturedData | null | undefined): SnapshotPayload {
  const data = asRecord(captured?.data)
  if (!data) return {}
  const result = { ...data }
  delete result._capture
  return result as SnapshotPayload
}

function isSection(value: unknown): value is SnapshotSection {
  const record = asRecord(value)
  return record !== null && (record.policy === 'full' || record.policy === 'hash')
}

export function promptSections(payload: SnapshotPayload): SnapshotSection[] {
  const sections = asRecord(payload.prompt)?.sections
  return Array.isArray(sections) ? sections.filter(isSection) : []
}

export function styleSection(payload: SnapshotPayload): SnapshotSection | null {
  return promptSections(payload).find((item) => (item.name ?? '').startsWith(STYLE_SECTION_PREFIX)) ?? null
}

export function hardRuleSection(payload: SnapshotPayload): SnapshotSection | null {
  return promptSections(payload).find((item) => item.name === HARD_RULE_SECTION) ?? null
}

export interface RecallGroup {
  key: string
  label: string
  items: Record<string, unknown>[]
}

export function recallGroups(payload: SnapshotPayload): RecallGroup[] {
  const groups = asRecord(asRecord(payload.recall)?.groups)
  if (!groups) return []
  return Object.entries(groups).map(([key, value]) => ({
    key, label: recallLabel(key), items: asRecords(value),
  }))
}

export function recallStats(payload: SnapshotPayload): Record<string, unknown> {
  return asRecord(asRecord(payload.recall)?.stats) ?? {}
}

/** 这一章生效的硬约束里，台账侧那些标了 is_hard 的事实。 */
export function hardRuleFacts(payload: SnapshotPayload): Record<string, unknown>[] {
  return (recallGroups(payload).find((group) => group.key === HARD_FACT_GROUP)?.items ?? [])
    .filter((item) => item.is_hard === true)
}

export function findings(payload: SnapshotPayload): SnapshotFinding[] {
  return asRecords(payload.findings) as SnapshotFinding[]
}

export function appliedSpans(payload: SnapshotPayload): Array<{ target: string; replacement: string }> {
  return asRecords(payload.applied_spans)
    .filter((span) => typeof span.target === 'string' && typeof span.replacement === 'string')
    .map((span) => ({ target: span.target as string, replacement: span.replacement as string }))
}

export function availableSubViews(payload: SnapshotPayload): SnapshotSubView[] {
  const views: SnapshotSubView[] = []
  if (promptSections(payload).length > 0) views.push('prompt')
  if (recallGroups(payload).length > 0) views.push('recall')
  if (hardRuleSection(payload) || hardRuleFacts(payload).length > 0) views.push('hardRules')
  if (styleSection(payload)) views.push('style')
  if (findings(payload).length > 0) views.push('findings')
  if (appliedSpans(payload).length > 0) views.push('patch')
  return views
}

export function severityClass(severity: string | null | undefined): string {
  if (severity === 'critical') return 'badge badge-error'
  if (severity === 'major') return 'badge badge-warning'
  return 'badge'
}

const FIELD_LABELS: Record<string, string> = {
  kind: '类型', name: '名称', fact_id: '事实', event_id: '事件', entity_id: '实体',
  character_id: '人物', thread_id: '故事线', foreshadow_id: '伏笔', chapter: '章',
  chapter_seq: '章', chapter_count: '章数', chapter_id: '章节 id', seq: '章序号',
  source_chapter: '源自第几章', first_seen_chapter: '首见章',
  confidence: '置信', status: '状态', lesson_type: '经验类型', category: '类别',
  is_hard: '硬约束', source: '来源',
  summary: '摘要', description: '描述', content: '内容', excerpt: '摘录',
  title: '标题', premise: '前提', storyline: '故事线', objective: '目标',
  volumes: '分卷', volume_seq: '卷序号', outline: '大纲',
  participants: '参与人物', confirm_status: '确认状态',
  planted_chapter: '埋设章', resolved_chapter: '回收章',
  trigger: '触发条件', actor: '人物', action: '动作', object: '对象',
  race: '种族', origin: '出身', realm_cap: '境界上限', personality: '性格',
  base_attrs: '基础设定', identity: '身份', role: '定位', importance: '作用',
  world_rules: '世界规则', hard_constraints: '硬约束', style_profile: '文风档案',
  genre_pack: '题材包', skill_pack: '技能包', settings: '设定',
  source_id: '题材', source_name: '题材名', secondary_id: '辅题材',
  secondary_name: '辅题材名', selling_point: '卖点', subgenres: '子题材',
  taboos: '禁忌', pacing: '节奏', satisfaction: '爽点', mechanics: '机制',
  world_hints: '世界提示', hook: '钩子', factions: '势力', locations: '地点',
  user_instruction: '用户指令', mode: '模式', attempt: '第几次',
  bytes: '字节', sha256: '摘要', model_id: '模型', stage: '阶段',
  total: '发现总数', critical: '致命', l2_major: '台账重大', resolved: '已解决',
  vector_hits: '向量腿命中', keyword_hits: '关键词腿命中', fused_total: '融合新增',
  recall_tokens_est: '召回 token（估）', context_tokens_est: '上下文 token（估）',
  share: '召回占比', vector_status: '向量腿状态', keyword_status: '关键词腿状态',
  degrade_reason: '降级原因', hybrid_status: '混合召回状态', recalled_by: '召回来源',
  text: '文本', tail: '结尾', statement: '陈述', state: '状态',
  old_value: '原值', new_value: '新值',
}

export function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key
}

/** 内部标记字段（`_gate_user_id` 之类）不进展示。 */
export function isInternalKey(key: string): boolean {
  return key.startsWith('_')
}


/** 条目里可以直接成对显示的标量字段（摘录单独渲染，不当字段列）。 */
export function scalarPairs(item: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(item)
    .filter(([key, value]) => key !== 'excerpt'
      && (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'))
    .map(([key, value]) => [key, String(value)])
}
