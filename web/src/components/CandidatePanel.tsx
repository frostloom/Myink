// 待确认候选池面板（§6.11 确认分流 / §7.3 事实生命周期）：extract 候选 → 人工
// confirm/reject（编排层写库入口）→ 处理后批次/任务 resume 放行。可折叠，默认
// 有待处理候选时展开；memory_removal（记忆删除）以破坏性样式警示。
import { useState } from 'react'
import { candidateFields, candidateLabel, candidateTone } from '../lib/candidates'
import { api, ApiError } from '../lib/api'
import type { MemoryCandidate } from '../types'
import { StatusBadge } from './StatusBadge'
import styles from './CandidatePanel.module.css'

/** 放行目标：单章 awaiting_review 任务确认完候选后，从这里 resume 落库正文 */
export interface ReleaseTarget {
  taskId: string
  chapterSeq: number
}

interface Props {
  projectId: string
  candidates: MemoryCandidate[]
  onChanged: () => void
  /** 当前章 await review 确认收尾后可放行 → 空态渲染主按钮 */
  releaseTarget?: ReleaseTarget | null
  onReleased?: (taskId: string, chapterSeq: number) => void
}

type Cid = MemoryCandidate['candidate_id'] | '__release__'

export function CandidatePanel({ projectId, candidates, onChanged, releaseTarget, onReleased }: Props) {
  const [open, setOpen] = useState(candidates.length > 0)
  const [busy, setBusy] = useState<Cid | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 面板 open 初始值取自首次渲染；候选从 0 → 有 时保持用户当前折叠态（不强制弹开）
  const count = candidates.length

  async function act(action: 'confirm' | 'reject', cid: Cid) {
    if (busy) return
    setBusy(cid)
    setError(null)
    try {
      if (action === 'confirm') await api.confirmCandidate(projectId, cid)
      else await api.rejectCandidate(projectId, cid)
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.code : '操作失败')
    } finally {
      setBusy(null)
    }
  }

  // 放行本章：候选确认完后 resume 单章任务（§6.11），把 checkpoint 草稿落库为正文
  async function release() {
    if (!releaseTarget || busy) return
    setBusy('__release__')
    setError(null)
    try {
      await api.resumeBatch(releaseTarget.taskId)
      onReleased?.(releaseTarget.taskId, releaseTarget.chapterSeq)
    } catch (err) {
      setError(err instanceof ApiError ? err.code : '放行失败')
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className={`panel ${styles.panel}`}>
      <header className={styles.head}>
        <button type="button" className={styles.toggle} onClick={() => setOpen((o) => !o)}>
          <span className={styles.title}>待确认候选</span>
          {count > 0 && <span className={`badge badge-warning`}>{count}</span>}
          <span className={styles.caret}>{open ? '▾' : '▸'}</span>
        </button>
      </header>

      {error && <div className="banner banner-error">{error}</div>}

      {open && count === 0 && (
        <div className={styles.release}>
          <p className="empty">
            无待确认候选。批次 critical 冲突 / 编辑校正变更 / 新人物卡片会进入这里。
          </p>
          {releaseTarget && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy !== null}
              onClick={() => void release()}
            >
              {busy === '__release__' ? '放行中…' : `放行第 ${releaseTarget.chapterSeq} 章`}
            </button>
          )}
        </div>
      )}

      {open && count > 0 && (
        <ul className={styles.list}>
          {candidates.map((c) => (
            <li key={c.candidate_id} className={styles.item}>
              <div className={styles.meta}>
                <StatusBadge tone={candidateTone(c.kind)}>{candidateLabel(c.kind)}</StatusBadge>
                <span className={styles.chapter}>第 {c.source_chapter} 章</span>
                {c.confidence < 1 && (
                  <span className={styles.conf}>置信 {Math.round(c.confidence * 100)}%</span>
                )}
              </div>
              <dl className={styles.fields}>
                {candidateFields(c.kind, c.payload).map(([label, value]) => (
                  <div key={label} className={styles.row}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
              {c.kind === 'character_card' && (
                <p className={styles.danger}>
                  确认将在设定页新建人物卡片（身份 / 角色 / 性格），正文后续抽取会持续更新其状态。
                </p>
              )}
              {c.kind === 'memory_removal' && (
                <p className={styles.danger}>确认将按类型失效被删记忆（events 硬删 / facts 关窗），不可撤销。</p>
              )}
              <div className={styles.actions}>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busy !== null}
                  onClick={() => void act('confirm', c.candidate_id)}
                >
                  {busy === c.candidate_id ? '处理中…' : '确认落库'}
                </button>
                <button
                  type="button"
                  className="btn btn-quiet"
                  disabled={busy !== null}
                  onClick={() => void act('reject', c.candidate_id)}
                >
                  拒绝
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
