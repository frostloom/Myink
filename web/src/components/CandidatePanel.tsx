// 待确认设定：接受记忆，或保存拒绝意见后自动启动本章修订。
// 保存意见与启动任务分两次请求；失败时从持久化评审记录恢复重试入口。
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { candidateFields, candidateLabel, candidateTone } from '../lib/candidates'
import { api } from '../lib/api'
import type { ChapterStatus, MemoryCandidate } from '../types'
import { StatusBadge } from './StatusBadge'
import styles from './CandidatePanel.module.css'

/** 放行目标：单章 awaiting_review 任务确认完候选后，从这里 resume 完成记忆与章节状态 */
export interface ReleaseTarget {
  taskId: string
  chapterSeq: number
  batchSize?: number
}

interface Props {
  projectId: string
  /** 右栏只展示当前选中章节的候选和评审记录。未传时保留组件独立测试兼容。 */
  chapterSeq?: number | null
  chapterStatus?: ChapterStatus | null
  candidates: MemoryCandidate[]
  onChanged: () => void
  /** 当前章 await review 确认收尾后可放行 → 空态渲染主按钮 */
  releaseTarget?: ReleaseTarget | null
  onReleased?: (taskId: string, chapterSeq: number, batchSize?: number) => void
  /** 将人物、实体和伏笔 UUID 转成人可读名称。 */
  referenceNames?: Readonly<Record<string, string>>
}

type Cid = MemoryCandidate['candidate_id'] | '__release__'

