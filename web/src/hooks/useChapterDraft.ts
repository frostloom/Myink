import { useCallback, useEffect, useRef, useState } from 'react'
import { useBlocker } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { liveDrafts, readChapterDraft, type ChapterDraft } from '../lib/chapterDraft'
import type { ChapterDetail } from '../types'

// ChapterEditor 按账号/项目/章节 key 重挂载，异步结果不能进入另一章。
export function useChapterDraft(key: string, projectId: string, chapterId: string,
  refreshTick: number, onNotFound: () => void, onSaved: () => void) {
  const [detail, setDetail] = useState<ChapterDetail | null>(null)
  const [draft, setDraft] = useState<ChapterDraft | null>(null)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [backupError, setBackupError] = useState(false)
  const [conflict, setConflict] = useState(false)
  const current = useRef<{ draft: ChapterDraft | null; dirty: boolean }>({ draft: null, dirty: false })
  const mounted = useRef(false)
  const savingRef = useRef(false)
  const readId = useRef(0)

  const putDraft = useCallback((next: ChapterDraft, changed: boolean) => {
    current.current = { draft: next, dirty: changed }
    setDraft(next)
    setDirty(changed)
    if (changed) liveDrafts.set(key, next)
    else liveDrafts.delete(key)
    try {
      if (changed) sessionStorage.setItem(key, JSON.stringify(next))
      else sessionStorage.removeItem(key)
      setBackupError(false)
    } catch {
      setBackupError(true)
    }
  }, [key])

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  useEffect(() => {
    const id = ++readId.current
    let alive = true
    setError(null)
    api.getChapter(projectId, chapterId).then((remote) => {
      if (!alive || !mounted.current || id !== readId.current) return
      setDetail(remote)
      let local = current.current.dirty ? current.current.draft : null
      if (!current.current.draft) {
        try { local = readChapterDraft(key) } catch { setBackupError(true) }
      }
      if (local && local.content !== (remote.content ?? '')) {
        putDraft(local, true)
        setConflict(local.baseVersion !== remote.version)
      } else {
        putDraft({ content: remote.content ?? '', baseVersion: remote.version }, false)
        setConflict(false)
      }
    }).catch((err: unknown) => {
      if (!alive || !mounted.current || id !== readId.current) return
      if (err instanceof ApiError && err.status === 404) onNotFound()
      else setError('正文加载失败，请稍后重新打开。已有草稿仍保留在本标签页。')
    })
    return () => { alive = false }
  }, [key, projectId, chapterId, refreshTick, onNotFound, putDraft])

  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  // 存储失败时禁止静默离开；正常切章由标签页草稿自动恢复。
  const blocker = useBlocker(dirty && backupError)

  function edit(content: string) {
    const old = current.current.draft
    if (old) putDraft({ ...old, content }, true)
  }

  async function save(expectedVersion?: number) {
    const submitted = current.current.draft
    if (!submitted || savingRef.current) return
    savingRef.current = true
    setSaving(true)
    setError(null)
    try {
      const resp = await api.updateContent(projectId, chapterId, submitted.content,
        expectedVersion ?? submitted.baseVersion)
      ++readId.current // 丢弃保存前发起的读请求，防旧响应倒灌。
      const latest = current.current.draft ?? submitted
      const next = { content: latest.content, baseVersion: resp.version }
      const changed = latest.content !== submitted.content
      // 已离开的编辑器不清理存储：同一章可能已重新打开并产生更新的草稿。
      // 下次读取服务器正文时会自动辨认已保存的草稿，或提示版本冲突。
      if (!mounted.current) return
      putDraft(next, changed)
      setDetail((old) => old ? { ...old, content: submitted.content, version: resp.version } : old)
      setConflict(false)
      onSaved()
    } catch (err) {
      if (!mounted.current) return
      if (err instanceof ApiError && err.status === 409) {
        setConflict(true)
        setError('服务器正文已更新，草稿未覆盖。请查看最新正文后选择如何处理。')
        try {
          const remote = await api.getChapter(projectId, chapterId)
          if (mounted.current) setDetail(remote)
        } catch { /* 不改变旧 baseVersion，后续提交仍须通过版本检查 */ }
      } else setError('保存失败，草稿已保留，请重试。')
    } finally {
      savingRef.current = false
      if (mounted.current) setSaving(false)
    }
  }

  function acceptRemote() {
    if (!detail || savingRef.current || !window.confirm('放弃当前未提交的草稿，载入服务器正文？')) return
    putDraft({ content: detail.content ?? '', baseVersion: detail.version }, false)
    setConflict(false)
    setError(null)
  }

  return { detail, draft, dirty, saving, error, backupError, conflict, blocker,
    edit, save, acceptRemote }
}
