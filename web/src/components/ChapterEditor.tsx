// 章节编辑器：读正文（GET 单章详情）→ 纸张色 textarea → Ctrl+S / 按钮保存（PUT content 轻编辑）。
// 阶段 4：头部「历史版本」入口 → 版本列表/回退弹层（覆盖写前快照，版本表）。
import { useEffect, useState, type KeyboardEvent } from 'react'
import { api, ApiError } from '../lib/api'
import { chapterStatusLabel, chapterStatusTone } from '../lib/labels'
import type { ChapterDetail, ChapterMeta, ChapterVersion, ContentUpdateResponse } from '../types'
import { StatusBadge } from './StatusBadge'
import { VersionHistory } from './VersionHistory'
import styles from './ChapterEditor.module.css'

interface Props {
  projectId: string
  chapter: ChapterMeta
  /** 章节不存在（404，可能被级联删除）→ 由父级刷新列表并清空选择 */
  onNotFound: () => void
  /** 保存成功 → 父级可刷新章节列表（status/version 变化） */
  onSaved: () => void
  /** 记忆校正生成变更集进待确认池 → 父级重载候选池 */
  onMemoryChanged: () => void
  /** 生成任务终态后自增 → 重新拉取正文（同章再生内容已更新） */
  refreshTick?: number
}

export function ChapterEditor({
  projectId,
  chapter,
  onNotFound,
  onSaved,
  onMemoryChanged,
  refreshTick = 0,
}: Props) {
  const [detail, setDetail] = useState<ChapterDetail | null>(null)
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [memBusy, setMemBusy] = useState(false)
  const [delBusy, setDelBusy] = useState(false)
  const [memBanner, setMemBanner] = useState<string | null>(null)
  const [version, setVersion] = useState<number | null>(null)
  const [showHistory, setShowHistory] = useState(false)

  useEffect(() => {
    let alive = true
    setLoaded(false)
    setDetail(null)
    setContent('')
    setDirty(false)
    setError(null)
    setVersion(null)
    api
      .getChapter(projectId, chapter.id)
      .then((d) => {
        if (!alive) return
        setDetail(d)
        setContent(d.content ?? '')
        setLoaded(true)
      })
      .catch((err) => {
        if (!alive) return
        if (err instanceof ApiError && err.status === 404) {
          onNotFound()
          return
        }
        setError(err instanceof ApiError ? err.code : '加载失败')
        setLoaded(true)
      })
    return () => {
      alive = false
    }
  }, [projectId, chapter.id, onNotFound, refreshTick])

  async function save() {
    if (saving) return
    setSaving(true)
    setError(null)
    try {
      const resp = await api.updateContent(projectId, chapter.id, content)
      setVersion(resp.version)
      setDirty(false)
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.code : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  // 内联 handler：每次渲染取最新 save/content，避免 useCallback 闭包存陈旧正文
  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault()
      if (dirty) void save()
    }
  }

  // 回退成功：就地覆盖编辑器正文/版本（restore 已持久化，无需重拉），版本列表随之变化
  function handleRestored(target: ChapterVersion, resp: ContentUpdateResponse) {
    setContent(target.content ?? '')
    setVersion(resp.version)
    setDirty(false)
    setShowHistory(false)
    onSaved()
  }

  // 校正记忆（§7.3）：编辑后正文重新抽取 → 与该章已落库记忆 diff → 变更集进待确认池。
  // 同步 LLM 调用（一次 extract），超时/失败可重试；no_op = 纯风格编辑无记忆差异。
  async function correctMemory() {
    if (memBusy) return
    setMemBusy(true)
    setError(null)
    setMemBanner(null)
    try {
      const resp = await api.correctMemory(projectId, chapter.id)
      setMemBanner(
        resp.no_op
          ? '无记忆变更（正文与已落库记忆一致）。'
          : '已生成变更集，进入「待确认候选」池。',
      )
      onMemoryChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.code : '校正失败')
    } finally {
      setMemBusy(false)
    }
  }

  // 级联删除本章及之后全部章节（正文 + 记忆 + 池候选，进度回退），不可撤销
  async function deleteChapter() {
    if (delBusy) return
    if (
      !window.confirm(
        `删除第 ${chapter.chapter_seq} 章及其后全部章节？正文、记忆与待确认候选将一并移除，不可撤销。`,
      )
    ) {
      return
    }
    setDelBusy(true)
    setError(null)
    try {
      await api.deleteChapter(projectId, chapter.id)
      onNotFound()
    } catch (err) {
      setError(err instanceof ApiError ? err.code : '删除失败')
    } finally {
      setDelBusy(false)
    }
  }

  return (
    <div className={styles.editor}>
      <header className={styles.head}>
        <div className={styles.headRow}>
          <h2 className={styles.title}>
            第 {chapter.chapter_seq} 章{detail?.title ? ` · ${detail.title}` : ''}
          </h2>
          {loaded && (
            <div className={styles.actions}>
              <button
                type="button"
                className="btn btn-quiet"
                disabled={memBusy || delBusy}
                onClick={() => void correctMemory()}
              >
                {memBusy ? '校正中…' : '校正记忆'}
              </button>
              <button
                type="button"
                className={`btn ${styles.danger}`}
                disabled={memBusy || delBusy}
                onClick={() => void deleteChapter()}
              >
                {delBusy ? '删除中…' : '删除本章'}
              </button>
              <button
                type="button"
                className="btn btn-quiet"
                onClick={() => setShowHistory(true)}
              >
                历史版本
              </button>
            </div>
          )}
        </div>
        <div className={styles.metaRow}>
          <StatusBadge tone={chapterStatusTone(chapter.status)}>
            {chapterStatusLabel(chapter.status)}
          </StatusBadge>
          {version !== null && <span className={styles.version}>v{version}</span>}
          {detail?.summary && <span className={styles.summary}>{detail.summary}</span>}
        </div>
      </header>

      {error && <div className="banner banner-error">{error}</div>}
      {memBanner && <div className="banner">{memBanner}</div>}

      {!loaded ? (
        <div className="empty">加载中…</div>
      ) : (
        <>
          <textarea
            className={styles.textarea}
            value={content}
            onChange={(e) => {
              setContent(e.target.value)
              setDirty(true)
            }}
            onKeyDown={onKeyDown}
            spellCheck={false}
            placeholder="章节正文…（Ctrl+S 保存）"
          />
          <footer className={styles.foot}>
            <span className={dirty ? styles.dirty : styles.saved}>
              {dirty ? '未保存修改' : '已保存'}
            </span>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void save()}
              disabled={!dirty || saving}
            >
              {saving ? '保存中…' : '保存'}
            </button>
          </footer>
        </>
      )}

      {showHistory && (
        <VersionHistory
          projectId={projectId}
          chapterId={chapter.id}
          chapterSeq={chapter.chapter_seq}
          onClose={() => setShowHistory(false)}
          onRestored={handleRestored}
        />
      )}
    </div>
  )
}
