// 生成进度时间线：phase 状态条 + 批次 i/N + 实时节点流（SSE 实时层）→ 终态后 runs 节点卡（快照权威）。
// 批次控制（暂停/续跑/取消）：网关控制路由仅对批次任务开放；外部控制不发 SSE 事件，
// 成功后调 refresh() 主动拉快照刷新状态/进度，终态（取消）由 refresh 停流。
import { useState } from 'react'
import { api, ApiError } from '../lib/api'
import { nodeLabel } from '../lib/labels'
import type { TaskPhase } from '../hooks/useTaskEvents'
import type { AgentRun, TaskStatus } from '../types'
import { RunNodeCard } from './RunNodeCard'
import styles from './TaskTimeline.module.css'

export interface TaskTimelineProps {
  taskId: string | null
  phase: TaskPhase
  status: TaskStatus | null
  nodes: Array<{ taskId: string; node: string; seenAt: number }>
  runs: AgentRun[]
  progress: { current: number; total: number } | null
  /** 右栏按章过滤：非空时 runs/nodes 已是该章切片，花费/详情标签标注「第 N 章」 */
  chapterSeq?: number | null
  error: string | null
  onRetry: () => void
  /** 批次任务才有控制权（网关仅暴露 /batches/:id/:action；单章生成走同端点但无网关控制路由） */
  canControl?: boolean
  /** 控制成功后主动拉快照刷新（见 useTaskEvents.refresh） */
  refresh: () => void
}

const PHASE_LABEL: Record<TaskPhase, string> = {
  idle: '空闲',
  connecting: '连接中',
  live: '实时',
  reconnecting: '重连中',
  terminal: '已完成',
  expired: '流已过期',
  error: '出错',
}

type BatchAction = 'pause' | 'resume' | 'cancel'

const ACTION_LABEL: Record<BatchAction, string> = {
  pause: '暂停',
  resume: '续跑',
  cancel: '取消',
}

// 各任务状态可用的控制动作。awaiting_review（候选确认池）已接线：确认候选后
// resume 从 checkpoint 续跑放行（Python _RESUMABLE 含 awaiting_review）；失败重试仍留重试切片。
const STATUS_ACTIONS: Partial<Record<TaskStatus, BatchAction[]>> = {
  paused: ['resume', 'cancel'],
  queued: ['pause', 'cancel'],
  running: ['pause', 'cancel'],
  awaiting_review: ['resume'],
}

export function TaskTimeline({
  taskId,
  phase,
  status,
  nodes,
  runs,
  progress,
  chapterSeq = null,
  error,
  onRetry,
  canControl = false,
  refresh,
}: TaskTimelineProps) {
  const [ctrl, setCtrl] = useState<BatchAction | null>(null)
  const [ctrlError, setCtrlError] = useState<string | null>(null)
  // 执行详情默认收起：总花费常显，展开才看逐节点流转/过程花费（用户口径）
  const [runsOpen, setRunsOpen] = useState(false)

  if (!taskId) {
    return <p className="empty">尚未发起生成。</p>
  }

  const terminal = phase === 'terminal'
  const busy = phase === 'connecting' || phase === 'live' || phase === 'reconnecting'
  // 总花费（§6.8 成本透明）：runs 终态快照全量，求和即任务总成本（批次=全批）
  const totalCost = runs.reduce((s, r) => s + r.cost_est, 0)
  const actions = canControl && status ? (STATUS_ACTIONS[status] ?? []) : []
  // 参数解构是可变绑定，收窄不进闭包：非空捕获 const 供 control 使用
  const tid = taskId

  async function control(action: BatchAction) {
    if (ctrl) return
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

  return (
    <div className={styles.timeline}>
      <header className={styles.head}>
        <span className={`badge badge-${phaseTone(phase)}`}>{PHASE_LABEL[phase]}</span>
        {status && <span className={styles.status}>任务 {status}</span>}
        {totalCost > 0 && (
          <span
            className={styles.cost}
            title={
              chapterSeq !== null
                ? `第 ${chapterSeq} 章运行成本（按选中章过滤，§6.8 成本透明）`
                : '任务总花费（节点 cost 合计，§6.8 成本透明）'
            }
          >
            {chapterSeq !== null ? `第 ${chapterSeq} 章花费 ¥${totalCost.toFixed(2)}` : `总花费 ¥${totalCost.toFixed(2)}`}
          </span>
        )}
        {progress && (
          <span className={styles.progress}>
            {progress.current}/{progress.total}
          </span>
        )}
        {error && <span className={styles.error}>{error}</span>}
      </header>

      {actions.length > 0 && (
        <div className={styles.controls}>
          {actions.map((a) => (
            <button
              key={a}
              type="button"
              className="btn btn-quiet"
              disabled={ctrl !== null}
              onClick={() => void control(a)}
            >
              {ctrl === a ? '处理中…' : ACTION_LABEL[a]}
            </button>
          ))}
          {status === 'awaiting_review' && (
            <span className={styles.hint}>候选待确认，处理完点续跑放行</span>
          )}
          {ctrlError && <span className={styles.ctrlError}>{ctrlError}</span>}
        </div>
      )}

      {phase === 'expired' && (
        <button type="button" className="btn btn-quiet" onClick={onRetry}>
          重新连接
        </button>
      )}

      {(busy || nodes.length > 0) && (
        <ol className={styles.nodes}>
          {nodes.map((n, i) => (
            <li key={`${n.seenAt}-${i}`} className={styles.node}>
              <span className={styles.nodeDot} />
              <span className={styles.nodeLabel}>{nodeLabel(n.node)}</span>
            </li>
          ))}
        </ol>
      )}

      {terminal && runs.length > 0 && (
        <div className={styles.runs}>
          <button
            type="button"
            className={styles.runsToggle}
            onClick={() => setRunsOpen((o) => !o)}
            aria-expanded={runsOpen}
          >
            <h4 className={styles.runsTitle}>
              {chapterSeq !== null ? `第 ${chapterSeq} 章` : '执行详情'} · {runs.length} 节点 · ¥
              {totalCost.toFixed(2)}
            </h4>
            <span className={styles.runCaret}>{runsOpen ? '▾' : '▸'}</span>
          </button>
          {runsOpen && (
            <div className={styles.runList}>
              {runs.map((r, i) => (
                <RunNodeCard key={`${r.node}-${i}`} run={r} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function phaseTone(phase: TaskPhase): string {
  switch (phase) {
    case 'live':
      return 'accent'
    case 'terminal':
      return 'success'
    case 'connecting':
    case 'reconnecting':
      return 'warning'
    case 'expired':
      return 'error'
    case 'error':
      return 'error'
    case 'idle':
      return 'hint'
  }
}
