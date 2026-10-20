// 写作偏好仅选择平台发布模型；服务地址和凭证由管理员维护。
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ConnectionNotices, type ConnectionNotice } from '../components/ConnectionNotices'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import type {
  Project,
  RankingsConfig,
  TaskBudgetLimits,
} from '../types'
import styles from './SettingsPage.module.css'

const MODEL_ROLES = [
  { key: 'planner', label: '规划（planner）' },
  { key: 'writer', label: '写作（writer）' },
]
const EMPTY_ROUTE = { value: '', label: '未指定' }

type SectionMsg = { tone: 'error' | 'ok'; text: string } | null

const EMPTY_RANKINGS: RankingsConfig = {
  enabled: true,
  timeout: 10,
  limit: 10,
}

export default function EnvironmentPage() {
  const { logout } = useAuth()
  const guest = useGuest()
  const [projects, setProjects] = useState<Project[]>([])
  const [routeSel, setRouteSel] = useState<Record<string, string>>({})
  const [availableModels, setAvailableModels] = useState<Array<{ id: string; name: string }>>([])
  const [loading, setLoading] = useState(true)
  const [taskBudget, setTaskBudget] = useState<TaskBudgetLimits>({ max_requests: 100, max_cost_yuan: 5, max_runtime_seconds: 1800 })
  const [budgetMessage, setBudgetMessage] = useState<SectionMsg>(null)
  const [rankings, setRankings] = useState<RankingsConfig>(EMPTY_RANKINGS)
  const [thinkingEnabled, setThinkingEnabled] = useState(false)
  const [notices, setNotices] = useState<ConnectionNotice[]>([])
  const [rankMsg, setRankMsg] = useState<SectionMsg>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)

  function notify(id: string, tone: 'error' | 'ok', text: string, returnFocus: HTMLElement | null) {
    setNotices((previous) => [
      { id, tone, text, returnFocus }, ...previous.filter((item) => item.id !== id),
    ])
  }

  const load = useCallback(async () => {
    setBanner(null)
    // 游客读不到环境配置（403），这里直接留空，免得进页面就顶一条红条。
    if (guest) { setLoading(false); return }
    setLoading(true)
    try {
      const [env, proj] = await Promise.all([api.getEnvironment(), api.listProjects()])
      setRouteSel(Object.fromEntries(MODEL_ROLES.map((r) => {
        const value = env.model_routes[r.key] ?? ''
        return [r.key, value.startsWith('custom:') ? value : '']
      })))
      setAvailableModels(env.available_models ?? [])
      setTaskBudget(env.task_budget ?? { max_requests: 100, max_cost_yuan: 5, max_runtime_seconds: 1800 })
      setRankings(env.rankings ?? EMPTY_RANKINGS)
      setThinkingEnabled(env.thinking_enabled === true)
      setProjects(proj)
    } catch (err) {
      setBanner(formatApiError(err, '环境配置加载失败'))
    } finally { setLoading(false) }
  }, [guest])

  useEffect(() => {
    void load()
  }, [load])

  async function saveRoutes() {
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const routes = Object.fromEntries(
      MODEL_ROLES.map((r) => [r.key, routeSel[r.key]]).filter(([, v]) => v),
    ) as Record<string, string>
    setBusy('routes')
    setBanner(null)
    try {
      await api.updateEnvironment({
        model_routes: routes, thinking_enabled: thinkingEnabled,
      })
      await load()
      notify('save', 'ok', '模型偏好已保存', returnFocus)
    } catch (err) {
      notify('save', 'error', formatApiError(err), returnFocus)
    } finally {
      setBusy(null)
    }
  }

  async function saveRankings() {
    if (!Number.isInteger(rankings.timeout) || rankings.timeout < 1 || rankings.timeout > 60) {
      setRankMsg({ tone: 'error', text: '超时须为 1–60 秒' })
      return
    }
    if (!Number.isInteger(rankings.limit) || rankings.limit < 1 || rankings.limit > 50) {
      setRankMsg({ tone: 'error', text: '条数须为 1–50' })
      return
    }
    setBusy('rankings')
    setRankMsg(null)
    try {
      await api.updateEnvironment({
        rankings: {
          enabled: rankings.enabled,
          timeout: rankings.timeout,
          limit: rankings.limit,
        },
      })
      await load()
      setRankMsg({ tone: 'ok', text: '扫榜配置已保存' })
    } catch (err) {
      setRankMsg({ tone: 'error', text: formatApiError(err) })
    } finally {
      setBusy(null)
    }
  }

  async function saveBudget() {
    const b = taskBudget
    if (!Number.isSafeInteger(b.max_requests) || b.max_requests < 0 || b.max_requests > 2000000000 ||
        !Number.isSafeInteger(b.max_runtime_seconds) || b.max_runtime_seconds < 0 || b.max_runtime_seconds > 9000000000000 ||
        !Number.isFinite(b.max_cost_yuan) || b.max_cost_yuan < 0 || b.max_cost_yuan > 9000000000000 ||
        Math.abs(b.max_cost_yuan * 1e6 - Math.round(b.max_cost_yuan * 1e6)) > 0.0001) {
      setBudgetMessage({ tone: 'error', text: '预算必须为非负数；请求和秒数为整数，费用最多六位小数。' })
      return
    }
    setBusy('budget')
    try {
      await api.updateEnvironment({ task_budget: b })
      setBudgetMessage({ tone: 'ok', text: '已保存，仅影响新任务。' })
    } catch (e) { setBudgetMessage({ tone: 'error', text: formatApiError(e) }) }
    finally { setBusy(null) }
  }

  return (
    <div className={styles.wrap}>
      <ConnectionNotices items={notices} onDismiss={(id) => setNotices((items) => items.filter((item) => item.id !== id))} />
      <ProjectRail projects={projects} onLogout={logout} />
      <main className={styles.main}>
        <div className={styles.inner}>
          <header className={styles.header}>
            <div>
              <h1>环境配置</h1>
              <div className={styles.crumb}>
                <Link to="/long">返回长篇</Link>
              </div>
            </div>
          </header>

          {banner && <div className="banner banner-error">{banner}</div>}

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>模型偏好</h2>
            <p className={styles.hint}>选择管理员发布的模型；未指定时使用平台默认配置。</p>
            {loading && <p role="status">正在加载模型…</p>}
            {!loading && availableModels.length === 0 && <p className="empty">暂无已发布模型，将使用平台默认配置。</p>}
            <label className={styles.routeRow}>
              <span className={styles.routeLabel}>思考模式</span>
              <select
                className="input"
                aria-label="思考模式"
                value={thinkingEnabled ? '1' : '0'}
                onChange={(e) => setThinkingEnabled(e.target.value === '1')}
              >
                <option value="0">关闭（推荐）</option>
                <option value="1">开启</option>
              </select>
            </label>
            <div className={styles.routeList}>
              {MODEL_ROLES.map((r) => (
                <label key={r.key} className={styles.routeRow}>
                  <span className={styles.routeLabel}>{r.label}</span>
                  <select
                    className="input"
                    value={routeSel[r.key] ?? ''}
                    onChange={(e) => setRouteSel((s) => ({ ...s, [r.key]: e.target.value }))}
                  >
                    {[
                      EMPTY_ROUTE,
                      ...availableModels.map((model) => ({ value: model.id, label: model.name })),
                    ].map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            <div className={styles.saveRow}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy !== null || loading}
                onClick={() => void saveRoutes()}
              >
                {busy === 'routes' ? '保存中…' : '保存模型偏好'}
              </button>
            </div>
          </section>

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>任务总预算</h2>
            <p>每次 Agent 任务共用预算，批次的所有章节累计计算。0 表示不限；修改只影响新任务。</p>
            {([
              ['max_requests', '任务请求上限'],
              ['max_cost_yuan', '任务费用上限（元）'],
              ['max_runtime_seconds', '任务运行上限（秒）'],
            ] as const).map(([key, label]) => <label key={key} className={styles.field}>
              {label}<input className="input" type="number" min="0" step={key === 'max_cost_yuan' ? '0.000001' : '1'} value={taskBudget[key]}
                onChange={e => setTaskBudget(b => ({ ...b, [key]: Number(e.target.value) }))} />
            </label>)}
            <button type="button" className="btn" disabled={busy !== null || loading} onClick={() => void saveBudget()}>保存任务预算</button>
            {budgetMessage && <p role={budgetMessage.tone === 'error' ? 'alert' : 'status'}>{budgetMessage.text}</p>}
          </section>

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>扫榜</h2>
            <p className={styles.hint}>数据来自番茄榜单，只作建书前灵感，不进记忆层。</p>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>启用扫榜</span>
              <select
                className="input"
                aria-label="启用扫榜"
                value={rankings.enabled ? '1' : '0'}
                onChange={(e) => setRankings((r) => ({ ...r, enabled: e.target.value === '1' }))}
              >
                <option value="1">开启</option>
                <option value="0">关闭（只用示例数据）</option>
              </select>
            </label>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>超时（秒）</span>
              <input
                className="input"
                aria-label="扫榜超时"
                type="number"
                min={1}
                max={60}
                value={rankings.timeout}
                onChange={(e) => setRankings((r) => ({ ...r, timeout: Number(e.target.value) }))}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>条数上限</span>
              <input
                className="input"
                aria-label="扫榜条数"
                type="number"
                min={1}
                max={50}
                value={rankings.limit}
                onChange={(e) => setRankings((r) => ({ ...r, limit: Number(e.target.value) }))}
              />
            </label>
            <div className={styles.saveRow}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy !== null || loading}
                onClick={() => void saveRankings()}
              >
                {busy === 'rankings' ? '保存中…' : '保存扫榜配置'}
              </button>
              {rankMsg && (
                <span
                  role="status"
                  className={`${styles.saveMsg} ${rankMsg.tone === 'error' ? styles.saveMsgError : ''}`}
                >
                  {rankMsg.text}
                </span>
              )}
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}
