// 当前章节唯一的状态流转图：实时节点与终态快照共用一条流程，逐节点展示耗时和费用。
// 审核结论与人工设定确认由独立面板负责，避免三类信息混在同一组件。
import { useState } from 'react'
import { api, ApiError } from '../lib/api'
import { nodeLabel, taskStatusLabel, taskStatusTone } from '../lib/labels'
import { compactFlowRuns, groupFlowAttempts } from '../lib/taskFlow'
import type { TaskPhase } from '../hooks/useTaskEvents'
import type { AgentRun, TaskStatus } from '../types'
import styles from './TaskTimeline.module.css'

export interface TaskTimelineProps {
  taskId: string | null
  phase: TaskPhase
  status: TaskStatus | null
  nodes: Array<{ taskId: string; node: string; seenAt: number }>
  runs: AgentRun[]
  /** 正在执行、尚无 agent_runs 记录的节点（由产物流推导）：补一条实时步骤，避免停在上一节点 */
  liveNode?: string | null
  progress: { current: number; total: number } | null
  chapterSeq?: number | null
  error: string | null
  onRetry: () => void
  canControl?: boolean
  refresh: () => void
}

const PHASE_LABEL: Record<TaskPhase, string> = {
  idle: '空闲',
  connecting: '连接中',
  live: '执行中',
  reconnecting: '重连中',
  terminal: '已结束',
  expired: '记录已归档',
  error: '出错',
}

type BatchAction = 'pause' | 'resume' | 'cancel'

const ACTION_LABEL: Record<BatchAction, string> = {
  pause: '暂停',
  resume: '续跑',
  cancel: '取消',
}

const STATUS_ACTIONS: Partial<Record<TaskStatus, BatchAction[]>> = {
  paused: ['resume', 'cancel'],
  queued: ['pause', 'cancel'],
  running: ['pause', 'cancel'],
  awaiting_review: ['resume'],
}

const ROUTE_LABELS: Record<string, string> = {
  plan_review: '等待确认计划',
  persist: '通过，进入落库',
  revise: '重写并复审',
  replan_chapter: '重规划本章',
  replan_batch: '重规划批次',
  needs_review: '转人工确认',
  fail: '停止',
}

