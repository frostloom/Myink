// 项目任务历史面板（阶段 4 任务视图）：切书后列出该书过往任务；点开任一条拉详情 →
// 节点流转记录（RunNodeCard 逐节点 token/成本/耗时）+ 批次进度 + pause/resume/cancel 控制。
// 实时流转仍走上方 TaskTimeline（SSE），此处管历史快照（根因 2/3：换书看任务 + 流转记录）。
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { taskStatusLabel, taskStatusTone, taskTypeLabel } from '../lib/labels'
import type { AgentRun, TaskDetail, TaskStatus, TaskSummary } from '../types'
import { RunNodeCard } from './RunNodeCard'
import { StatusBadge } from './StatusBadge'
import styles from './TaskHistory.module.css'

interface Props {
  projectId: string
  /** 当前活动任务（SSE 实时时间线）；命中该行高亮「进行中」 */
  activeTaskId: string | null
}

type BatchAction = 'pause' | 'resume' | 'cancel'

const ACTION_LABEL: Record<BatchAction, string> = {
  pause: '暂停',
  resume: '续跑',
  cancel: '取消',
}

// 可控制状态（同 TaskTimeline STATUS_ACTIONS 口径；awaiting_review 确认候选后 resume 放行）
const STATUS_ACTIONS: Partial<Record<TaskStatus, BatchAction[]>> = {
  paused: ['resume', 'cancel'],
  queued: ['pause', 'cancel'],
  running: ['pause', 'cancel'],
  awaiting_review: ['resume'],
}

/** 行目标文案：批次 → N 章 + i/N；单章 → 第 N 章 */
function targetLabel(t: TaskSummary): string {
  if (t.task_type === 'batch_generate') {
    const size = t.batch_size ?? 0
    const current = t.batch_current
    return `批次${size > 0 ? ` ${size} 章` : ''}${current !== null && size > 0 ? ` · ${current}/${size}` : ''}`
  }
  return t.chapter_seq !== null ? `第 ${t.chapter_seq} 章` : ''
}

