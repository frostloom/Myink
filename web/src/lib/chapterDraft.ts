// 每个标签页独立保存草稿，避免两个编辑窗口互相覆盖；按账号和章节隔离。
export interface ChapterDraft {
  content: string
  baseVersion: number
}

// 存储配额不足时仍保留本页面内的切章恢复能力；刷新前由 beforeunload 提醒。
export const liveDrafts = new Map<string, ChapterDraft>()

export function readChapterDraft(key: string): ChapterDraft | null {
  if (liveDrafts.has(key)) return liveDrafts.get(key)!
  const raw = sessionStorage.getItem(key)
  if (!raw) return null
  const value: unknown = JSON.parse(raw)
  if (typeof value !== 'object' || value === null) throw new Error('草稿格式无效')
  const draft = value as ChapterDraft
  if (typeof draft.content !== 'string' || !Number.isInteger(draft.baseVersion) || draft.baseVersion < 1) {
    throw new Error('草稿格式无效')
  }
  return draft
}
