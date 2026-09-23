/** 管理控制台各视图共用的展示件与取数钩子。
 *
 * 样式仍取自 AdminPage.module.css：这些类（panel/tableWrap/drilldown…）本就是这个页面
 * 的版式，抽出来只是为了让分析页与快照页复用同一套，不复制一份 CSS。
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ApiError } from '../../lib/api'
import { formatApiError } from '../../lib/apiError'
import type { AdminMetrics, CapturedData } from '../../lib/adminApi'
import styles from '../AdminPage.module.css'

export const PAGE_SIZE = 25

export function useResource<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  onForbidden: () => void,
) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [revision, setRevision] = useState(0)
  const sequence = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    const current = ++sequence.current
    setLoading(true)
    setError(null)
    setData(null)
    void loader(controller.signal).then((value) => {
      if (!controller.signal.aborted && current === sequence.current) setData(value)
    }).catch((reason: unknown) => {
      if (controller.signal.aborted || current !== sequence.current) return
      if (reason instanceof ApiError && reason.status === 403) {
        onForbidden()
        return
      }
      if (reason instanceof ApiError && reason.code === 'request_aborted') return
      setError(formatApiError(reason, '加载失败，请稍后重试'))
    }).finally(() => {
      if (!controller.signal.aborted && current === sequence.current) setLoading(false)
    })
    return () => controller.abort()
  }, [loader, onForbidden, revision])

  return { data, loading, error, retry: () => setRevision((value) => value + 1) }
}

export function LoadState({
  loading,
  error,
  empty,
  retry,
  children,
}: {
  loading: boolean
  error: string | null
  empty: boolean
  retry: () => void
  children: ReactNode
}) {
  if (loading) return <div className="empty" role="status">正在加载…</div>
  if (error) {
    return (
      <div className={`banner banner-error ${styles.loadError}`} role="alert">
        <span>{error}</span>
        <button type="button" className="btn btn-secondary" onClick={retry}>重试</button>
      </div>
    )
  }
  if (empty) return <div className="empty">暂无数据</div>
  return children
}

export function Pagination({ total, offset, onChange }: {
  total: number
  offset: number
  onChange: (offset: number) => void
}) {
  return (
    <div className={styles.pagination} aria-label="分页">
      <button
        type="button"
        className="btn btn-quiet"
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}
      >上一页</button>
      <span>第 {Math.floor(offset / PAGE_SIZE) + 1} 页 · 共 {total} 条</span>
      <button
        type="button"
        className="btn btn-quiet"
        disabled={offset + PAGE_SIZE >= total}
        onClick={() => onChange(offset + PAGE_SIZE)}
      >下一页</button>
    </div>
  )
}

export function RefreshButton({ onClick }: { onClick: () => void }) {
  return <button type="button" className="btn btn-secondary" onClick={onClick}>刷新当前视图</button>
}

export function Metrics({ value }: { value: AdminMetrics }) {
  return (
    <dl className={styles.metrics}>
      <div><dt>运行数</dt><dd>{value.run_count.toLocaleString()}</dd></div>
      <div><dt>输入 Token</dt><dd>{value.input_tokens.toLocaleString()}</dd></div>
      <div><dt>输出 Token</dt><dd>{value.output_tokens.toLocaleString()}</dd></div>
      <div><dt>预估存储成本（非实际账单）</dt><dd>¥/US$ {value.cost_est.toFixed(4)}</dd></div>
      <div><dt>节点计时合计；0 表示未记录</dt><dd>{formatDuration(value.duration_ms)}</dd></div>
    </dl>
  )
}

export function formatDuration(value: number): string {
  if (value === 0) return '0（未记录）'
  if (value < 1000) return `${value} ms`
  return `${(value / 1000).toFixed(2)} 秒`
}

export function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

export function JsonText({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === '') return <p className={styles.muted}>无记录</p>
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  return <pre className={styles.pre}>{text}</pre>
}

export function CapturedView({ value, label }: { value: CapturedData; label: string }) {
  return (
    <section className={styles.capture} aria-label={label}>
      <h4>{label}</h4>
      <div className={styles.flags}>
        {value.truncated && <span className="badge badge-warning">内容已截断</span>}
        {value.redacted && <span className="badge badge-warning">敏感信息已脱敏</span>}
        {!value.truncated && !value.redacted && <span className="badge">完整的受限快照</span>}
      </div>
      <JsonText value={value.data} />
      <small className={styles.muted}>
        上限：{value.limits.max_items} 项 / {value.limits.max_text} 字符 / {value.limits.max_bytes} 字节
      </small>
    </section>
  )
}
