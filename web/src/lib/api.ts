// fetch 统一封装：Vite dev proxy 把 /api 转发到网关 :8080（同源免 CORS）。
// 网关业务路由一律 Bearer（§14.1 ③）；非 2xx 统一抛 ApiError（code = 网关 {"error": code}）。

import type {
  AuthResponse,
  CandidateActionResponse,
  CharacterCard,
  ChapterDetail,
  ChapterMeta,
  ChapterVersionsResponse,
  ContentUpdateResponse,
  CorrectMemoryResponse,
  CreateProjectBody,
  DeleteChapterResponse,
  GenerateResponse,
  AuditRunResponse,
  GlobalAuditReportDetail,
  GlobalAuditReportSummary,
  LessonActionResponse,
  LoreEntity,
  MemoryCandidate,
  Project,
  ProjectSettings,
  SetupBody,
  SetupConfirmResponse,
  SetupDraft,
  SkillPreset,
  StyleDraft,
  StyleProfile,
  StyleProfileResponse,
  TaskControlResponse,
  TaskDetail,
  TaskSummary,
  UpdateProjectBody,
  WorldView,
  WritingLesson,
} from '../types'
import { dispatchUnauthorized, getToken } from './token'

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

/** 三层闸门拒绝码（§6.11）：429 时前端按 code 展示中文文案 */
export const GATE_CODES: Record<string, string> = {
  QUOTA_EXCEEDED: '今日免费额度已用完，请明天再试',
  BOOK_QUOTA_EXCEEDED: '本书当日写作额度已用完',
  CONCURRENCY_LIMIT: '本书已有进行中的任务，请稍候',
  DAILY_BUDGET_EXCEEDED: '当日全局成本预算已用完',
  BOOK_CNT_EXCEEDED: '今日新建作品数已达上限',
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(BASE + path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'network_error', null)
  }

  if (!res.ok) {
    let parsed: unknown = null
    try {
      parsed = await res.json()
    } catch {
      /* 非 JSON 响应：保留原始状态 */
    }
    const code =
      (parsed as { error?: string } | null)?.error ?? res.statusText
    if (res.status === 401) dispatchUnauthorized()
    throw new ApiError(res.status, code, parsed)
  }
  return (await res.json()) as T
}

export const api = {
  login: (username: string) =>
    request<AuthResponse>('POST', '/auth/token', { username }),

  listProjects: () => request<Project[]>('GET', '/projects'),

  listChapters: (pid: string) =>
    request<ChapterMeta[]>('GET', `/projects/${pid}/chapters`),

  getChapter: (pid: string, cid: string) =>
    request<ChapterDetail>('GET', `/projects/${pid}/chapters/${cid}`),

  updateContent: (pid: string, cid: string, content: string) =>
    request<ContentUpdateResponse>('PUT', `/projects/${pid}/chapters/${cid}/content`, {
      content,
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
    body: { seq: number; user_instruction?: string },
  ) => request<GenerateResponse>('POST', `/projects/${pid}/chapters/${cid}/generate`, body),

  generateBatch: (pid: string, body: { size: number; start: number }) =>
    request<GenerateResponse>('POST', `/projects/${pid}/batches/generate`, body),

  getTask: (tid: string) => request<TaskDetail>('GET', `/tasks/${tid}`),

  // 项目任务历史（阶段 4 任务视图）：切书后展示该书过往任务（网关转发 Python）。
  listTasks: (pid: string) => request<TaskSummary[]>('GET', `/projects/${pid}/tasks`),

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

  rejectCandidate: (pid: string, cid: string) =>
    request<CandidateActionResponse>(
      'POST', `/projects/${pid}/candidates/${cid}/reject`,
    ),

  // 创作设置（阶段 4 设置页）：settings 读/写 + 题材预设 + 文风样本/档案（网关转发 Python）。
  getSettings: (pid: string) =>
    request<ProjectSettings>('GET', `/projects/${pid}/settings`),

  updateSettings: (pid: string, model_routes: Record<string, string>) =>
    request<ProjectSettings>('PUT', `/projects/${pid}/settings`, { model_routes }),

  listSkillPresets: () => request<SkillPreset[]>('GET', '/skill-presets'),

  extractStyleSample: (pid: string, samples: string[]) =>
    request<StyleDraft>('POST', `/projects/${pid}/style-samples`, { samples }),

  putStyleProfile: (pid: string, profile: StyleProfile, skill_pack?: string) =>
    request<StyleProfileResponse>(
      'PUT', `/projects/${pid}/style-profile`,
      skill_pack ? { profile, skill_pack } : { profile },
    ),

  // 全局审计报告（阶段 4 审计视图）：手动触发 + 列表 + 详情（网关转发 Python）。
  triggerGlobalAudit: (pid: string) =>
    request<AuditRunResponse>('POST', `/projects/${pid}/global-audit`),

  listGlobalAudits: (pid: string) =>
    request<GlobalAuditReportSummary[]>('GET', `/projects/${pid}/global-audit`),

  getGlobalAudit: (pid: string, rid: string) =>
    request<GlobalAuditReportDetail>('GET', `/projects/${pid}/global-audit/${rid}`),

  // 建书向导 + 设定浏览（§7.11：创建作品 / 设定草稿 / 确认落库 / 世界观 / 人物卡片）。
  createProject: (body: CreateProjectBody) => request<Project>('POST', '/projects', body),

  // 作品信息更新（§6.9 每章目标字数可配）：未传字段不改，显式 null 置空。
  updateProject: (pid: string, body: UpdateProjectBody) =>
    request<Project>('PUT', `/projects/${pid}`, body),

  setupDraft: (pid: string, premise: string) =>
    request<SetupDraft>('POST', `/projects/${pid}/setup-draft`, { premise }),

  confirmSetup: (pid: string, body: SetupBody) =>
    request<SetupConfirmResponse>('PUT', `/projects/${pid}/setup`, body),

  getWorld: (pid: string) => request<WorldView>('GET', `/projects/${pid}/world`),

  getCharacters: (pid: string) => request<CharacterCard[]>('GET', `/projects/${pid}/characters`),

  // 设定实体（§7.11 ④ 自动建档：武器/功法/技能/地点，低风险正文抽取自动登记）。
  listEntities: (pid: string) => request<LoreEntity[]>('GET', `/projects/${pid}/entities`),
}
