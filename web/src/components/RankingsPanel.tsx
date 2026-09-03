// 扫榜灵感面板（§10 MCP Client 拉取外部榜单 → 只作建书前的灵感工具）。
// 全局无项目端点：不传 projectId（或建书向导里）→ 展示外部实时榜单，供用户建书前
// 看题材风向；不注入任何生成节点，数据不进记忆/事实层。
// source=remote 显示实时榜单（accent 徽标）；source=sample 显示降级横幅
// （网络不可达 / RANKINGS_ENABLED=0）+ 示例数据（warning 徽标，书名带【示例】前缀）。
// 头部刷新按钮强制绕过进程内 TTL 缓存重拉；数据仅灵感参考，不进记忆/事实层。
import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { hotText, sourceLabel, sourceTone, tagsText } from '../lib/rankings'
import type { RankingsResponse } from '../types'
import { StatusBadge } from './StatusBadge'
import styles from './RankingsPanel.module.css'

export function RankingsPanel() {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<RankingsResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (refresh: boolean) => {
    setBusy(true)
    setError(null)
    try {
      setData(await api.listRankings(refresh))
    } catch (err) {
      setError(err instanceof ApiError ? err.code : '榜单加载失败')
    } finally {
      setBusy(false)
    }
  }, [])

  // 挂载即预热（TTL 缓存服务端兜底，多次折叠展开不重复打 MCP）；失败静默降级
  useEffect(() => {
    let alive = true
    api
      .listRankings()
      .then((res) => { if (alive) setData(res) })
      .catch(() => { if (alive) setData(null) })
    return () => { alive = false }
  }, [])

  const degraded = data?.source === 'sample'

  return (
    <section className={`panel ${styles.panel}`}>
      <header className={styles.head}>
        <button type="button" className={styles.toggle} onClick={() => setOpen((o) => !o)}>
          <span className={styles.title}>扫榜灵感</span>
          <span className={styles.caret}>{open ? '▾' : '▸'}</span>
        </button>
        <button
          type="button"
          className="btn btn-quiet"
          disabled={busy}
          title="强制刷新（绕过缓存）"
          onClick={() => void load(true)}
        >
          {busy ? '刷新中…' : '刷新'}
        </button>
      </header>

      {error && <div className="banner banner-error">{error}</div>}

      {open && !data && !error && (
        <p className="empty">扫榜灵感为空。建书前看看外部题材风向，给梗概找些参考。</p>
      )}

      {open && data && (
        <div className={styles.body}>
          {degraded && (
            <div className="banner banner-warning">
              外部榜单不可用（{data.error ?? '网络不可达或已禁用'}）。下方为内置示例数据，仅示意字段形状；建书不依赖此面板。
            </div>
          )}
          <div className={styles.meta}>
            <StatusBadge tone={sourceTone(data.source)}>{sourceLabel(data.source)}</StatusBadge>
            {data.fetched_at && (
              <span className={styles.fetched}>{data.fetched_at.replace('T', ' ').slice(0, 19)}</span>
            )}
          </div>
          <ul className={styles.list}>
            {data.items.map((item) => (
              <li key={item.rank} className={styles.item}>
                <span className={styles.rank}>{item.rank}</span>
                <div className={styles.info}>
                  <span className={styles.titleText}>{item.title}</span>
                  {item.author && <span className={styles.author}>{item.author}</span>}
                </div>
                <div className={styles.rightMeta}>
                  {tagsText(item.tags) && <span className={styles.tags}>{tagsText(item.tags)}</span>}
                  {hotText(item.hot) && <span className={styles.hot}>{hotText(item.hot)}</span>}
                </div>
              </li>
            ))}
          </ul>
          <p className={styles.note}>
            仅作建书前的题材风向参考，禁止抄袭书名/设定，不构成本书事实约束。
          </p>
        </div>
      )}
    </section>
  )
}
