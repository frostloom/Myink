// 待确认候选的纯展示映射（kind → 中文标签 / 徽标色调 / payload 字段渲染）。
// 抽成纯函数便于单测；字段键对齐 Python persist 落库路径（nodes.py _persist_candidates）
// 实际读取的 payload 键，未知键回退「原键名 + 格式化值」，键漂移不崩。
import type { BadgeTone } from '../components/StatusBadge'
import type { CandidateKind } from '../types'

export const CANDIDATE_LABELS: Record<string, string> = {
  event: '事件',
  fact: '事实',
  character_state: '角色状态',
  relation_change: '关系变更',
  foreshadow: '伏笔',
  foreshadow_touch: '伏笔回收',
  chapter_summary: '章节摘要',
  memory_removal: '记忆删除',
  character_card: '新人物卡片',
  new_entity: '新设定实体',
  plotline: '剧情线推进',
}

export function candidateLabel(kind: CandidateKind): string {
  return CANDIDATE_LABELS[kind] ?? kind
}

const CANDIDATE_TONES: Record<string, BadgeTone> = {
  event: 'accent',
  fact: 'hint',
  character_state: 'minor',
  relation_change: 'major',
  foreshadow: 'warning',
  foreshadow_touch: 'warning',
  chapter_summary: 'hint',
  memory_removal: 'error',
  character_card: 'accent',
  new_entity: 'minor',
  plotline: 'accent',
}

export function candidateTone(kind: CandidateKind): BadgeTone {
  return CANDIDATE_TONES[kind] ?? 'hint'
}

/** 各 kind 优先展示的 payload 键（对齐 _persist_candidates 读取；未列出的键兜底追加） */
const KIND_FIELD_ORDER: Record<string, string[]> = {
  event: ['type', 'title', 'summary', 'participants', 'date', 'location'],
  fact: ['content', 'category', 'is_hard', 'evidence'],
  character_state: ['character_id', 'field', 'old_value', 'new_value', 'reason'],
  relation_change: [
    'relation_type', 'source_id', 'target_id', 'change', 'reason', 'valid_from', 'valid_to',
  ],
  foreshadow: ['name', 'description', 'trigger', 'payoff_plan', 'planted_chapter'],
  foreshadow_touch: ['foreshadow_id', 'outcome', 'note'],
  chapter_summary: ['summary'],
  memory_removal: ['memory_type', 'memory_id', 'reason'],
  character_card: ['name', 'identity', 'role', 'personality', 'importance'],
  new_entity: ['entity_type', 'name', 'description'],
  plotline: ['thread_name', 'note'],
}

const FIELD_LABELS: Record<string, string> = {
  summary: '摘要',
  participants: '参与者',
  type: '类型',
  title: '标题',
  content: '内容',
  category: '分类',
  is_hard: '硬约束',
  character_id: '角色',
  field: '字段',
  old_value: '旧值',
  new_value: '新值',
  source_id: '源角色',
  target_id: '目标角色',
  relation_type: '关系',
  change: '变化',
  reason: '理由',
  valid_from: '生效章',
  valid_to: '失效章',
  description: '描述',
  trigger: '触发条件',
  foreshadow_id: '伏笔',
  outcome: '回收结果',
  note: '说明',
  thread_name: '剧情线',
  memory_type: '记忆类型',
  memory_id: '记忆',
  evidence: '证据',
  name: '名称',
  planted_chapter: '埋设章',
  payoff_plan: '回收计划',
  date: '时间',
  location: '地点',
  identity: '身份',
  role: '角色',
  importance: '重要度',
  entity_type: '实体类型',
}

/** 顶层已展示/冗余字段，渲染 payload 时跳过 */
const SKIP_KEYS = new Set(['confidence', 'project_id', 'source_chapter', 'status'])

/** UUID 型 id 展示前 8 位（全 UUID 过长干扰阅读） */
const ID_KEYS = new Set(['character_id', 'source_id', 'target_id', 'memory_id', 'foreshadow_id'])