export function CandidatePanel({ projectId, chapterSeq, chapterStatus, candidates: projectCandidates, onChanged, releaseTarget, onReleased, referenceNames = {} }: Props) {
  const allCandidates = chapterSeq == null
    ? projectCandidates
    : projectCandidates.filter((candidate) => candidate.source_chapter === chapterSeq)
  const currentReleaseTarget = releaseTarget && (chapterSeq == null || releaseTarget.chapterSeq === chapterSeq)
    ? releaseTarget
    : null
  // 启动修改后立即收起旧稿候选，避免快照刷新前再次操作同一稿。
  const [submittedIds, setSubmittedIds] = useState<string[]>([])
  const candidates = allCandidates.filter((c) => c.status === 'pending' && !submittedIds.includes(c.candidate_id))
  const history = allCandidates.filter((c) => c.status !== 'pending').slice(-20).reverse()
  const [open, setOpen] = useState(candidates.length > 0)
  const [busy, setBusy] = useState<Cid | null>(null)
  const [reason, setReason] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [retryChapter, setRetryChapter] = useState<number | null>(null)
  const retryChapters = [...new Set([
    ...(retryChapter === null ? [] : [retryChapter]),
    ...allCandidates.filter((c) => c.status === 'rejected' && c.review?.mode === 'revise'
      && !c.review.applied && !submittedIds.includes(c.candidate_id)).map((c) => c.source_chapter),
  ])]
  // 面板 open 初始值取自首次渲染；候选从 0 → 有 时保持用户当前折叠态（不强制弹开）
  const count = candidates.length
  const actionable = count > 0 || currentReleaseTarget !== null || retryChapters.length > 0
  const hasHistory = history.length > 0
  const hasShownCandidates = useRef(count > 0)
  const actionKey = actionable
    ? `${chapterSeq ?? 'all'}:${candidates.map((candidate) => candidate.candidate_id).join(',')}:${retryChapters.join(',')}:${currentReleaseTarget?.taskId ?? ''}`
    : ''
  const previousActionKey = useRef(actionKey)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const [reviewOpen, setReviewOpen] = useState(actionable)

  // 首次异步加载到待确认项时自动展开；用户之后主动折叠时不再抢回展开状态。
  useEffect(() => {
    if (count > 0 && !hasShownCandidates.current) {
      hasShownCandidates.current = true
      setOpen(true)
    }
  }, [count])

  // 新一轮待确认到达时自动提醒；用户主动关闭后，本轮不反复抢回焦点。
  useEffect(() => {
    if (actionKey && actionKey !== previousActionKey.current) setReviewOpen(true)
    if (!actionKey) setReviewOpen(false)
    previousActionKey.current = actionKey
  }, [actionKey])

  // 最后一条候选处理并成功放行后，父级会清掉 releaseTarget。此时旧的“任务正在继续”
  // 提示已经过期，应自动收起并切换为历史记录状态，避免完成章仍看起来在待确认。
  useEffect(() => {
    if (actionable || chapterStatus !== 'confirmed') return
    setNotice('')
    setError(null)
    setOpen(false)
  }, [actionable, chapterStatus])

  async function findTarget(chapterSeq: number, retry = false): Promise<ReleaseTarget> {
    // 候选池跨章节；不能直接续跑编辑器当前选中章，也不能从旧任务中挑一个恢复。
    const [latest] = await api.listTasks(projectId, chapterSeq)
    const allowed = retry ? ['awaiting_review', 'failed', 'paused', 'queued'] : ['awaiting_review']
    if (!latest || !allowed.includes(latest.status)) {
      throw new Error(`第 ${chapterSeq} 章当前没有可修改的待评审任务，请刷新任务状态。`)
    }
    if (latest.task_type === 'batch_generate') {
      const detail = await api.getTask(latest.task_id)
      const currentChapter = Number(detail.payload.start) + (detail.progress?.current ?? 0)
      if (currentChapter !== chapterSeq) throw new Error('这条候选不属于批次当前待处理章节，请刷新候选列表。')
    }
    return { taskId: latest.task_id, chapterSeq, batchSize: latest.batch_size ?? undefined }
  }

  async function startRevision(target: ReleaseTarget) {
    await api.resumeBatch(target.taskId)
    setSubmittedIds((ids) => [...ids, ...allCandidates.filter((c) => c.source_chapter === target.chapterSeq).map((c) => c.candidate_id)])
    setRetryChapter(null)
    setReason('')
    setNotice(`第 ${target.chapterSeq} 章已提交自动修改，系统会检查修改后的内容，进度见任务区。`)
    setReviewOpen(false)
    onReleased?.(target.taskId, target.chapterSeq, target.batchSize)
    onChanged()
  }

  async function act(action: 'confirm' | 'reject', candidate: MemoryCandidate) {
    if (busy) return
    const cid = candidate.candidate_id
    setBusy(cid)
    setError(null)
    setNotice('')
    let rejectionSaved = false
    try {
      if (action === 'confirm') {
        await api.confirmCandidate(projectId, cid)
        setSubmittedIds((ids) => [...ids, cid])
        const isLastPending = candidates.every((item) => item.candidate_id === cid)
        if (isLastPending && currentReleaseTarget) {
          try {
            await api.resumeBatch(currentReleaseTarget.taskId)
            setNotice(`第 ${currentReleaseTarget.chapterSeq} 章设定已确认，任务正在继续。`)
            setReviewOpen(false)
            onReleased?.(currentReleaseTarget.taskId, currentReleaseTarget.chapterSeq, currentReleaseTarget.batchSize)
          } catch {
            setError('设定已接受，但任务未能继续。请点“重试完成确认”，无需再次接受。')
          }
        } else {
          const remaining = Math.max(0, candidates.length - 1)
          setNotice(remaining > 0 ? `已接受这条设定，还有 ${remaining} 条待确认。` : '已接受这条设定。')
        }
      } else {
        const target = await findTarget(candidate.source_chapter)
        await api.rejectCandidate(projectId, cid, reason, 'revise')
        rejectionSaved = true
        setRetryChapter(candidate.source_chapter)
        await startRevision(target)
      }
      onChanged()
    } catch (err) {
      setError(rejectionSaved ? '意见已保存，但自动修改未能启动。请点“重试修改”，无需再次拒绝。'
        : err instanceof Error ? err.message : '操作失败')
      // 请求响应丢失时，服务端可能已保存意见；刷新后也能找回重试入口。
      onChanged()
    } finally {
      setBusy(null)
    }
  }

  async function retryRevision(chapterSeq: number) {
    if (busy) return
    setBusy('__release__')
    setError(null)
    try {
      await startRevision(await findTarget(chapterSeq, true))
    } catch (err) {
      setError(err instanceof Error ? err.message : '启动修改失败，请重试')
    } finally {
      setBusy(null)
    }
  }

  // 放行本章：正文已在待确认阶段可见；候选确认完后 resume 完成记忆与章节状态。
  async function release() {
    if (!currentReleaseTarget || busy) return
    setBusy('__release__')
    setError(null)
    try {
      await api.resumeBatch(currentReleaseTarget.taskId)
      setNotice(`第 ${currentReleaseTarget.chapterSeq} 章设定已确认，任务正在继续。`)
      setReviewOpen(false)
      onReleased?.(currentReleaseTarget.taskId, currentReleaseTarget.chapterSeq, currentReleaseTarget.batchSize)
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : '接受本章失败')
    } finally {
      setBusy(null)
    }
  }

  useEffect(() => {
    if (!reviewOpen) return
    const previousOverflow = document.body.style.overflow
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    document.body.style.overflow = 'hidden'
    closeButtonRef.current?.focus()
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && busy === null) setReviewOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKeyDown)
      previousFocus?.focus()
    }
  }, [reviewOpen, busy])

  return (
    <>
      <section className={`panel ${styles.panel}`} aria-label="设定评审侧栏">
        <header className={styles.head}>
          <button type="button" className={styles.toggle} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            <span className={styles.headingGroup}>
              <span className={styles.title}>{actionable ? '设定确认' : '设定记录'}</span>
              {chapterSeq != null && <span className={styles.chapter}>第 {chapterSeq} 章</span>}
            </span>
            <span className={styles.headerMeta}>
              {count > 0 && <span className="badge badge-warning">{count} 项</span>}
              {count === 0 && (currentReleaseTarget || retryChapters.length > 0) && <span className="badge badge-warning">待处理</span>}
              {!actionable && hasHistory && <span className="badge badge-success">已完成</span>}
              <span className={styles.caret}>{open ? '▾' : '▸'}</span>
            </span>
          </button>
        </header>

        {open && notice && <p role="status" className={styles.notice}>{notice}</p>}
        {open && history.length > 0 && <details className={styles.history}><summary>最近评审记录（{history.length}）</summary>
          {history.map((c) => <p key={c.candidate_id}>第 {c.source_chapter} 章 · {candidateLabel(c.kind)} · {c.status === 'confirmed' ? '已确认' : c.review?.superseded ? '旧稿候选已作废' : c.review?.mode === 'revise' ? (c.review.applied ? '已按意见修订并复审' : '等待按意见修订') : '仅拒绝记忆入库'}
            {c.review?.reason && `：${c.review.reason}`}</p>)}
        </details>}
        {open && !reviewOpen && error && <div className="banner banner-error">{error}</div>}
        {open && (
          <div className={styles.release}>
            <p className="empty">
              {actionable ? '本章有设定需要处理，操作会在页面中央的确认窗口中完成。' : '本章没有待确认的设定。'}
            </p>
            {actionable && (
              <button type="button" className="btn btn-primary" onClick={() => setReviewOpen(true)}>
                {count > 0 ? `处理 ${count} 项设定` : '继续处理'}
              </button>
            )}
          </div>
        )}
      </section>

      {reviewOpen && actionable && createPortal(
        <div
          className={styles.modalBackdrop}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && busy === null) setReviewOpen(false)
          }}
        >
          <section
            className={styles.modal}
            role="dialog"
            aria-modal="true"
            aria-labelledby="candidate-review-title"
          >
            <header className={styles.modalHead}>
              <div>
                <h2 id="candidate-review-title">设定确认</h2>
                <p>{chapterSeq != null ? `第 ${chapterSeq} 章` : '当前章节'} · {count > 0 ? `${count} 项待处理` : '继续未完成操作'}</p>
              </div>
              <button
                ref={closeButtonRef}
                type="button"
                className={styles.modalClose}
                aria-label="暂后处理"
                disabled={busy !== null}
                onClick={() => setReviewOpen(false)}
              >
                ×
              </button>
            </header>

            <div className={styles.modalBody}>
              <p className={styles.modalHint}>
                {count > 0
                  ? '接受会保存设定；不接受会按你的意见自动修改本章，然后重新检查。'
                  : '上一次结果已经保存，可以继续未完成的后续步骤。'}
              </p>
              {error && <div className="banner banner-error">{error}</div>}
              {retryChapters.map((seq) => (
                <button key={seq} type="button" className="btn btn-primary"
                  disabled={busy !== null} onClick={() => void retryRevision(seq)}>
                  {busy === '__release__' ? '处理中…' : `重试修改第 ${seq} 章`}
                </button>
              ))}
              {currentReleaseTarget && !retryChapters.includes(currentReleaseTarget.chapterSeq)
                && count === 0 && (
                <button type="button" className="btn btn-primary" disabled={busy !== null} onClick={() => void release()}>
                  {busy === '__release__' ? '处理中…' : '重试完成确认'}
                </button>
              )}

              {count > 0 && (
                <label className={styles.reasonField}>
                  <span>修改意见（可选）</span>
                  <input className="input" value={reason} disabled={busy !== null} maxLength={2000}
                    onChange={(e) => setReason(e.target.value)} placeholder="例如：人物仍然受伤，需要治疗过程" />
                </label>
              )}
              {count > 0 && (
                <ul className={styles.list}>
                  {candidates.map((c) => (
                    <li key={c.candidate_id} className={styles.item}>
                      <div className={styles.meta}>
                        <StatusBadge tone={candidateTone(c.kind)}>{candidateLabel(c.kind)}</StatusBadge>
                        <span className={styles.chapter}>第 {c.source_chapter} 章</span>
                        {c.confidence < 1 && <span className={styles.conf}>置信 {Math.round(c.confidence * 100)}%</span>}
                      </div>
                      <dl className={styles.fields}>
                        {candidateFields(c.kind, c.payload, referenceNames).map(([label, value]) => (
                          <div key={label} className={styles.row}><dt>{label}</dt><dd>{value}</dd></div>
                        ))}
                      </dl>
                      {c.kind === 'character_card' && (
                        <p className={styles.danger}>确认将在设定页新建人物卡片（身份 / 角色 / 性格），正文后续抽取会持续更新其状态。</p>
                      )}
                      {c.kind === 'memory_removal' && (
                        <p className={styles.danger}>确认将按类型失效被删记忆（events 硬删 / facts 关窗），不可撤销。</p>
                      )}
                      <div className={styles.actions}>
                        <button type="button" className="btn btn-primary"
                          disabled={busy !== null || retryChapters.includes(c.source_chapter)}
                          onClick={() => void act('confirm', c)}>
                          {busy === c.candidate_id ? '处理中…' : '接受'}
                        </button>
                        <button type="button" className="btn btn-quiet"
                          disabled={busy !== null || retryChapters.includes(c.source_chapter)}
                          onClick={() => void act('reject', c)}>
                          不接受，自动修改
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </div>,
        document.body,
      )}
    </>
  )
}
