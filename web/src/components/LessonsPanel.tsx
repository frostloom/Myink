// 写作经验面板（§8.9 reflexion：批次收尾复盘高危经验 → 待确认池 → 人工确认/拒绝）。
// proposed 显示 confirm/reject；active/rejected 灰显只读 + 复发次数徽标。确认后经验
// 随下一批 recall 注入后续章节规划/写作（越写越懂这本书）。
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { WritingLesson } from '../types'
import { StatusBadge } from './StatusBadge'
import styles from './LessonsPanel.module.css'

interface Props {
  projectId: string
}

type LessonStatus = WritingLesson['status']

const STATUS_TONE: Record<LessonStatus, 'accent' | 'success' | 'hint'> = {
  proposed: 'accent',
  active: 'success',
  rejected: 'hint',
}

const STATUS_LABEL: Record<LessonStatus, string> = {
  proposed: '待确认',
  active: '已生效',
  rejected: '已拒绝',
}

export function LessonsPanel({ projectId }: Props) {
  const [open, setOpen] = useState(true)
  const [lessons, setLessons] = useState<WritingLesson[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    api.listLessons(projectId)
      .then((list) => { if (alive) setLessons(list) })
      .catch(() => { if (alive) setLessons([]) })
    return () => { alive = false }
  }, [projectId])

  const pending = lessons.filter((l) => l.status === 'proposed').length

  async function act(action: 'confirm' | 'reject', lid: string) {
    if (busy) return
    setBusy(lid)
    setError(null)
    try {
      if (action === 'confirm') await api.confirmLesson(projectId, lid)
      else await api.rejectLesson(projectId, lid)
      const list = await api.listLessons(projectId).catch(() => [])
      setLessons(list)
    } catch (err) {
      setError(err instanceof ApiError ? err.code : '操作失败')
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className={`panel ${styles.panel}`}>
      <header className={styles.head}>
        <button type="button" className={styles.toggle} onClick={() => setOpen((o) => !o)}>
          <span className={styles.title}>写作经验</span>
          {pending > 0 && <span className="badge badge-warning">{pending}</span>}
          <span className={styles.caret}>{open ? '▾' : '▸'}</span>
        </button>
      </header>

      {error && <div className="banner banner-error">{error}</div>}

      {open && lessons.length === 0 && (
        <p className="empty">暂无写作经验。批次收尾 reflexion 复盘出的高危经验会出现在这里。</p>
      )}

      {open && lessons.length > 0 && (
        <ul className={styles.list}>
          {lessons.map((l) => (
            <li key={l.lesson_id} className={styles.item}>
              <div className={styles.meta}>
                <StatusBadge tone={STATUS_TONE[l.status] ?? 'hint'}>
                  {STATUS_LABEL[l.status] ?? l.status}
                </StatusBadge>
                <span className={styles.chapter}>第 {l.source_chapter} 章</span>
                {l.recurrence_count > 0 && (
                  <span className={`badge badge-warning`}>复发 ×{l.recurrence_count}</span>
                )}
              </div>
              <p className={styles.content}>{l.content}</p>
              {l.status === 'proposed' && (
                <div className={styles.actions}>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busy !== null}
                    onClick={() => void act('confirm', l.lesson_id)}
                  >
                    {busy === l.lesson_id ? '处理中…' : '确认生效'}
                  </button>
                  <button
                    type="button"
                    className="btn btn-quiet"
                    disabled={busy !== null}
                    onClick={() => void act('reject', l.lesson_id)}
                  >
                    拒绝
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
