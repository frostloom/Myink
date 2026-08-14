// 全局审计报告视图（阶段 4）：报告列表（窗口/状态/维度计数）+ 手动触发 + 详情 findings（跳章）。
// 长线一致性治理（§8.6）：跨章抽样 L2（人设/桥段/文风维度），findings 与章节校验同构渲染。
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { FindingsList } from '../components/FindingsList'
import { ProjectRail } from '../components/ProjectRail'
import { StatusBadge } from '../components/StatusBadge'
import { useAuth } from '../context/AuthContext'
import { api, ApiError } from '../lib/api'
import type { GlobalAuditReportDetail, GlobalAuditReportSummary, Project } from '../types'
import styles from './AuditPage.module.css'

export default function AuditPage() {
  const { projectId = '' } = useParams()
  const { logout } = useAuth()
  const navigate = useNavigate()

  const [projects, setProjects] = useState<Project[]>([])
  const [reports, setReports] = useState<GlobalAuditReportSummary[] | null>(null)
  const [detail, setDetail] = useState<GlobalAuditReportDetail | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [banner, setBanner] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  const load = useCallback(async (): Promise<GlobalAuditReportSummary[] | null> => {
    setBanner(null)
    try {
      const [list, proj] = await Promise.all([api.listGlobalAudits(projectId), api.listProjects()])
      setReports(list)
      setProjects(proj)
      return list
    } catch (err) {
      setBanner(err instanceof ApiError ? err.code : '报告加载失败')
      return null
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  async function openReport(id: string) {
    setBanner(null)
    try {
      const d = await api.getGlobalAudit(projectId, id)
      setDetail(d)
      setOpenId(id)
    } catch (err) {
      setBanner(err instanceof ApiError ? err.code : '报告详情加载失败')
    }
  }

  async function trigger() {
    if (busy) return
    setBusy(true)
    setBanner(null)
    setOk(null)
    try {
      await api.triggerGlobalAudit(projectId)
      // 用 load 返回的当次列表（勿读本渲染闭包的旧 reports——await 后闭包已陈旧）
      const list = await load()
      const newest = list?.[0]
      if (newest) await openReport(newest.report_id)
      setOk('审计已完成')
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 400) setBanner('该书尚无已写章节，无法审计')
        else if (err.status === 502) {
          setBanner('审计失败（已落 failed 报告，可查看明细）')
          void load()
        } else setBanner(err.code)
      } else {
        setBanner('请求失败，请重试')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.wrap}>
      <ProjectRail projects={projects} onLogout={logout} />
      <main className={styles.main}>
        <div className={styles.inner}>
          <header className={styles.header}>
            <div>
              <h1>全局审计</h1>
              <div className={styles.crumb}>
                <Link to={`/projects/${projectId}`}>返回工作台</Link>
                <span>每 K 章跨章抽样，检出跨章长线一致性问题</span>
              </div>
            </div>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={trigger}>
              {busy ? '审计中…' : '触发审计'}
            </button>
          </header>

          {banner && <div className="banner banner-error">{banner}</div>}
          {ok && <div className="banner banner-warning">{ok}</div>}

          {reports === null ? (
            <div className="empty">加载中…</div>
          ) : reports.length === 0 ? (
            <div className="empty">还没有审计报告。写几章后点「触发审计」开始跨章长线检查。</div>
          ) : (
            <ul className={styles.list}>
              {reports.map((r) => (
                <li key={r.report_id} className={`panel ${styles.report}`}>
                  <button
                    type="button"
                    className={styles.reportHead}
                    onClick={() => (openId === r.report_id ? setOpenId(null) : openReport(r.report_id))}
                  >
                    <StatusBadge tone={r.status === 'completed' ? 'success' : 'error'}>
                      {r.status === 'completed' ? '完成' : '失败'}
                    </StatusBadge>
                    <span className={styles.window}>
                      第 {r.window_start}–{r.window_end} 章
                    </span>
                    <span className={styles.meta}>
                      {r.chapters} 章 · 抽样 {r.sampled} 角色 · {r.findings} 发现
                      {r.trigger === 'manual' && ' · 手动'}
                    </span>
                    <span className={styles.date}>{r.created_at?.slice(0, 16) ?? ''}</span>
                  </button>

                  {openId === r.report_id && (
                    <div className={styles.detail}>
                      {r.error && <div className="banner banner-error">失败原因：{r.error}</div>}
                      <div className={styles.stats}>
                        <Stat label="窗口" value={`${r.window_start}–${r.window_end} 章`} />
                        <Stat label="抽样角色" value={r.sampled} />
                        <Stat label="findings" value={r.findings} />
                        {(r.bridge || r.style) && (
                          <span className={styles.dims}>
                            {r.bridge && <span className="badge badge-accent">桥段 {r.bridge.pairs} 对</span>}
                            {r.style && <span className="badge badge-accent">文风 {r.style.sampled} 章</span>}
                          </span>
                        )}
                      </div>
                      {detail && detail.report_id === r.report_id && (
                        <FindingsList
                          findings={detail.findings}
                          onNavigateChapter={(seq) => navigate(`/projects/${projectId}?chapter=${seq}`)}
                        />
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <span className={styles.stat}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.statValue}>{value}</span>
    </span>
  )
}
