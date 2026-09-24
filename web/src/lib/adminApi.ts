import { authenticatedGet, authenticatedSend } from './api'

export interface AdminPage<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface AdminMetrics {
  run_count: number
  input_tokens: number
  output_tokens: number
  cost_est: number
  duration_ms: number
}

/** 两级均值：先按任务汇总，再对任务取平均。无任务时为 null（与「花费为零」区分）。 */
export interface AdminTaskAverages {
  avg_cost_per_task: number | null
  avg_duration_ms_per_task: number | null
  avg_runs_per_task: number | null
}

export interface CaptureLimits {
  max_depth: number
  max_items: number
  max_text: number
  max_bytes: number
}

export interface CapturedData {
  data: unknown
  truncated: boolean
  redacted: boolean
  limits: CaptureLimits
}

export interface AdminOverview {
  user_count: number
  project_count: number
  chapter_count: number
  task_count: number
  metrics: AdminMetrics
  task_status_counts: Record<string, number>
}

export interface AdminUser {
  id: string
  username: string
  tier: string
  role: 'user' | 'admin'
  project_count: number
  chapter_count: number
  word_count: number
  task_count: number
  metrics: AdminMetrics
  task_averages: AdminTaskAverages
}

export interface AdminProject {
  id: string
  user_id: string
  username: string
  title: string
  genre: string
  current_chapter: number
  target_words: number | null
  creation_status: string
  created_at: string
  updated_at: string
  chapter_count: number
  word_count: number
  task_count: number
  metrics: AdminMetrics
  task_averages: AdminTaskAverages
}

export interface AdminChapter {
  id: string
  project_id: string
  chapter_seq: number
  title: string | null
  status: string
  word_count: number
  created_at: string
  updated_at: string
}

export interface AdminChapterDetail extends AdminChapter {
  content: string | null
  summary: string | null
  version: number
}

export interface AdminContextCollection {
  items: CapturedData[]
  total: number
  limit: number
  truncated: boolean
}

export interface AdminContext {
  project_id: string
  settings: CapturedData
  outlines: AdminContextCollection
  events: AdminContextCollection
  facts: AdminContextCollection
  characters: AdminContextCollection
  foreshadows: AdminContextCollection
  threads: AdminContextCollection
}

export interface AdminTask {
  id: string
  project_id: string
  user_id: string
  username: string
  project_title: string
  task_type: string
  status: string
  chapter_seq: number | null
  batch_task_id: string | null
  retry_count: number
  created_at: string
  updated_at: string
  metrics: AdminMetrics
}

export interface AdminTaskDetail extends AdminTask {
  payload: CapturedData
  error: CapturedData
  elapsed_ms: number
  elapsed_includes_waits: true
}

/** 一本书里的一个任务一行（分析页第二层）。 */
export interface AdminGenerationTask {
  id: string
  task_type: string
  status: string
  chapter_seq: number | null
  batch_task_id: string | null
  retry_count: number
  chapter_count: number
  snapshot_count: number
  created_at: string
  updated_at: string
  metrics: AdminMetrics
}

/** 快照指针：只有定位与标量，正文在 /snapshots/{id}。 */
export interface AdminSnapshotRef {
  id: number
  stage: string
  attempt: number
  model_id: string | null
  cost_est: number
  duration_ms: number
  degraded: boolean
  created_at: string
}

/** 任务内按章的分解（分析页第三层）。 */
export interface AdminTaskChapter {
  chapter_seq: number | null
  stages: string[]
  metrics: AdminMetrics
  snapshots: AdminSnapshotRef[]
}

/** 渲染后的提示词分节。hash 只留字节数与摘要；full 留原文（可能被节上限截断）。 */
export interface SnapshotSection {
  role: string | null
  name: string | null
  policy: 'full' | 'hash'
  text?: string
  bytes?: number
  sha256?: string
  truncated?: boolean
  omitted?: 'budget'
}

export interface SnapshotPrompt {
  sections: SnapshotSection[]
  truncated: boolean
  bytes: number
}

export interface SnapshotRecallItem {
  [key: string]: unknown
}

export interface SnapshotRecall {
  groups: Record<string, SnapshotRecallItem[]>
  counts: Record<string, number>
  stats: Record<string, unknown>
}

