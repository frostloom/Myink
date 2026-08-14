// API 类型（字段对齐 Python 侧已核实响应形状，见 plan.md 阶段 4 首切计划 §7）

export interface AuthResponse {
  token: string
  user_id: string
  expires_in: number
}

export interface Project {
  id: string
  title: string
  genre: string
  current_chapter: number
}

export type ChapterStatus =
  | 'planning'
  | 'writing'
  | 'awaiting_review'
  | 'confirmed'
  | 'failed'
  | 'cancelled'

export interface ChapterMeta {
  id: string
  chapter_seq: number
  title: string | null
  status: ChapterStatus
}

/** 单章详情（get_chapter，main.py:117；无 version——version 由保存响应返回） */
export interface ChapterDetail extends ChapterMeta {
  content: string | null
  summary: string | null
}

export interface ContentUpdateResponse {
  chapter_id: string
  chapter_seq: number
  status: string
  version: number
}

export type TaskStatus =
  | 'queued'
  | 'running'
  | 'paused'
  | 'awaiting_review'
  | 'failed'
  | 'cancelled'
  | 'done'

export interface GenerateResponse {
  task_id: string
  trace_id: string
  status: string
}

/** 批次控制响应（POST /batches/:id/:action → Python tasks/{id}/{action}） */
export interface TaskControlResponse {
  task_id: string
  status: TaskStatus
  message?: string
}

export type RunNode =
  | 'load_state'
  | 'recall'
  | 'plan_chapter'
  | 'write'
  | 'extract'
  | 'validate'
  | 'revise'
  | 'audit'
  | 'persist'
  | 'batch_plan'
  | 'batch_end'
  | 'global_audit'
  | 'style_extract'
  | (string & {})

export interface AgentRun {
  node: RunNode
  model_id: string | null
  input_tokens: number
  output_tokens: number
  cache_hit: boolean
  duration_ms: number
  cost_est: number
  retry_count: number
  degraded: boolean
  error: string | null
  /** 确定性节点记执行统计；audit 行带 audit_verdict */
  detail: { audit_verdict?: AuditVerdict } | null
}

export type Verdict = 'pass' | 'rewrite' | 'replan'

export interface AuditVerdict {
  verdict: Verdict
  replan_target?: 'chapter' | 'batch' | null
  findings: Finding[]
  reasons: string[]
  confidence: number
}

export type FindingSeverity = 'critical' | 'major' | 'minor' | 'hint'

export interface Finding {
  conflict_key: string
  conflict_type: string
  severity: FindingSeverity
  scope: 'local' | 'structural'
  source: string
  evidence: Array<{ chapter: number; quote: string }>
  suggestion: string | null
}

export interface TaskDetail {
  task_id: string
  task_type: 'chapter_generate' | 'batch_generate' | string
  status: TaskStatus
  payload: Record<string, unknown>
  error: string | null
  retry_count: number
  trace_id: string | null
  chapter_seq: number | null
  batch_task_id: string | null
  created_at: string | null
  /** 仅批次任务 */
  progress?: { current: number; total: number }
  runs: AgentRun[]
}
