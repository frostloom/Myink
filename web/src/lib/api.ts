import type { TaskBudgetLimits, ResumeBudgetBody } from '../types'
// fetch 统一封装：Vite dev proxy 把 /api 转发到 Caddy（:80，见 vite.config.ts），生产同源。
// 业务路由一律 Bearer（§14.1 ③）；非 2xx 统一抛 ApiError（code = {"error": code} 信封）。

import type {
  AuthResponse,
  AuthSessionResponse,
  CandidateActionResponse,
  CharacterCard,
  CharacterStateChange,
  ChapterDetail,
  ChapterMeta,
  ChapterPlan,
  ChapterVersionsResponse,
  ConnectionTestResult,
  ContentUpdateResponse,
  EnvironmentSettings,
  CorrectMemoryResponse,
  CreateProjectBody,
  DeleteChapterResponse,
  DeleteProjectResponse,
  Feedback,
  FeedbackList,
  GenerateResponse,
  AuditRunResponse,
  GlobalAuditReportDetail,
  GlobalAuditReportSummary,
  Foreshadow,
  LessonActionResponse,
  LoreEntity,
  MemoryCandidate,
  MfaChallengeResponse,
  MfaEnrollResponse,
  MfaStatusResponse,
  ModelConnectionInput,
  ModelListResult,
  ModelProbeRequest,
  Project,
  ProjectCreation,
  ProjectSettings,
  BookOutlineResponse,
  OutlineConfirmBody,
  OutlineDraft,
  OutlineDraftBody,
  OkResponse,
  RankingsConfigInput,
  RankingsResponse,
  SetupBody,
  SetupConfirmResponse,
  SetupDraft,
  StoryEvent,
  TaskControlResponse,
  TaskDetail,
  TaskSummary,
  UpdateProjectBody,
  WorldGraphResponse,
  WorldView,
  WritingLesson,
  WritingMode,
} from '../types'
import { dispatchUnauthorized, getSessionUserId, getToken } from './token'

const BASE = '/api/v1'

export class ApiError extends Error {
  status: number
  code: string
  body: unknown

  constructor(status: number, code: string, body: unknown) {
    super(code)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.body = body
  }
}

export { GATE_CODES, formatApiError, formatErrorText } from './apiError'

interface RequestOptions {
  token?: string | null
  signal?: AbortSignal
  dispatchAuthFailure?: boolean
}

const authenticatedRequests = new Map<string, Set<AbortController>>()

export function abortRequestsForToken(token: string): void {
  const controllers = authenticatedRequests.get(token)
  if (!controllers) return
  for (const controller of controllers) controller.abort()
  authenticatedRequests.delete(token)
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options?: RequestOptions,
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = options?.token === undefined ? getToken() : options.token
  // 按账号（userId）而不是令牌字符串判定响应是否已作废：滑动续期会换令牌但不换账号，
  // 拿令牌比会把续期当换账号，把正在跑的请求判成 aborted。
  const identityAtStart = getSessionUserId()
  if (token) headers.Authorization = `Bearer ${token}`
  // FormData 的 Content-Type 得留给浏览器写，它要自己拼 multipart 边界
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'

  const controller = new AbortController()
  const abortFromCaller = () => controller.abort()
  if (options?.signal?.aborted) controller.abort()
  options?.signal?.addEventListener('abort', abortFromCaller, { once: true })
  if (token) {
    const pending = authenticatedRequests.get(token) ?? new Set<AbortController>()
    pending.add(controller)
    authenticatedRequests.set(token, pending)
  }

  try {
    const res = await fetch(BASE + path, {
      method,
      headers,
      body: isForm ? (body as FormData) : body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })

    if (!res.ok) {
      let parsed: unknown = null
      try {
        parsed = await res.json()
      } catch {
        /* 非 JSON 响应：保留原始状态 */
      }
      if (controller.signal.aborted || (token && getSessionUserId() !== identityAtStart)) {
        throw new ApiError(0, 'request_aborted', null)
      }
      const errorBody = parsed as { error?: string; detail?: unknown } | null
      const code = errorBody?.error
        ?? (typeof errorBody?.detail === 'string' ? errorBody.detail : res.statusText)
      if (res.status === 401 && token && options?.dispatchAuthFailure !== false) {
        dispatchUnauthorized(token)
      }
      throw new ApiError(res.status, code, parsed)
    }

    const parsed = (await res.json()) as T
    if (controller.signal.aborted || (token && getSessionUserId() !== identityAtStart)) {
      throw new ApiError(0, 'request_aborted', null)
    }
    return parsed
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (controller.signal.aborted) throw new ApiError(0, 'request_aborted', null)
    throw new ApiError(0, 'network_error', null)
  } finally {
    options?.signal?.removeEventListener('abort', abortFromCaller)
    if (token) {
      const pending = authenticatedRequests.get(token)
      pending?.delete(controller)
      if (pending?.size === 0) authenticatedRequests.delete(token)
    }
  }
}