const FIELD_VALUE_LABELS: Record<string, Record<string, string>> = {
  field: {
    realm: '境界', goal: '目标', injury: '伤势', knowledge: '掌握信息', item: '持有物',
    location: '位置', power: '战力', identity: '身份', alive: '存活状态',
  },
  relation_type: {
    hostile: '敌对', ally: '盟友', master_student: '师徒', located_in: '位于', owns: '持有',
    defeated_by: '被击败于', knows: '相识', promises: '承诺', happened_at: '发生于',
    neutral: '中立', family: '亲属', mentor: '师徒', trusts: '信任', distrusts: '不信任',
    owes: '亏欠', controls: '控制',
  },
  outcome: {
    advanced: '已推进', resolved: '已回收', planted: '已埋设',
    developing: '推进中', dropped: '已放弃',
  },
  entity_type: { item: '物品', skill: '功法/技能', location: '地点' },
  memory_type: {
    event: '事件', events: '事件', fact: '事实', facts: '事实',
    character_state: '角色状态', relation: '人物关系', foreshadow: '伏笔',
  },
}

const CUMULATIVE_STATE_FIELDS = new Set(['item', 'knowledge'])
const STATE_REMOVAL_MARKERS = ['失去', '丢失', '交出', '消耗', '用掉', '不再持有', '移除', '删除']

/** 兼容修复前已经生成的增量候选，让“新值”显示为接受后应得到的完整状态。 */
export function materializeDisplayedState(payload: Record<string, unknown>): unknown {
  const field = String(payload.field ?? '')
  const oldValue = String(payload.old_value ?? '').trim()
  const newValue = String(payload.new_value ?? '').trim()
  if (!CUMULATIVE_STATE_FIELDS.has(field) || !oldValue || !newValue || newValue.includes(oldValue)) {
    return payload.new_value
  }
  if (STATE_REMOVAL_MARKERS.some((marker) => newValue.includes(marker))) return payload.new_value
  const additive = ['新增', '增加', '获得', '得到', '另有'].some((marker) => newValue.includes(marker))
  const unchangedTail = newValue.includes('其余') && newValue.includes('不变')
  if (!additive && !unchangedTail) return payload.new_value
  const delta = newValue
    .replace(/[；;，,]?\s*其余(?:物件|物品|信息|内容)?不变[。.]?/, '')
    .replace(/^[；;，,。\s]+|[；;，,。\s]+$/g, '')
  return delta ? `${oldValue}；${delta}` : oldValue
}

export function formatCandidateValue(
  key: string,
  value: unknown,
  referenceNames: Readonly<Record<string, string>> = {},
): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return value.map((item) => referenceNames[String(item)] ?? String(item)).join('、')
  if (typeof value === 'object') {
    const fields = value as Record<string, unknown>
    if (key === 'trigger') {
      const rows = [
        ['人物', fields.actor],
        ['动作', fields.action],
        ['对象', fields.object],
      ].filter((row) => row[1] !== null && row[1] !== undefined && row[1] !== '')
      if (rows.length > 0) {
        return rows.map(([label, item]) => `${label}：${referenceNames[String(item)] ?? String(item)}`).join('\n')
      }
    }
    return Object.entries(fields)
      .map(([field, item]) => `${field}：${referenceNames[String(item)] ?? String(item)}`)
      .join('\n')
  }
  const s = String(value)
  if (referenceNames[s]) return referenceNames[s]
  if (FIELD_VALUE_LABELS[key]?.[s]) return FIELD_VALUE_LABELS[key][s]
  return ID_KEYS.has(key) && s.length > 12 ? `${s.slice(0, 8)}…` : s
}

/** payload → 有序 [标签, 值] 行；curated 键优先，未知键追加，跳过冗余键 */
export function candidateFields(
  kind: CandidateKind,
  payload: Record<string, unknown>,
  referenceNames: Readonly<Record<string, string>> = {},
): Array<[string, string]> {
  const rows: Array<[string, string]> = []
  const appended = new Set<string>()
  const append = (key: string) => {
    if (SKIP_KEYS.has(key) || appended.has(key)) return
    const rawValue = kind === 'character_state' && key === 'new_value'
      ? materializeDisplayedState(payload)
      : payload[key]
    const value = formatCandidateValue(key, rawValue, referenceNames)
    if (value === '') return
    rows.push([FIELD_LABELS[key] ?? key, value])
    appended.add(key)
  }
  for (const key of KIND_FIELD_ORDER[kind] ?? []) append(key)
  for (const key of Object.keys(payload)) append(key)
  return rows
}
