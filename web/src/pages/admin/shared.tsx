/** 管理控制台各视图共用的展示件与取数钩子。
 *
 * 样式仍取自 AdminPage.module.css：这些类（panel/tableWrap/drilldown…）本就是这个页面
 * 的版式，抽出来只是为了让分析页与快照页复用同一套，不复制一份 CSS。
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../../lib/api'
import { formatApiError } from '../../lib/apiError'
import type { AdminMetrics, CapturedData } from '../../lib/adminApi'
import { asRecord, fieldLabel, isInternalKey } from '../../lib/snapshotView'
import styles from '../AdminPage.module.css'

export const PAGE_SIZE = 25

/** /admin 外壳交给子路由的东西：闸门验过的 token 与「权限已变」的回调。 */
export type AdminOutletContext = { token: string; onForbidden: () => void }

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

/** 详情页外壳：标题 + 返回原标签页的链接。返回必须带回 tab，否则回退永远落在概览。 */
export function DetailPage({ heading, backTab, children }: {
  heading: string
  backTab: string
  children: ReactNode
}) {
  return (
    <section className={styles.view}>
      <div className={styles.viewHead}>
        <div><h1>{heading}</h1></div>
        <Link to={`/admin?tab=${backTab}`} className="btn btn-secondary">返回</Link>
      </div>
      {children}
    </section>
  )
}

/** 值 → 可读文本：标量直出，布尔转「是/否」，对象与对象数组降一级展开。 */
export function ValueText({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === '') return <span className={styles.muted}>—</span>
  if (typeof value === 'boolean') return <>{value ? '是' : '否'}</>
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className={styles.muted}>—</span>
    if (value.every((item) => item === null || typeof item !== 'object')) {
      return <>{value.map((item) => String(item)).join('、')}</>
    }
    return <ul className={styles.plainList}>
      {value.map((item, index) => <li key={index}><ValueText value={item} /></li>)}
    </ul>
  }
  if (typeof value === 'object') return <RecordFields value={value} />
  return <>{String(value)}</>
}

/** 记录 → 「字段名 → 值」列表。空值、空串与内部标记字段不占位。 */
export function RecordFields({ value, skip = [] }: { value: unknown; skip?: string[] }) {
  const record = asRecord(value)
  if (!record) return <ValueText value={value} />
  const rows = Object.entries(record).filter(([key, item]) => !isInternalKey(key)
    && !skip.includes(key) && item !== null && item !== undefined && item !== '')
  if (rows.length === 0) return <p className={styles.muted}>无记录</p>
  return (
    <dl className={styles.fields}>
      {rows.map(([key, item]) => <div key={key}>
        <dt>{fieldLabel(key)}</dt>
        <dd><ValueText value={item} /></dd>
      </div>)}
    </dl>
  )
}

/** 一行一个「字段名 → 值」；表格单元格里的多字段摘要用它，避免斜杠拼列。 */
export function FieldRows({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <dl className={styles.fields}>
      {rows.map(([label, value]) => <div key={label}>
        <dt>{label}</dt>
        <dd>{value}</dd>
      </div>)}
    </dl>
  )
}

export function Metrics({ value }: { value: AdminMetrics }) {
  return (
    <dl className={styles.metrics}>
      <div><dt>运行数</dt><dd>{value.run_count.toLocaleString()}</dd></div>
      <div><dt>输入 token</dt><dd>{value.input_tokens.toLocaleString()}</dd></div>
      <div><dt>输出 token</dt><dd>{value.output_tokens.toLocaleString()}</dd></div>
      <div><dt>预估成本</dt><dd>{formatCost(value.cost_est)}</dd></div>
      <div><dt>节点耗时</dt><dd>{formatDuration(value.duration_ms)}</dd></div>
    </dl>
  )
}

/** 成本只有估算值，币种不可知，所以只出数字，不拼货币符号。 */
export function formatCost(value: number): string {
  return value.toFixed(4)
}

export function formatDuration(value: number): string {
  if (value === 0) return '—'
  if (value < 1000) return `${value} ms`
  return `${(value / 1000).toFixed(2)} 秒`
}

export function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

/** 一律按字段展示；只有拿不到结构的兜底才落回 JSON。 */
export function CapturedView({ value, label, skip }: {
  value: CapturedData
  label: string
  skip?: string[]
}) {
  const flagged = value.truncated || value.redacted
  return (
    <section className={styles.capture} aria-label={label}>
      <h4>{label}</h4>
      {flagged && <div className={styles.flags}>
        {value.truncated && <span className="badge badge-warning">内容已截断</span>}
        {value.redacted && <span className="badge badge-warning">敏感信息已脱敏</span>}
      </div>}
      {typeof value.data === 'string'
        ? (value.data === ''
          ? <p className={styles.muted}>无记录</p>
          : <p className={styles.text}>{value.data}</p>)
        : <RecordFields value={value.data} skip={skip} />}
    </section>
  )
}