/** 快照留存的原始输入（选择性）。键的存在即代表该阶段有这项内容。 */
export interface SnapshotPayload {
  prompt?: SnapshotPrompt
  output?: { bytes: number; sha256: string; excerpt: string }
  recall?: SnapshotRecall
  findings?: SnapshotFinding[]
  applied_spans?: Array<{ target: string; replacement: string }>
  input_draft?: { bytes: number; sha256: string; excerpt: string }
  summary?: string
  error?: string
  _capture?: { scope: string; selective: boolean; truncated: boolean; redacted: boolean }
}

export interface AdminSnapshot {
  id: number
  project_id: string
  task_id: string
  chapter_seq: number | null
  stage: string
  attempt: number
  model_id: string | null
  input_tokens: number
  output_tokens: number
  cache_hit: boolean
  duration_ms: number
  cost_est: number
  retry_count: number
  degraded: boolean
  created_at: string
  updated_at: string
  payload: CapturedData
  snapshot_missing: boolean
}

export interface SnapshotEvidence {
  chapter: number
  quote: string
}

/** 一条校验发现 + 它出现在哪一章哪次尝试。 */
export interface SnapshotFinding {
  finding_id?: string | null
  conflict_key?: string | null
  conflict_type?: string | null
  severity?: string | null
  scope?: string | null
  source?: string | null
  confidence?: number | null
  suggestion?: string | null
  evidence?: SnapshotEvidence[]
}

export interface AdminSnapshotFinding extends SnapshotFinding {
  snapshot_id: number
  task_id: string
  chapter_seq: number | null
  attempt: number
  evidence: SnapshotEvidence[]
}

export interface AdminRun {
  id: number
  project_id: string | null
  user_id: string
  username: string | null
  project_title: string | null
  task_id: string | null
  node: string
  role: string | null
  model_id: string | null
  input_tokens: number
  output_tokens: number
  cost_est: number
  duration_ms: number
  cache_hit: boolean
  degraded: boolean
  retry_count: number
  created_at: string
  updated_at: string
}

export interface AdminRunDetail extends AdminRun {
  detail: CapturedData
  error: CapturedData
  detail_missing: boolean
  prompt_missing: boolean
}

export interface AdminAccessLog {
  id: number
  actor_id: string
  action: string
  target: string
  created_at: string
}

export interface AdminInvitation {
  id: string
  label: string | null
  expires_at: string
  max_redemptions: number
  redemption_count: number
  revoked_at: string | null
  created_by: string | null
  created_by_username: string | null
  created_at: string
}

export interface AdminInvitationCreated {
  id: string
  code: string
  label: string | null
  expires_at: string
  max_redemptions: number
}

export interface InvitationDraft {
  expiresDays: number
  maxRedemptions: number
  label?: string
  code?: string
}

interface PageFilters {
  limit?: number
  offset?: number
}

interface ProjectFilters extends PageFilters {
  userId?: string
  q?: string
}

interface TaskFilters extends PageFilters {
  userId?: string
  projectId?: string
  status?: string
}

interface RunFilters extends PageFilters {
  userId?: string
  projectId?: string
  node?: string
}

interface FindingFilters extends PageFilters {
  severity?: string
  chapterSeq?: number
}

function query(entries: Array<[string, string | number | undefined]>): string {
  const params = new URLSearchParams()
  for (const [key, value] of entries) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  const result = params.toString()
  return result ? `?${result}` : ''
}

const paging = (filters: PageFilters): Array<[string, string | number | undefined]> => [
  ['limit', filters.limit ?? 25], ['offset', filters.offset ?? 0],
]