export function TaskTimeline({
  taskId,
  phase,
  status,
  nodes,
  runs,
  liveNode = null,
  progress,
  chapterSeq = null,
  error,
  onRetry,
  canControl = false,
  refresh,
}: TaskTimelineProps) {
  const [open, setOpen] = useState(true)
  const [ctrl, setCtrl] = useState<BatchAction | null>(null)
  const [ctrlError, setCtrlError] = useState<string | null>(null)
  const attempts = groupFlowAttempts(runs).map((attemptRuns) => ({
    rawRuns: attemptRuns,
    displayRuns: compactFlowRuns(attemptRuns, status),
  }))
  const displayRunCount = attempts.reduce((sum, attempt) => sum + attempt.displayRuns.length, 0)
  const displayNodes = nodes.filter((node, index) => index === 0 || node.node !== nodes[index - 1].node)
  const renderedTail = attempts.length > 0
    ? attempts.at(-1)?.displayRuns.at(-1)?.node
    : displayNodes.at(-1)?.node
  // 已落库的最后一步就是这个进行中节点（落库先于产物 complete 的极窄窗口）→ 不重复补
  const pendingNode = liveNode && liveNode !== renderedTail ? liveNode : null
  const totalCost = runs.reduce((sum, run) => sum + run.cost_est, 0)
  const totalDuration = runs.reduce((sum, run) => sum + run.duration_ms, 0)
  const actions = canControl && status ? (STATUS_ACTIONS[status] ?? []) : []
  const tid = taskId

  async function control(action: BatchAction) {
    if (!tid || ctrl) return
    setCtrl(action)
    setCtrlError(null)
    try {
      if (action === 'pause') await api.pauseBatch(tid)
      else if (action === 'resume') await api.resumeBatch(tid)
      else await api.cancelBatch(tid)
    } catch (err) {
      setCtrlError(err instanceof ApiError ? err.code : '操作失败')
    } finally {
      setCtrl(null)
      refresh()
    }
  }

  const tone = status ? taskStatusTone(status) : phaseTone(phase)
  const label = status ? taskStatusLabel(status) : PHASE_LABEL[phase]

  return (
    <section className={`panel ${styles.panel}`} aria-label="章节状态流转">
      <header className={styles.head}>
        <button type="button" className={styles.toggle} onClick={() => setOpen((value) => !value)} aria-expanded={open}>
          <span className={styles.headingGroup}>
            <span className={styles.title}>章节流转</span>
            {chapterSeq !== null && <span className={styles.chapter}>第 {chapterSeq} 章</span>}
          </span>
          <span className={styles.headerMeta}>
            <span className={`badge badge-${tone}`}>{label}</span>
            {taskId && <span className={styles.cost}>¥{totalCost.toFixed(4)}</span>}
            <span className={styles.caret}>{open ? '▾' : '▸'}</span>
          </span>
        </button>
      </header>

      {open && (
        <div className={styles.body}>
          {!taskId ? (
            <p className="empty">本章还没有生成记录。</p>
          ) : (
            <>
              <div className={styles.summary}>
                <span>
                  {attempts.length > 0
                    ? `${attempts.length} 次生成 · ${displayRunCount} 个阶段`
                    : `本次 ${displayNodes.length} 个阶段`}
                </span>
                {totalDuration > 0 && <span>{formatDuration(totalDuration)}</span>}
                {progress && <span>批次 {progress.current}/{progress.total}</span>}
              </div>
              {error && <div className="banner banner-error">{error}</div>}

              {attempts.length > 0 ? (
                <div className={styles.attemptList}>
                  {attempts.map((attempt, attemptIndex) => {
                    const attemptCost = attempt.rawRuns.reduce((sum, run) => sum + run.cost_est, 0)
                    const attemptDuration = attempt.rawRuns.reduce((sum, run) => sum + run.duration_ms, 0)
                    const attemptTokens = attempt.rawRuns.reduce(
                      (sum, run) => sum + run.input_tokens + run.output_tokens, 0,
                    )
                    return (
                      <section key={attemptIndex} className={styles.attempt} aria-label={`第 ${attemptIndex + 1} 次生成`}>
                        <div className={styles.attemptHead}>
                          <strong>第 {attemptIndex + 1} 次生成</strong>
                          <span>{attempt.displayRuns.length} 个阶段</span>
                        </div>
                        <div className={styles.attemptSummary}>
                          <span>{formatDuration(attemptDuration)}</span>
                          <span>¥{attemptCost.toFixed(4)}</span>
                          <span>{attemptTokens.toLocaleString('zh-CN')} Token</span>
                        </div>
                        <ol className={styles.flow}>
                          {attempt.displayRuns.map((run, index) => (
                            <li key={`${run.node}-${index}`} className={styles.step}>
                              <span className={`${styles.dot} ${run.error ? styles.dotError : ''}`} />
                              <div className={styles.stepMain}>
                                <div className={styles.stepHead}>
                                  <strong>{nodeLabel(run.node)}</strong>
                                  {run.detail?.route && <span className={styles.route}>{ROUTE_LABELS[run.detail.route] ?? run.detail.route}{run.derived ? '（依据结果）' : ''}</span>}
                                </div>
                                <dl className={styles.metrics}>
                                  <div><dt>耗时</dt><dd>{formatDuration(run.duration_ms)}</dd></div>
                                  <div><dt>费用</dt><dd>¥{run.cost_est.toFixed(4)}</dd></div>
                                  <div><dt>Token</dt><dd>{(run.input_tokens + run.output_tokens).toLocaleString('zh-CN')}</dd></div>
                                </dl>
                                {run.retry_count > 0 && <span className={styles.retry}>重试 {run.retry_count} 次</span>}
                                {run.error && <p className={styles.stepError}>{run.error}</p>}
                              </div>
                            </li>
                          ))}
                          {attemptIndex === attempts.length - 1 && pendingNode && (
                            <LiveStep node={pendingNode} />
                          )}
                        </ol>
                      </section>
                    )
                  })}
                </div>
              ) : displayNodes.length > 0 || pendingNode ? (
                <ol className={styles.flow}>
                  {displayNodes.map((node, index) => (
                    <li key={`${node.seenAt}-${index}`} className={styles.step}>
                      <span className={styles.dot} />
                      <div className={styles.stepMain}>
                        <div className={styles.stepHead}><strong>{nodeLabel(node.node)}</strong></div>
                        <p className={styles.liveState}>已完成</p>
                      </div>
                    </li>
                  ))}
                  {pendingNode && <LiveStep node={pendingNode} />}
                </ol>
              ) : (
                <p className="empty">{emptyTaskMessage(status)}</p>
              )}

              {actions.length > 0 && (
                <div className={styles.controls}>
                  {actions.map((action) => (
                    <button key={action} type="button" className="btn btn-quiet" disabled={ctrl !== null} onClick={() => void control(action)}>
                      {ctrl === action ? '处理中…' : ACTION_LABEL[action]}
                    </button>
                  ))}
                  {ctrlError && <span className={styles.ctrlError}>{ctrlError}</span>}
                </div>
              )}
              {phase === 'expired' && <button type="button" className="btn btn-quiet" onClick={onRetry}>重新连接</button>}
            </>
          )}
        </div>
      )}
    </section>
  )
}

function LiveStep({ node }: { node: string }) {
  return (
    <li className={styles.step}>
      <span className={`${styles.dot} ${styles.dotLive}`} />
      <div className={styles.stepMain}>
        <div className={styles.stepHead}><strong>{nodeLabel(node)}</strong></div>
        <p className={styles.liveState}>正在执行</p>
      </div>
    </li>
  )
}

function emptyTaskMessage(status: TaskStatus | null): string {
  switch (status) {
    case 'failed': return '本次生成在记录流程前失败，请查看错误信息。'
    case 'cancelled': return '任务已取消，没有可显示的流程记录。'
    case 'done': return '任务已完成，但没有可显示的流程记录。'
    case 'awaiting_plan': return '章节计划正在等待确认。'
    case 'awaiting_review': return '任务正在等待人工处理，但没有可显示的流程记录。'
    case 'paused': return '任务已暂停，尚未记录执行步骤。'
    default: return '任务已创建，等待第一个步骤开始。'
  }
}

function formatDuration(milliseconds: number): string {
  if (milliseconds < 1000) return `${milliseconds} ms`
  if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} 秒`
  const minutes = Math.floor(milliseconds / 60_000)
  const seconds = Math.round((milliseconds % 60_000) / 1000)
  return `${minutes} 分 ${seconds} 秒`
}

function phaseTone(phase: TaskPhase): string {
  switch (phase) {
    case 'live': return 'accent'
    case 'terminal': return 'success'
    case 'connecting':
    case 'reconnecting': return 'warning'
    case 'expired':
    case 'error': return 'error'
    case 'idle': return 'hint'
  }
}
