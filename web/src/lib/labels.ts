// 中文标签与色调映射（状态/severity 一律文字+色+icon 三通道，DESIGN §Review）。
import type { BadgeTone } from '../components/StatusBadge'
import type { ChapterStatus, FindingSeverity, TaskStatus, Verdict } from '../types'

export const NODE_LABELS: Record<string, string> = {
  load_state: '加载状态',
  recall: '回忆召回',
  plan_chapter: '章节规划',
  write: '写作',
  extract: '记忆抽取',
  validate: '校验',
  revise: '修订',
  audit: '审核',
  persist: '落库',
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

export function chapterStatusLabel(s: ChapterStatus): string {
  return {
    planning: '规划中',
    writing: '写作中',
    awaiting_review: '待确认',
    confirmed: '已确认',
    failed: '失败',
    cancelled: '已取消',
  }[s]
}

export function chapterStatusTone(s: ChapterStatus): BadgeTone {
  return CHAPTER_TONES[s]
}

const TASK_TONES: Record<TaskStatus, BadgeTone> = {
  queued: 'hint',
  running: 'accent',
  paused: 'warning',
  awaiting_review: 'warning',
  failed: 'error',
  cancelled: 'hint',
  done: 'success',
}

export function taskStatusLabel(s: TaskStatus): string {
  return {
    queued: '排队中',
    running: '运行中',
    paused: '已暂停',
    awaiting_review: '待人工',
    failed: '失败',
    cancelled: '已取消',
    done: '完成',
  }[s]
}

export function taskStatusTone(s: TaskStatus): BadgeTone {
  return TASK_TONES[s]
}

export function severityLabel(s: FindingSeverity): string {
  return { critical: '致命', major: '重大', minor: '次要', hint: '提示' }[s]
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