export const adminApi = {
  getOverview: (token: string, signal?: AbortSignal) =>
    authenticatedGet<AdminOverview>('/admin/overview', token, signal),

  listUsers: (token: string, filters: PageFilters & { q?: string }, signal?: AbortSignal) =>
    authenticatedGet<AdminPage<AdminUser>>(`/admin/users${query([
      ['q', filters.q], ...paging(filters),
    ])}`, token, signal),

  listProjects: (token: string, filters: ProjectFilters, signal?: AbortSignal) =>
    authenticatedGet<AdminPage<AdminProject>>(`/admin/projects${query([
      ['user_id', filters.userId], ['q', filters.q], ...paging(filters),
    ])}`, token, signal),

  getProject: (token: string, projectId: string, signal?: AbortSignal) =>
    authenticatedGet<AdminProject>(`/admin/projects/${encodeURIComponent(projectId)}`, token, signal),

  listChapters: (token: string, projectId: string, filters: PageFilters, signal?: AbortSignal) =>
    authenticatedGet<AdminPage<AdminChapter>>(
      `/admin/projects/${encodeURIComponent(projectId)}/chapters${query(paging(filters))}`,
      token, signal,
    ),

  getChapter: (token: string, projectId: string, chapterId: string, signal?: AbortSignal) =>
    authenticatedGet<AdminChapterDetail>(
      `/admin/projects/${encodeURIComponent(projectId)}/chapters/${encodeURIComponent(chapterId)}`,
      token, signal,
    ),

  getProjectContext: (token: string, projectId: string, limit = 25, signal?: AbortSignal) =>
    authenticatedGet<AdminContext>(
      `/admin/projects/${encodeURIComponent(projectId)}/context${query([['limit', limit]])}`,
      token, signal,
    ),

  listTasks: (token: string, filters: TaskFilters, signal?: AbortSignal) =>
    authenticatedGet<AdminPage<AdminTask>>(`/admin/tasks${query([
      ['user_id', filters.userId], ['project_id', filters.projectId], ['status', filters.status],
      ...paging(filters),
    ])}`, token, signal),

  getTask: (token: string, taskId: string, signal?: AbortSignal) =>
    authenticatedGet<AdminTaskDetail>(`/admin/tasks/${encodeURIComponent(taskId)}`, token, signal),

  listTaskRuns: (token: string, taskId: string, filters: PageFilters, signal?: AbortSignal) =>
    authenticatedGet<AdminPage<AdminRun>>(
      `/admin/tasks/${encodeURIComponent(taskId)}/runs${query(paging(filters))}`,
      token, signal,
    ),

  listRuns: (token: string, filters: RunFilters, signal?: AbortSignal) =>
    authenticatedGet<AdminPage<AdminRun>>(`/admin/runs${query([
      ['user_id', filters.userId], ['project_id', filters.projectId], ['node', filters.node],
      ...paging(filters),
    ])}`, token, signal),

  getRun: (token: string, runId: number, signal?: AbortSignal) =>
    authenticatedGet<AdminRunDetail>(`/admin/runs/${runId}`, token, signal),

  listGenerationTasks: (token: string, projectId: string, filters: PageFilters, signal?: AbortSignal) =>
    authenticatedGet<AdminPage<AdminGenerationTask>>(
      `/admin/projects/${encodeURIComponent(projectId)}/generation-tasks${query(paging(filters))}`,
      token, signal,
    ),

  listTaskChapters: (token: string, taskId: string, filters: PageFilters, signal?: AbortSignal) =>
    authenticatedGet<AdminPage<AdminTaskChapter>>(
      `/admin/tasks/${encodeURIComponent(taskId)}/chapters${query(paging(filters))}`,
      token, signal,
    ),

  getSnapshot: (token: string, snapshotId: number, signal?: AbortSignal) =>
    authenticatedGet<AdminSnapshot>(`/admin/snapshots/${snapshotId}`, token, signal),

  listFindings: (token: string, projectId: string, filters: FindingFilters, signal?: AbortSignal) =>
    authenticatedGet<AdminPage<AdminSnapshotFinding>>(
      `/admin/projects/${encodeURIComponent(projectId)}/findings${query([
        ['severity', filters.severity], ['chapter_seq', filters.chapterSeq], ...paging(filters),
      ])}`,
      token, signal,
    ),

  listAccessLogs: (token: string, filters: PageFilters, signal?: AbortSignal) =>
    authenticatedGet<AdminPage<AdminAccessLog>>(
      `/admin/access-logs${query(paging(filters))}`, token, signal,
    ),

  listInvitations: (token: string, filters: PageFilters, signal?: AbortSignal) =>
    authenticatedGet<AdminPage<AdminInvitation>>(
      `/admin/invitations${query(paging(filters))}`, token, signal,
    ),

  createInvitation: (token: string, draft: InvitationDraft, signal?: AbortSignal) =>
    authenticatedSend<AdminInvitationCreated>('POST', '/admin/invitations', token, {
      expires_days: draft.expiresDays,
      max_redemptions: draft.maxRedemptions,
      label: draft.label?.trim() || null,
      code: draft.code?.trim() || null,
    }, signal),

  revokeInvitation: (token: string, invitationId: string, signal?: AbortSignal) =>
    authenticatedSend<{ ok: true }>(
      'POST', `/admin/invitations/${encodeURIComponent(invitationId)}/revoke`, token, undefined, signal,
    ),
}
