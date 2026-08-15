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

/** 章节历史版本（阶段 4 版本表：覆盖写前快照；reason = manual/batch/revise/revert） */
export interface ChapterVersion {
  version: number
  title: string | null
  content: string | null
  summary: string | null
  reason: string
  created_at: string | null
}

/** 版本列表响应（versions 降序；当前实时版本 = current_version，不在列表中） */
export interface ChapterVersionsResponse {
  chapter_id: string
  chapter_seq: number
  current_version: number
  versions: ChapterVersion[]
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

/** 项目任务历史列表项（GET /projects/:pid/tasks → Python TaskSummaryOut，阶段 4 任务视图）。
 * 轻量摘要不含 runs，点开任一条再走 GET /tasks/:id 拉节点流转记录。 */
export interface TaskSummary {
  task_id: string
  task_type: 'chapter_generate' | 'batch_generate' | string
  status: TaskStatus
  chapter_seq: number | null
  /** 批次任务：目标章数（payload.size）；单章任务为 null */
  batch_size: number | null
  /** 批次任务：已完成章数（该批 persist 节点去重派生）；单章任务为 null */
  batch_current: number | null
  error: string | null
  created_at: string | null
}

/** 记忆候选 kind（memory_candidates 表 CHECK 枚举，§7.3 事实生命周期） */
export type CandidateKind =
  | 'event'
  | 'fact'
  | 'character_state'
  | 'relation_change'
  | 'foreshadow'
  | 'chapter_summary'
  | 'memory_removal'
  | (string & {})

/** 待确认候选（list_candidates，routes_candidates.py；payload 为自由 dict） */
export interface MemoryCandidate {
  candidate_id: string
  kind: CandidateKind
  source_chapter: number
  payload: Record<string, unknown>
  confidence: number
  status: 'pending' | 'confirmed' | 'rejected'
  created_at: string | null
}

export interface CandidateActionResponse {
  candidate_id: string
  status: 'confirmed' | 'rejected'
}

/** 校正记忆响应（POST chapters/:cid/correct-memory → Python CorrectMemoryOut，§7.3） */
export interface CorrectMemoryResponse {
  chapter_seq: number
  /** 该章编辑后重新抽取 → 与已落库记忆 diff 出的变更集（进待确认池） */
  changeset: Record<string, unknown>
  pool: Record<string, unknown>
  /** 无差异 → true（前端提示「无变更」，不打扰） */
  no_op: boolean
}

/** 级联删章明细（DELETE chapters/:cid → Python DeleteChapterOut：删该章及其后全部章节） */
export interface DeletedChapter {
  chapter_seq: number
  title: string | null
  invalidation: Record<string, unknown>
}

export interface DeleteChapterResponse {
  deleted: DeletedChapter[]
  /** 删完后的当前最大章序 */
  current_chapter: number
}

/** 写作经验（GET lessons → Python WritingLessonOut，§8.9 reflexion：批次复盘高危经验） */
export interface WritingLesson {
  lesson_id: string
  category: string
  lesson_type: string
  content: string
  evidence: Array<Record<string, unknown>>
  confidence: number
  source_chapter: number
  /** proposed 待确认 → confirm/reject → active/rejected */
  status: 'proposed' | 'active' | 'rejected' | (string & {})
  recurrence_count: number
  last_recurrence_at: number | null
  created_at: string | null
}

export interface LessonActionResponse {
  lesson_id: string
  status: 'active' | 'rejected' | (string & {})
}

/** 文风档案（§7.12 StyleProfile：键值透传，validate_profile 顶层 None 丢弃） */
export type StyleProfile = Record<string, unknown>

/** 创作设置（GET/PUT settings，routes_settings.py；model_routes 全量替换） */
export interface ProjectSettings {
  style_profile: StyleProfile
  skill_pack: string | null
  model_routes: Record<string, string>
  version: number
}

/** 题材 Skill 预设（skill-presets，routes_style.py；id 即 skill_pack marker） */
export interface SkillPreset {
  id: string
  name: string
  genre: string
  style_profile: StyleProfile
}

/** 文风样本提取响应（style-samples：统计层 + LLM 提炼草稿；extract_error 为 LLM 降级提示） */
export interface StyleDraft {
  draft: StyleProfile & { extract_error?: string }
}

/** 文风档案确认落库响应（style-profile：确认 + 可选 skill_pack 原子写） */
export interface StyleProfileResponse {
  style_profile: StyleProfile
  skill_pack: string | null
  version: number
}

/** 全局审计报告（GET global-audit 列表项，routes_global_audit.py；findings 明细在详情） */
export interface GlobalAuditReportSummary {
  report_id: string
  window_start: number
  window_end: number
  audited_up_to_chapter: number
  trigger: 'batch' | 'manual' | (string & {})
  status: string
  sampled: number
  findings: number
  chapters: number
  bridge?: { pairs: number; findings: number } | null
  style?: { sampled: number; findings: number } | null
  error: string | null
  created_at: string | null
}

/** 全局审计报告详情（GET global-audit/:id = 列表项 + 抽样角色 + findings 明细） */
export interface GlobalAuditReportDetail extends Omit<GlobalAuditReportSummary, 'findings'> {
  findings: Finding[]
  sampled_characters: Array<{ character_id: string; name: string }>
  summary: Record<string, unknown>
}

/** 手动触发全局审计响应（POST global-audit：run_global_audit 报告 dict，无 report_id/trigger） */
export interface AuditRunResponse {
  window_start: number
  window_end: number
  audited_up_to_chapter: number
  status: string
  sampled_characters: Array<{ character_id: string; name: string }>
  findings: Finding[]
  error: string | null
  summary: Record<string, unknown>
}

/** 建书（§7.11 建书向导）：POST /projects 创建 Project + 空 ProjectSettings（不调 LLM） */
export interface CreateProjectBody {
  title: string
  genre: string
}

/** 设定骨架草稿请求（§7.11 ②：一句话梗概 → Planner 提案） */
export interface SetupDraftBody {
  premise: string
}

/** 设定骨架草稿响应（可编辑不落库；LLM 失败 → draft:{} + error 降级） */
export interface SetupDraft {
  draft: Record<string, unknown>
  error: string | null
}

/** 设定确认落库（§7.11 ③ append-only：world_rules/hard_constraints 整体替换、角色/势力/地点按 name 建） */
export interface SetupBody {
  world_rules: Record<string, unknown>
  hard_constraints: string[]
  characters: Array<Record<string, unknown>>
  forces: Array<Record<string, unknown>>
  locations: Array<{ name: string }>
}

export interface SetupConfirmResponse {
  ok: boolean
}

/** 势力（世界观浏览） */
export interface LoreFaction {
  name: string
  stance: string | null
  resources: string[]
}

/** 地点（世界观浏览） */
export interface LoreLocation {
  name: string
}

/** 世界观浏览（GET world：world_rules 含 realm_order 列表、hard_constraints + 势力/地点） */
export interface WorldView {
  world_rules: Record<string, unknown>
  hard_constraints: string[]
  factions: LoreFaction[]
  locations: LoreLocation[]
}

/** 人物卡片（静态基底 + 当前状态台账 §7.7，state 按当前章物化 {field: new_value}） */
export interface CharacterCard {
  id: string
  name: string
  race: string | null
  origin: string | null
  realm_cap: string
  personality: string | null
  aliases: unknown[]
  base_attrs: Record<string, unknown>
  state: Record<string, string>
}