// 管理面板等独立模块复用同一认证、账号切换中止与 401 分发语义。
export function authenticatedGet<T>(path: string, token: string, signal?: AbortSignal): Promise<T> {
  return request<T>('GET', path, undefined, { token, signal })
}

export function authenticatedSend<T>(
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  token: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  return request<T>(method, path, body, { token, signal })
}

export const api = {
  // 开了第二因子的账号回的是挑战票而不是令牌，用 `mfa_required` 判别（见 types.ts）。
  login: (username: string, password: string) =>
    request<AuthResponse | MfaChallengeResponse>(
      'POST', '/auth/token', { username, password }, { token: null },
    ),

  register: (username: string, password: string, invitationCode: string) =>
    request<AuthResponse>('POST', '/auth/register', {
      username,
      password,
      invitation_code: invitationCode,
    }, { token: null }),

  getSession: (token: string, signal?: AbortSignal) =>
    request<AuthSessionResponse>('GET', '/auth/session', undefined, { token, signal }),

  // 第二因子（§2.8，仅管理员；机制见 docs/AUTH.md）。verify 免身份——凭证是挑战票。
  verifyMfa: (mfaToken: string, code: string) =>
    request<AuthResponse>('POST', '/auth/mfa/verify', { mfa_token: mfaToken, code }, { token: null }),

  mfaStatus: (token?: string) =>
    request<MfaStatusResponse>('GET', '/auth/mfa', undefined, { token }),

  // 开第二因子要再验一次密码：光有令牌就够的话，偷到令牌的人能绑上自己的认证器。
  mfaEnroll: (password: string, token?: string) =>
    request<MfaEnrollResponse>('POST', '/auth/mfa/enroll', { password }, { token }),

  // confirm/disable 会自增 auth_version（踢掉开启前签发的所有令牌），所以本机令牌也会当场失效；
  // 验证码输错是 401，不能让它触发全局登出——同 changePassword 的 dispatchAuthFailure: false。
  mfaConfirm: (code: string, token?: string) =>
    request<OkResponse>('POST', '/auth/mfa/confirm', { code }, { token, dispatchAuthFailure: false }),

  mfaDisable: (code: string, token?: string) =>
    request<OkResponse>('POST', '/auth/mfa/disable', { code }, { token, dispatchAuthFailure: false }),

  changePassword: (currentPassword: string, newPassword: string, token?: string) =>
    request<OkResponse>('POST', '/auth/password', {
      current_password: currentPassword,
      new_password: newPassword,
    }, { token, dispatchAuthFailure: false }),

  logout: (token?: string, signal?: AbortSignal) =>
    request<OkResponse>('POST', '/auth/logout', undefined, { token, signal }),

  listProjects: () => request<Project[]>('GET', '/projects'),

  listChapters: (pid: string) =>
    request<ChapterMeta[]>('GET', `/projects/${pid}/chapters`),

  getChapter: (pid: string, cid: string) =>
    request<ChapterDetail>('GET', `/projects/${pid}/chapters/${cid}`),

  updateContent: (pid: string, cid: string, content: string, expectedVersion: number) =>
    request<ContentUpdateResponse>('PUT', `/projects/${pid}/chapters/${cid}/content`, {
      content,
      expected_version: expectedVersion,
    }),

  // 显式校正记忆（§7.3：编辑后重新抽取 → 与该章已落库记忆 diff → 变更集进待确认池）。
  // 同步 LLM 调用（一次 extract），网关超时 30s；超时属正常，提示重试即可。
  correctMemory: (pid: string, cid: string) =>
    request<CorrectMemoryResponse>('POST', `/projects/${pid}/chapters/${cid}/correct-memory`),

  // 级联删除章节（§7.3：删除该章及其后全部正文 + 记忆 + 池候选，进度回退）。
  deleteChapter: (pid: string, cid: string) =>
    request<DeleteChapterResponse>('DELETE', `/projects/${pid}/chapters/${cid}`),

  // 写作经验（§8.9 reflexion：批次复盘高危经验池）。confirm/reject 幂等（非 proposed 409）。
  listLessons: (pid: string) =>
    request<WritingLesson[]>('GET', `/projects/${pid}/lessons`),

  confirmLesson: (pid: string, lid: string) =>
    request<LessonActionResponse>('POST', `/projects/${pid}/lessons/${lid}/confirm`),

  rejectLesson: (pid: string, lid: string) =>
    request<LessonActionResponse>('POST', `/projects/${pid}/lessons/${lid}/reject`),

  // 章节历史版本（阶段 4 版本表）：列表 + 回退（网关转发 Python）。
  listChapterVersions: (pid: string, cid: string) =>
    request<ChapterVersionsResponse>('GET', `/projects/${pid}/chapters/${cid}/versions`),

  restoreChapterVersion: (pid: string, cid: string, version: number) =>
    request<ContentUpdateResponse>(
      'POST', `/projects/${pid}/chapters/${cid}/versions/${version}/restore`,
    ),

  generateChapter: (
    pid: string,
    cid: string,
    body: { seq: number; user_instruction?: string; rewrite?: boolean; mode?: WritingMode },
  ) => request<GenerateResponse>('POST', `/projects/${pid}/chapters/${cid}/generate`, body),

  generateBatch: (pid: string, body: { size: number; start: number }) =>
    request<GenerateResponse>('POST', `/projects/${pid}/batches/generate`, body),

  // 短篇：整篇一次成稿（成稿/审稿/改稿都在一个任务里），扣的是章数额度。
  generateShort: (pid: string) =>
    request<GenerateResponse>('POST', `/projects/${pid}/short/generate`),

  getTask: (tid: string) => request<TaskDetail>('GET', `/tasks/${tid}`),

  confirmTaskPlan: (tid: string, plan: ChapterPlan, expectedAttempt: number) =>
    request<TaskControlResponse>('POST', `/tasks/${tid}/plan/confirm`, {
      plan,
      expected_attempt: expectedAttempt,
    }),

  cancelTask: (tid: string) =>
    request<TaskControlResponse>('POST', `/tasks/${tid}/cancel`),

  resumeTask: (tid: string, body?: ResumeBudgetBody) =>
    request<TaskControlResponse>('POST', `/tasks/${tid}/resume`, body),

  // 项目任务历史（阶段 4 任务视图）：切书后展示该书过往任务（网关转发 Python）。
  // chapterSeq 非空 → 只列覆盖该章的任务 + 该章花费（右栏按章过滤，§11）。
  listTasks: (pid: string, chapterSeq?: number) =>
    request<TaskSummary[]>(
      'GET',
      `/projects/${pid}/tasks${chapterSeq ? `?chapter_seq=${chapterSeq}` : ''}`,
    ),

  // 批次控制（pause|resume|cancel）：网关转发 Python 任务控制端点；外部控制不发
  // SSE 事件，成功后调用方需主动 GET 快照刷新（useTaskEvents.refresh）。
  pauseBatch: (batchId: string) =>
    request<TaskControlResponse>('POST', `/batches/${batchId}/pause`),
  resumeBatch: (batchId: string) =>
    request<TaskControlResponse>('POST', `/batches/${batchId}/resume`),
  cancelBatch: (batchId: string) =>
    request<TaskControlResponse>('POST', `/batches/${batchId}/cancel`),

  // 待确认候选池（§6.11 确认分流）：GET 列表 + 人工 confirm/reject（编排层写库入口）。
  listCandidates: (pid: string, status = 'pending') =>
    request<MemoryCandidate[]>('GET', `/projects/${pid}/candidates?status=${status}`),

  confirmCandidate: (pid: string, cid: string) =>
    request<CandidateActionResponse>(
      'POST', `/projects/${pid}/candidates/${cid}/confirm`,
    ),

  rejectCandidate: (pid: string, cid: string, reason = "", mode: "revise" | "memory_only" = "revise") =>
    request<CandidateActionResponse>(
      'POST', `/projects/${pid}/candidates/${cid}/reject`, { reason, mode },
    ),

  // 创作设置（书内文风/预设/目标字数；模型连接已迁到账号级 /environment）。
  getSettings: (pid: string) =>
    request<ProjectSettings>('GET', `/projects/${pid}/settings`),

  updateSettings: (pid: string, model_routes: Record<string, string>, model_connections?: ModelConnectionInput[]) =>
    request<ProjectSettings>('PUT', `/projects/${pid}/settings`, { model_routes, model_connections }),

  getEnvironment: () => request<EnvironmentSettings>('GET', '/environment'),

  updateEnvironment: (body: {
    model_routes?: Record<string, string>
    model_connections?: ModelConnectionInput[]
    rankings?: RankingsConfigInput
    thinking_enabled?: boolean
    task_budget?: TaskBudgetLimits
  }) => request<EnvironmentSettings>('PUT', '/environment', body),

  // 模型连接探针（环境配置页）：拉取可用模型列表 / 联通测试。
  listModels: (body: ModelProbeRequest) =>
    request<ModelListResult>('POST', '/environment/models', body),

  testConnection: (body: ModelProbeRequest) =>
    request<ConnectionTestResult>('POST', '/environment/test-connection', body),

  listGenrePacks: () => request<import('../lib/genrePacks').GenreCatalogItem[]>('GET', '/genre-packs'),

  putGenrePack: (pid: string, fields: import('../lib/genrePacks').GenreFields) =>
    request<import('../lib/genrePacks').BookGenrePack>('PUT', `/projects/${pid}/genre-pack`, fields),

  restoreGenrePack: (pid: string) =>
    request<import('../lib/genrePacks').BookGenrePack>('POST', `/projects/${pid}/genre-pack/restore`),

  // 全局审计报告（阶段 4 审计视图）：手动触发 + 列表 + 详情（网关转发 Python）。
  triggerGlobalAudit: (pid: string) =>
    request<AuditRunResponse>('POST', `/projects/${pid}/global-audit`),

  listGlobalAudits: (pid: string) =>
    request<GlobalAuditReportSummary[]>('GET', `/projects/${pid}/global-audit`),

  getGlobalAudit: (pid: string, rid: string) =>
    request<GlobalAuditReportDetail>('GET', `/projects/${pid}/global-audit/${rid}`),

  // 建书向导 + 设定浏览（§7.11：创建作品 / 设定草稿 / 确认落库 / 世界观 / 人物卡片）。
  createProject: (body: CreateProjectBody) => request<Project>('POST', '/projects', body),
  getCreation: (pid: string) => request<ProjectCreation>('GET', `/projects/${encodeURIComponent(pid)}/creation`),

  // 作品信息更新（§6.9 每章目标字数可配）：未传字段不改，显式 null 置空。
  updateProject: (pid: string, body: UpdateProjectBody) =>
    request<Project>('PUT', `/projects/${pid}`, body),

  // 整本书删除（阶段 6 硬删：FK 级联清正文/记忆/向量/任务记录；有进行中任务 → 409）。
  deleteProject: (pid: string) =>
    request<DeleteProjectResponse>('DELETE', `/projects/${pid}`),

  setupDraft: (pid: string, premise: string) =>
    request<SetupDraft>('POST', `/projects/${pid}/setup-draft`, { premise }),

  confirmSetup: (pid: string, body: SetupBody) =>
    request<SetupConfirmResponse>('PUT', `/projects/${pid}/setup`, body),

  // 整书大纲：梗概 + 章节数 + 故事线 → 卷 + 约 30 章一段的阶段；写作注入当前卷/阶段。
  outlineDraft: (pid: string, body: OutlineDraftBody) =>
    request<OutlineDraft>('POST', `/projects/${pid}/outline-draft`, body),

  confirmOutline: (pid: string, body: OutlineConfirmBody) =>
    request<BookOutlineResponse>('PUT', `/projects/${pid}/outline`, body),

  getOutline: (pid: string) =>
    request<BookOutlineResponse>('GET', `/projects/${pid}/outline`),

  getWorld: (pid: string) => request<WorldView>('GET', `/projects/${pid}/world`),

  getCharacters: (pid: string) => request<CharacterCard[]>('GET', `/projects/${pid}/characters`),

  // 设定实体（§7.11 ④ 自动建档：武器/功法/技能/地点，低风险正文抽取自动登记）。
  listEntities: (pid: string) => request<LoreEntity[]>('GET', `/projects/${pid}/entities`),

  // 事件台账（§7.4 中期记忆全量：此前事件只写不读）。可按章号区间过滤。
  listEvents: (pid: string, fromChapter?: number, toChapter?: number) => {
    const q = [
      fromChapter != null ? `from_chapter=${fromChapter}` : '',
      toChapter != null ? `to_chapter=${toChapter}` : '',
    ]
      .filter(Boolean)
      .join('&')
    return request<StoryEvent[]>('GET', `/projects/${pid}/events${q ? `?${q}` : ''}`)
  },

  // 人物状态变化历史（§7.7 追加式台账全量，含已失效行）。
  getCharacterStateHistory: (pid: string, characterId: string) =>
    request<CharacterStateChange[]>(
      'GET',
      `/projects/${pid}/characters/${characterId}/state-history`,
    ),

  // 世界拓扑全量（§9 图谱：4 类节点 + 人物关系/地点层级边，ECharts 力导向渲染）。
  listGraph: (pid: string) => request<WorldGraphResponse>('GET', `/projects/${pid}/graph`),

  // 伏笔池台账（§7.9 状态机全量：planted/developing/resolved/dropped，设定页展示）。
  listForeshadows: (pid: string) => request<Foreshadow[]>('GET', `/projects/${pid}/foreshadows`),

  // 扫榜灵感（§10 榜单数据由后端自己去取，只作建书前的灵感工具；全局无项目端点，网关转发 Python）。
  // refresh=true 强制绕过进程内 TTL 缓存重拉（降级样例也可重试）。
  listRankings: (refresh = false) =>
    request<RankingsResponse>('GET', `/rankings${refresh ? '?refresh=true' : ''}`),

  // 用户反馈（灯泡挂件）：提交是 multipart（描述 + 图片/视频附件），列表只含本人。
  submitFeedback: (form: FormData, signal?: AbortSignal) =>
    request<Feedback>('POST', '/feedback', form, { signal }),

  listFeedback: (signal?: AbortSignal) =>
    request<FeedbackList>('GET', '/feedback', undefined, { signal }),
}

/** 反馈附件是二进制流，不走 JSON 解包：取回原始 Blob 供预览或另存。 */
export async function fetchFeedbackAttachment(
  feedbackId: string,
  index: number,
  signal?: AbortSignal,
): Promise<Blob> {
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${BASE}/feedback/${feedbackId}/attachments/${index}`, { headers, signal })
  if (!res.ok) {
    if (res.status === 401 && token) dispatchUnauthorized(token)
    throw new ApiError(res.status, res.status === 404 ? 'not_found' : 'network_error', null)
  }
  return res.blob()
}
