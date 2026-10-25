import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import * as echarts from 'echarts'
import { adminApi, type AdminTrendPoint } from '../../lib/adminApi'
import { LoadState, useResource } from './shared'
import styles from './AdminTrends.module.css'

const counts = [['user_count', '新增用户'], ['project_count', '新增作品'], ['chapter_count', '新增章节'], ['task_count', '新增任务'], ['run_count', '模型调用']] as const
const tokens = [['input_tokens', '输入 Token'], ['output_tokens', '输出 Token']] as const
const cost = [['cost_est', '估算费用（人民币）']] as const
function recent(days: number) {
  const end = new Date()
  const start = new Date(end)
  start.setUTCDate(start.getUTCDate() - days + 1)
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) }
}
function TrendChart({ points, series, title }: { points: AdminTrendPoint[]; series: readonly (readonly [keyof Omit<AdminTrendPoint, 'day'>, string])[]; title: string }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current, undefined, { renderer: 'svg' })
    chart.setOption({
      color: ['#3d8073', '#688cc4', '#b89754', '#a078b1', '#bd7562'],
      tooltip: { trigger: 'axis', confine: true },
      legend: { bottom: 0, type: 'scroll' },
      grid: { top: 20, left: 20, right: 20, bottom: 65, containLabel: true },
      xAxis: { type: 'category', data: points.map(p => p.day), boundaryGap: false },
      yAxis: { type: 'value', min: 0 },
      series: series.map(([key, name]) => ({ name, type: 'line', showSymbol: points.length < 15, data: points.map(p => p[key]) })),
    })
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => chart.resize())
    observer?.observe(ref.current)
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => { observer?.disconnect(); window.removeEventListener('resize', resize); chart.dispose() }
  }, [points, series])
  return <section className={styles.chartCard}><h3>{title}</h3><div className={styles.chart} ref={ref} role="img" aria-label={title} /></section>
}
export function AdminTrends({ token, onForbidden }: { token: string; onForbidden: () => void }) {
  const [range, setRange] = useState(() => recent(30))
  const [draft, setDraft] = useState(range)
  const [validation, setValidation] = useState('')
  const load = useCallback((signal: AbortSignal) => adminApi.getTrends(token, range.start, range.end, signal), [token, range])
  const resource = useResource(load, onForbidden)
  const points = resource.data?.items ?? []
  const allSeries = [...counts, ...tokens, ...cost]
  const empty = points.every(p => allSeries.every(([key]) => p[key] === 0))
  const choose = (days: number) => { const next = recent(days); setDraft(next); setRange(next); setValidation('') }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const days = (Date.parse(draft.end) - Date.parse(draft.start)) / 86400000 + 1
    if (!Number.isFinite(days) || days < 1 || days > 90) { setValidation('请选择连续 1 至 90 天'); return }
    setValidation(''); setRange({ ...draft })
  }
  return <section className={styles.trends} aria-labelledby="trends-heading">
    <h2 id="trends-heading">每日趋势</h2>
    <p>按 UTC 自然日统计新增记录，起止日期均包含在内；费用为估算人民币金额。</p>
    <form className={styles.filters} onSubmit={submit}>
      <button type="button" className="btn btn-secondary" onClick={() => choose(7)}>近7天</button>
      <button type="button" className="btn btn-secondary" onClick={() => choose(30)}>近30天</button>
      <label>开始日期<input aria-label="开始日期" type="date" required value={draft.start} onChange={e => setDraft({ ...draft, start: e.target.value })} /></label>
      <label>结束日期<input aria-label="结束日期" type="date" required value={draft.end} onChange={e => setDraft({ ...draft, end: e.target.value })} /></label>
      <button className="btn btn-secondary" type="submit">查询趋势</button>
      <button className="btn btn-quiet" type="button" onClick={resource.retry}>刷新趋势</button>
    </form>
    {validation && <p role="alert">{validation}</p>}
    <LoadState {...resource} empty={false}>
      {empty ? <p className="empty">所选日期暂无记录</p> : <>
        <dl className={styles.summary}>{allSeries.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{points.reduce((sum, p) => sum + p[key], 0).toLocaleString('zh-CN', { maximumFractionDigits: key === 'cost_est' ? 4 : 0 })}</dd></div>)}</dl>
        <TrendChart points={points} series={counts} title="新增记录与模型调用" />
        <TrendChart points={points} series={tokens} title="每日输入与输出 Token" />
        <TrendChart points={points} series={cost} title="每日估算费用" />
      </>}
    </LoadState>
  </section>
}
