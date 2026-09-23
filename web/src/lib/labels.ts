// 中文标签与色调映射（状态/severity 一律文字+色+icon 三通道，DESIGN §Review）。
import type { BadgeTone } from '../components/StatusBadge'
import type { ChapterStatus, FindingSeverity, TaskStatus, Verdict } from '../types'

export const NODE_LABELS: Record<string, string> = {
  load_state: '加载状态',
  recall: '回忆召回',
  plan_cast: '出场人物',
  plan_chapter: '章节规划',
  plan_review: '确认计划',
  write: '写作',
  extract: '记忆抽取',
  validate: '校验',
  revise: '修订',
  patch: '局部修订',
  audit: '审核',
  route: '策略路由',
  reset_replan: '重新规划',
  persist: '落库',
  summarize: '章节摘要',
  reflexion: '复盘',
  batch_plan: '批次规划',
  batch_end: '批次收尾',
  global_audit: '全局审计',
  style_extract: '文风提炼',
}

export function nodeLabel(node: string): string {
  return NODE_LABELS[node] ?? node
}

const CHAPTER_TONES: Record<ChapterStatus, BadgeTone> = {
  planning: 'hint',
  writing: 'accent',
  awaiting_review: 'warning',
  confirmed: 'success',
  failed: 'error',
  cancelled: 'hint',
}

export function chapterStatusLabel(s: string): string {
  return {
    planning: '规划中',
    writing: '写作中',
    awaiting_review: '待确认',
    confirmed: '已确认',
    failed: '失败',
    cancelled: '已取消',
  }[s] ?? s
}

export function chapterStatusTone(s: ChapterStatus): BadgeTone {
  return CHAPTER_TONES[s]
}

const TASK_TONES: Record<TaskStatus, BadgeTone> = {
  queued: 'hint',
  running: 'accent',
  paused: 'warning',
  awaiting_plan: 'warning',
  awaiting_review: 'warning',
  failed: 'error',
  cancelled: 'hint',
  done: 'success',
}

/** 管理台读的是库里的裸字符串，可能落在联合类型之外：认不出就原样返回。 */
export function taskStatusLabel(s: string): string {
  return {
    queued: '排队中',
    running: '运行中',
    paused: '已暂停',
    awaiting_plan: '待确认计划',
    awaiting_review: '待人工',
    failed: '失败',
    cancelled: '已取消',
    done: '完成',
  }[s] ?? s
}

export function taskStatusTone(s: TaskStatus): BadgeTone {
  return TASK_TONES[s]
}

/** 任务类型中文标签（任务历史列表行；未知类型回退原名，不崩） */
export function taskTypeLabel(t: string): string {
  return {
    chapter_generate: '单章生成',
    batch_generate: '批次生成',
    validate: '校验',
    outline_generate: '大纲生成',
    global_audit: '全局审计',
  }[t] ?? t
}

/** 建书状态：草稿=设定未定，legacy_ready=存量书可直接开写。 */
export function creationStatusLabel(s: string): string {
  return { draft: '草稿', legacy_ready: '可直接写作' }[s] ?? s
}

/** 台账状态：事实的确认态与伏笔的生命周期共用一张表（两边取值不冲突）。 */
export function ledgerStatusLabel(s: string): string {
  return {
    confirmed: '已确认', expired: '已失效',
    planted: '已埋设', developing: '推进中', resolved: '已回收', dropped: '已放弃',
  }[s] ?? s
}

/** 用户等级：VIP 走网关高优先级队列（routes_tasks.py 的 tier 判定）。 */
export function tierLabel(s: string): string {
  return { normal: '普通', vip: 'VIP' }[s] ?? s
}

export function roleLabel(s: string): string {
  return { user: '普通用户', admin: '管理员' }[s] ?? s
}

export function severityLabel(s: string): string {
  return { critical: '致命', major: '重大', minor: '次要', hint: '提示' }[s] ?? s
}

/** 修订范围：局部可走 patch，结构性必须整章重写（validation/service.py 的判定口径）。 */
export function scopeLabel(s: string): string {
  return { local: '局部', structural: '结构性' }[s] ?? s
}

export function severityTone(s: FindingSeverity): BadgeTone {
  return s // critical/major/minor/hint 与 badge tone 同名
}

export function verdictLabel(v: Verdict): string {
  return { pass: '通过', rewrite: '重写', replan: '重规划' }[v]
}

export function verdictTone(v: Verdict): BadgeTone {
  return v === 'pass' ? 'success' : v === 'rewrite' ? 'warning' : 'error'
}

export function conflictTypeLabel(type: string): string {
  return {
    faction: '势力设定', power: '境界与战力', timeline: '时间线', location: '地点连续性',
    character: '人物设定', character_state: '人物状态', relation: '人物关系',
    foreshadow: '伏笔', item_rule: '物品规则', plotline: '剧情线', persona: '人物行为',
    volume: '卷规划',
    style: '文风与重复', fact: '事实设定',
  }[type] ?? type
}

export function findingSourceLabel(source: string): string {
  return { L1: '确定性校验', L2: '语义台账校验', audit: '模型审核' }[source] ?? source
}
