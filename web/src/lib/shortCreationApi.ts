/** 对话式短篇建书：取会话 / 发一句 / 确认开写 / 重新开始。
 *
 * commit 只落书不出稿——入队走既有的 POST /projects/{id}/short/generate，
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

export interface ShortCreationPayload {
  session: ShortCreationSession
  messages: ShortCreationMessage[]
  ready: boolean
}

export interface ShortCreationCommit {
  project_id: string
  lengths_compressed: boolean
  plan_warning: string | null
  style_name: string | null
}

export const shortCreationApi = {
  get: (token: string, signal?: AbortSignal): Promise<ShortCreationPayload> =>
    authenticatedGet('/short/creation', token, signal),

  send: (token: string, content: string, card: Record<string, unknown>, signal?: AbortSignal):
    Promise<ShortCreationPayload> =>
    authenticatedSend('POST', '/short/creation/messages', token, { content, card }, signal),

  commit: (token: string, card: Record<string, unknown>, styleItemId: string | null, signal?: AbortSignal):
    Promise<ShortCreationCommit> =>
    authenticatedSend('POST', '/short/creation/commit', token,
                      { card, style_item_id: styleItemId }, signal),

  reset: (token: string, signal?: AbortSignal): Promise<{ ok: boolean }> =>
    authenticatedSend('DELETE', '/short/creation', token, undefined, signal),
}
