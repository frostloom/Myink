// 生成进度时间线：phase 状态条 + 批次 i/N + 实时节点流（SSE 实时层）→ 终态后 runs 节点卡（快照权威）。
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
  error: string | null
  onRetry: () => void
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

export function TaskTimeline({
  taskId,
  phase,
  status,
  nodes,
  runs,
  progress,
  error,
  onRetry,
}: TaskTimelineProps) {
  if (!taskId) {
    return <p className="empty">尚未发起生成。</p>
  }

  const terminal = phase === 'terminal'
  const busy = phase === 'connecting' || phase === 'live' || phase === 'reconnecting'

  return (
    <div className={styles.timeline}>
      <header className={styles.head}>
        <span className={`badge badge-${phaseTone(phase)}`}>{PHASE_LABEL[phase]}</span>
        {status && <span className={styles.status}>任务 {status}</span>}
        {progress && (
          <span className={styles.progress}>
            {progress.current}/{progress.total}
          </span>
        )}
        {error && <span className={styles.error}>{error}</span>}
      </header>

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
          <h4 className={styles.runsTitle}>执行详情</h4>
          {runs.map((r, i) => (
            <RunNodeCard key={`${r.node}-${i}`} run={r} />
          ))}
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
