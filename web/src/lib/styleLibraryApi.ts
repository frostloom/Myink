/** 账号级文风库：列 / 导入文章提取 / 命名保存 / 改名改备注 / 删除。
 *
 * 路径不带 /api/v1 —— lib/api 的 request() 已经把 BASE 拼在前面，这里再带一次就是两层前缀。
 * 认证与账号切换中止复用同一套语义（与 adminApi 同款）。
 */
import { authenticatedGet, authenticatedSend } from './api'

export interface StyleLibraryItem {
  id: string                    // uuid 字符串，或内置预设的 "builtin:<preset_id>"
  name: string
  profile: Record<string, unknown>
  note: string
  sample_chars: number
  created_at: string | null     // 内置预设没有时间戳
  builtin: boolean
  removable: boolean
}

export interface StyleDraft {
  draft: Record<string, unknown>
}

export interface StyleLibrarySaveBody {
  name: string
  profile: Record<string, unknown>
  note?: string
  sample_chars?: number
}

export interface StyleLibraryPatchBody {
  name?: string
  note?: string
}

export const styleLibraryApi = {
  list: (token: string, signal?: AbortSignal): Promise<{ items: StyleLibraryItem[] }> =>
    authenticatedGet('/style-library', token, signal),

  extract: (token: string, samples: string[], signal?: AbortSignal): Promise<StyleDraft> =>
    authenticatedSend('POST', '/style-library/samples', token, { samples }, signal),

  save: (token: string, body: StyleLibrarySaveBody, signal?: AbortSignal): Promise<StyleLibraryItem> =>
    authenticatedSend('POST', '/style-library', token, body, signal),

  // 改名 / 改备注：没传的字段不动，所以调用点只给要改的那个键。
  patch: (token: string, itemId: string, body: StyleLibraryPatchBody,
          signal?: AbortSignal): Promise<StyleLibraryItem> =>
    authenticatedSend('PATCH', `/style-library/${itemId}`, token, body, signal),

  remove: (token: string, itemId: string, signal?: AbortSignal): Promise<{ ok: boolean }> =>
    authenticatedSend('DELETE', `/style-library/${itemId}`, token, undefined, signal),
}
