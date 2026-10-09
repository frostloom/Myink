import { useRef, useState } from 'react'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import type { ResumeBudgetBody, TaskBudgetView, TaskStatus } from '../types'
import styles from './TaskBudgetPanel.module.css'
const REASONS: Record<string, string> = { request_limit: '请求次数耗尽', cost_limit: '费用额度不足', time_limit: '运行时间耗尽', runtime_limit: '运行时间耗尽' }
export function TaskBudgetPanel({ task, onResumed }: {
  task: { task_id: string; status: TaskStatus; budget?: TaskBudgetView | null }
  onResumed: () => void
}) {
  const [requests, setRequests] = useState(0)
  const [yuan, setYuan] = useState(0)
  const [minutes, setMinutes] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pending = useRef<ResumeBudgetBody | null>(null)
  const inFlight = useRef(false)
  const b = task.budget
  if (!b) return null
  const uncertain = task.status === 'queued' && b.resume_publication === 'uncertain'
  const canExtend = task.status === 'paused' && !!b.pause_reason
  const limit = (value: number, suffix = '') => value === 0 ? '不限' : `${value}${suffix}`
  async function resume(repair = false) {
    if (inFlight.current) return
    if (!pending.current) {
      if (!repair && (!Number.isSafeInteger(requests) || requests < 0 || requests > 2000000000 || !Number.isFinite(yuan) || yuan < 0 || yuan > 9000000000000 || Math.abs(yuan * 1e6 - Math.round(yuan * 1e6)) > 0.0001 || !Number.isSafeInteger(minutes * 60) || minutes < 0 || minutes * 60 > 9000000000000)) {
        setError('请输入非负预算；请求次数和秒数必须为整数，费用最多六位小数。')
        return
      }
      pending.current = { operation_id: crypto.randomUUID(), add_requests: repair ? 0 : requests, add_cost_yuan: repair ? 0 : yuan, add_runtime_seconds: repair ? 0 : minutes * 60 }
    }
    inFlight.current = true
    setBusy(true); setError(null)
    try {
      await api.resumeTask(task.task_id, pending.current)
      pending.current = null
      onResumed()
    } catch (e) { setError(formatApiError(e)); onResumed() }
    finally { inFlight.current = false; setBusy(false) }
  }
  return <section className={styles.panel} aria-label="任务预算">
    <h3>任务总预算</h3>
    <p>请求 {b.requests_used} / {limit(b.limits.max_requests)} · 费用 ¥{b.cost_used_yuan.toFixed(4)} / {limit(b.limits.max_cost_yuan, ' 元')} · 运行 {Math.round(b.runtime_used_seconds)} 秒 / {limit(b.limits.max_runtime_seconds, ' 秒')}</p>
    <p>未确认预留：¥{b.cost_reserved_yuan.toFixed(4)}。队列和暂停等待不计运行时间。</p>
    {b.stage && <p>当前阶段：{b.stage}</p>}
    {canExtend && <>
      <p>预算暂停：{REASONS[b.pause_reason!] ?? b.pause_reason}。追加后从保存的位置继续，累计消耗保留。</p>
      <div className={styles.fields}>
        <label>追加请求次数<input className="input" type="number" min="0" step="1" value={requests} disabled={busy || !!pending.current} onChange={e => setRequests(Number(e.target.value))} /></label>
        <label>追加费用（元）<input className="input" type="number" min="0" step="0.000001" value={yuan} disabled={busy || !!pending.current} onChange={e => setYuan(Number(e.target.value))} /></label>
        <label>追加运行时间（分钟）<input className="input" type="number" min="0" step="1" value={minutes} disabled={busy || !!pending.current} onChange={e => setMinutes(Number(e.target.value))} /></label>
      </div>
      <button className="btn" disabled={busy} onClick={() => void resume()}>{busy ? '处理中…' : pending.current ? '重试本次恢复' : '追加并继续'}</button>
      {pending.current && !busy && <button className="btn btn-quiet" onClick={() => { pending.current = null; setError(null) }}>结束本次操作</button>}
    </>}
    {uncertain && <><p>队列投递确认不明，额度已追加。先刷新状态；若仍排队，可重新投递，费用额度不会再次追加。</p><button className="btn" disabled={busy} onClick={() => { pending.current = null; void resume(true) }}>重新投递（不追加额度）</button></>}
    {error && <p role="alert">{error}</p>}
  </section>
}