export function TaskHistory({ projectId, activeTaskId }: Props) {
  const [open, setOpen] = useState(true)
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [openTaskId, setOpenTaskId] = useState<string | null>(null)
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ctrl, setCtrl] = useState<BatchAction | null>(null)

  // 切书：清展开/详情 + 重载历史（新书任务列表自动加载，根因 2 解决）
  useEffect(() => {
    let alive = true
    setTasks([])
    setOpenTaskId(null)
    setDetail(null)
    api.listTasks(projectId)
      .then((list) => { if (alive) setTasks(list) })
      .catch(() => { if (alive) setTasks([]) })
    return () => { alive = false }
  }, [projectId])

  // 新任务入队/终态 → 历史追加当前任务（实时流转仍走上方 TaskTimeline）
  useEffect(() => {
    let alive = true
    api.listTasks(projectId)
      .then((list) => { if (alive) setTasks(list) })
      .catch(() => { if (alive) setTasks([]) })
    return () => { alive = false }
  }, [activeTaskId, projectId])

  // 展开/收起一行：展开时拉任务详情（含 runs 流转记录）
  async function toggleDetail(tid: string) {
    if (openTaskId === tid) {
      setOpenTaskId(null)
      setDetail(null)
      return
    }
    setOpenTaskId(tid)
    setDetail(null)
    setDetailLoading(true)
    setError(null)
    try {
      setDetail(await api.getTask(tid))
    } catch (err) {
      setError(err instanceof ApiError ? err.code : '详情加载失败')
    } finally {
      setDetailLoading(false)
    }
  }

  // 控制（pause/resume/cancel）：外部控制不发 SSE，成功后主动拉新详情 + 刷新列表
  async function control(action: BatchAction, tid: string) {
    if (ctrl) return
    setCtrl(action)
    setError(null)
    try {
      if (action === 'pause') await api.pauseBatch(tid)
      else if (action === 'resume') await api.resumeBatch(tid)
      else await api.cancelBatch(tid)
      setDetail(await api.getTask(tid))
      const list = await api.listTasks(projectId).catch(() => [])
      setTasks(list)
    } catch (err) {
      setError(err instanceof ApiError ? err.code : '操作失败')
    } finally {
      setCtrl(null)
    }
  }

  const detailActions = detail ? (STATUS_ACTIONS[detail.status] ?? []) : []

  return (
    <section className={`panel ${styles.panel}`}>
      <header className={styles.head}>
        <button type="button" className={styles.toggle} onClick={() => setOpen((o) => !o)}>
          <span className={styles.title}>任务</span>
          {tasks.length > 0 && <span className="badge badge-hint">{tasks.length}</span>}
          <span className={styles.caret}>{open ? '▾' : '▸'}</span>
        </button>
      </header>

      {error && <div className="banner banner-error">{error}</div>}

      {open && tasks.length === 0 && (
        <p className="empty">尚无任务。发起生成后历史会出现在这里。</p>
      )}

      {open && tasks.length > 0 && (
        <ul className={styles.list}>
          {tasks.map((t) => {
            const expanded = openTaskId === t.task_id
            const active = t.task_id === activeTaskId
            return (
              <li key={t.task_id} className={styles.item}>
                <button
                  type="button"
                  className={styles.row}
                  onClick={() => void toggleDetail(t.task_id)}
                >
                  <StatusBadge tone={taskStatusTone(t.status)}>{taskStatusLabel(t.status)}</StatusBadge>
                  <span className={styles.type}>{taskTypeLabel(t.task_type)}</span>
                  <span className={styles.target}>{targetLabel(t)}</span>
                  {t.cost_total > 0 && (
                    <span className={styles.cost} title="任务总花费（节点 cost 合计，§6.8 成本透明）">
                      总 ¥{t.cost_total.toFixed(2)}
                    </span>
                  )}
                  {active && <span className={styles.live}>进行中</span>}
                  <span className={styles.date}>
                    {t.created_at ? new Date(t.created_at).toLocaleString('zh-CN') : ''}
                  </span>
                  <span className={styles.caret}>{expanded ? '▾' : '▸'}</span>
                </button>
                {t.error && <p className={styles.errorText}>{t.error}</p>}
                {expanded && (
                  <div className={styles.detail}>
                    {detailLoading ? (
                      <p className="empty">加载流转记录…</p>
                    ) : detail ? (
                      <>
                        <div className={styles.detailHead}>
                          {detail.cost_total > 0 && (
                            <span className={styles.cost}>总花费 ¥{detail.cost_total.toFixed(2)}</span>
                          )}
                          {detail.progress && (
                            <span className={styles.progress}>
                              {detail.progress.current}/{detail.progress.total}
                            </span>
                          )}
                          {detailActions.length > 0 && (
                            <div className={styles.controls}>
                              {detailActions.map((a) => (
                                <button
                                  key={a}
                                  type="button"
                                  className="btn btn-quiet"
                                  disabled={ctrl !== null}
                                  onClick={() => void control(a, t.task_id)}
                                >
                                  {ctrl === a ? '处理中…' : ACTION_LABEL[a]}
                                </button>
                              ))}
                              {detail.status === 'awaiting_review' && (
                                <span className={styles.hint}>候选待确认，处理完点续跑放行</span>
                              )}
                            </div>
                          )}
                        </div>
                        {detail.runs.length > 0 ? (
                          <div className={styles.runs}>
                            {detail.runs.map((r: AgentRun, i) => (
                              <RunNodeCard key={`${r.node}-${i}`} run={r} />
                            ))}
                          </div>
                        ) : (
                          <p className="empty">无流转记录（任务未开始或尚未落库）。</p>
                        )}
                      </>
                    ) : (
                      <p className="empty">详情加载失败。</p>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
