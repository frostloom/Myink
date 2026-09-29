/** 对话式短篇建书：取会话列表 / 打开某条 / 新建 / 发一句 / 确认开写 / 删掉一条。
 *
 * 会话是多条的：一个短篇一条，旧的原样留着能翻回去看。所以除了取列表，每个动作都要
 * 带上 sessionId。commit 只落书不出稿——入队走既有的 POST /projects/{id}/short/generate，
 * 配额与成本估算只有那一份实现。
 */
import { authenticatedGet, authenticatedSend } from './api'

export interface ShortCreationCard {
  working_title: string
  genre: string
  direction: string
  protagonist_pressure: string
  conflict_core: string
  emotional_payoff: string
  plot_sketch: string
  chapter_count: number
  chars_per_chapter: number
}

export const REQUIRED_CARD_FIELDS = [
  'working_title', 'genre', 'direction', 'protagonist_pressure',
  'conflict_core', 'emotional_payoff', 'plot_sketch',
] as const

export interface ShortCreationMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  card: Partial<ShortCreationCard> | null
  model_id: string | null
  cost_est: number
  error: string | null
  created_at: string
}

export interface ShortCreationSession {
  id: string
  status: 'active' | 'committed'
  card: Partial<ShortCreationCard>
  style_item_id: string | null
  style_name: string | null
  book_id: string | null
}

/** 会话列表项：只够画出那排可切换的会话。 */
export interface ShortCreationSummary {
  id: string
  title: string
  status: 'active' | 'committed'
  book_id: string | null
  updated_at: string
}

export interface ShortCreationPayload {
  session: ShortCreationSession
  messages: ShortCreationMessage[]
  sessions: ShortCreationSummary[]
  ready: boolean
}

export interface ShortCreationCommit {
  project_id: string
  lengths_compressed: boolean
  plan_warning: string | null
  style_name: string | null
}

export const shortCreationApi = {
  /** 页面加载：最近聊过的那条（一条都没有就新建一条）。 */
  open: (token: string, signal?: AbortSignal): Promise<ShortCreationPayload> =>
    authenticatedGet('/short/creation', token, signal),

  /** 另起一条新会话。 */
  create: (token: string, signal?: AbortSignal): Promise<ShortCreationPayload> =>
    authenticatedSend('POST', '/short/creation/sessions', token, undefined, signal),

  /** 切到已有的某条会话。 */
  openSession: (token: string, sessionId: string, signal?: AbortSignal): Promise<ShortCreationPayload> =>
    authenticatedGet(`/short/creation/sessions/${sessionId}`, token, signal),

  send: (token: string, sessionId: string, content: string, card: Record<string, unknown>,
         signal?: AbortSignal): Promise<ShortCreationPayload> =>
    authenticatedSend('POST', `/short/creation/sessions/${sessionId}/messages`, token,
                      { content, card }, signal),

  commit: (token: string, sessionId: string, card: Record<string, unknown>,
           styleItemId: string | null, signal?: AbortSignal): Promise<ShortCreationCommit> =>
    authenticatedSend('POST', `/short/creation/sessions/${sessionId}/commit`, token,
                      { card, style_item_id: styleItemId }, signal),

  remove: (token: string, sessionId: string, signal?: AbortSignal): Promise<{ ok: boolean }> =>
    authenticatedSend('DELETE', `/short/creation/sessions/${sessionId}`, token, undefined, signal),
}
