// 章节历史版本弹层（阶段 4 版本表）：列历史 → 预览全文 → 回退。
// 语义：chapters 是当前实时版本（列表顶部标出）；历史行是每次覆盖写前的快照，
// 回退会把当前再留痕（revert）并覆盖回目标版本。
import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import type { ChapterVersion, ContentUpdateResponse } from '../types'
import styles from './VersionHistory.module.css'

const REASON_LABELS: Record<string, string> = {
  manual: '手动保存',
  batch: '批次生成',
  revise: '修订',
  revert: '回退',
  edit: '编辑',
}

interface Props {
  projectId: string
  chapterId: string
  chapterSeq: number
  onClose: () => void
  /** 回退成功 → 编辑器就地更新正文/版本（无需重新拉取） */
  onRestored: (target: ChapterVersion, resp: ContentUpdateResponse) => void
}

export function VersionHistory({ projectId, chapterId, chapterSeq, onClose, onRestored }: Props) {
  const [versions, setVersions] = useState<ChapterVersion[]>([])
  const [currentVersion, setCurrentVersion] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [restoring, setRestoring] = useState<number | null>(null)

  useEffect(() => {
    let alive = true
    api
      .listChapterVersions(projectId, chapterId)
      .then((res) => {
        if (!alive) return
        setVersions(res.versions)
        setCurrentVersion(res.current_version)
        setLoading(false)
      })
      .catch((err) => {
        if (!alive) return
        setError(formatApiError(err, '加载失败'))
        setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [projectId, chapterId])

  async function restore(v: ChapterVersion) {
    if (restoring !== null) return
    if (!window.confirm(`确认回退到 v${v.version}？当前正文将覆盖为历史内容（回退本身也会留痕）。`)) {
      return
    }
    setRestoring(v.version)
    setError(null)
    try {
      const resp = await api.restoreChapterVersion(projectId, chapterId, v.version)
      onRestored(v, resp)
    } catch (err) {
      setError(formatApiError(err, '回退失败'))
    } finally {
      setRestoring(null)
    }
  }

  return (
    <div className={styles.backdrop} onMouseDown={onClose}>
      <div
        className={styles.card}
        role="dialog"
        aria-label="版本历史"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className={styles.head}>
          <h3 className={styles.title}>版本历史 · 第 {chapterSeq} 章</h3>
          <button type="button" className="btn btn-quiet" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </header>

        {error && <div className="banner banner-error">{error}</div>}

        {loading ? (
          <div className="empty">加载中…</div>
        ) : (
          <>
            <div className={styles.current}>
              当前 <strong>v{currentVersion ?? '-'}</strong>
              <span className={styles.muted}>（实时版本，不在下列历史中）</span>
            </div>
            {versions.length === 0 ? (
              <div className="empty">暂无历史版本——每次保存/生成前自动留痕</div>
            ) : (
              <ul className={styles.list}>
                {versions.map((v) => (
                  <li key={v.version} className={styles.row}>
                    <div className={styles.rowTop}>
                      <span className={styles.badge}>v{v.version}</span>
                      <span className={styles.reason}>
                        {REASON_LABELS[v.reason] ?? v.reason}
                      </span>
                      <span className={styles.date}>
                        {v.created_at ? new Date(v.created_at).toLocaleString('zh-CN') : ''}
                      </span>
                    </div>
                    {(v.title || v.summary) && (
                      <div className={styles.meta}>
                        {v.title && <span className={styles.titleLine}>{v.title}</span>}
                        {v.summary && <span className={styles.summary}>{v.summary}</span>}
                      </div>
                    )}
                    <div className={styles.excerpt}>{v.content?.slice(0, 120) ?? '（空）'}</div>
                    <details className={styles.detail}>
                      <summary>预览全文</summary>
                      <pre className={styles.full}>{v.content ?? ''}</pre>
                    </details>
                    <div className={styles.rowFoot}>
                      <button
                        type="button"
                        className="btn btn-quiet"
                        disabled={restoring !== null}
                        onClick={() => void restore(v)}
                      >
                        {restoring === v.version ? '回退中…' : '回退到此版本'}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </div>
  )
}
