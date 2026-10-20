// 写作偏好仅选择平台发布模型；服务地址和凭证由管理员维护。
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ConnectionNotices, type ConnectionNotice } from '../components/ConnectionNotices'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import type { EnvironmentSettings, Project, RankingsConfig, TaskBudgetLimits, UserDefaults } from '../types'
import styles from './SettingsPage.module.css'

const MODEL_ROLES = [
  { key: 'planner', label: '规划（planner）' },
  { key: 'writer', label: '写作（writer）' },
]
const EMPTY_ROUTE = { value: '', label: '跟随平台默认' }
const DEFAULT_BUDGET: TaskBudgetLimits = { max_requests: 100, max_cost_yuan: 5, max_runtime_seconds: 1800 }
const DEFAULT_RANKINGS: RankingsConfig = { enabled: true, timeout: 10, limit: 10 }
const BUDGET_FIELDS = [
  ['max_requests', '任务请求上限'],
  ['max_cost_yuan', '任务费用上限（元）'],
  ['max_runtime_seconds', '任务运行上限（秒）'],
] as const

type SectionMsg = { tone: 'error' | 'ok'; text: string } | null
type Preferences = UserDefaults & { model_routes: Record<string, string> }
type PreferenceUpdate = Parameters<typeof api.updateEnvironment>[0]
type PendingDrafts = { original: Preferences; draft: Preferences; committed: string[] }

function preserveDrafts<T extends object>(server: T, draft: T, original: T, prefix: string, committed: string[]): T {
  return Object.fromEntries((Object.keys(server) as Array<keyof T>).map((key) => [key,
    draft[key] !== original[key] && !committed.includes(`${prefix}.${String(key)}`) ? draft[key] : server[key],
  ])) as T
}

function changedFields<T extends object>(draft: T, original: T): Partial<T> {
  return Object.fromEntries((Object.keys(draft) as Array<keyof T>)
    .filter((key) => draft[key] !== original[key])
    .map((key) => [key, draft[key]])) as Partial<T>
}

export default function EnvironmentPage() {
  const { logout } = useAuth()
  const guest = useGuest()
  const [projects, setProjects] = useState<Project[]>([])
  const [routeSel, setRouteSel] = useState<Record<string, string>>({})
  const [availableModels, setAvailableModels] = useState<Array<{ id: string; name: string }>>([])
  const [loading, setLoading] = useState(true)
  const [original, setOriginal] = useState<Preferences | null>(null)
  const [overriddenFields, setOverriddenFields] = useState<string[] | undefined>()
  const [expanded, setExpanded] = useState(false)
  const [taskBudget, setTaskBudget] = useState<TaskBudgetLimits>(DEFAULT_BUDGET)
  const [budgetMessage, setBudgetMessage] = useState<SectionMsg>(null)
  const [rankings, setRankings] = useState<RankingsConfig>(DEFAULT_RANKINGS)
  const [thinkingEnabled, setThinkingEnabled] = useState(false)
  const [notices, setNotices] = useState<ConnectionNotice[]>([])
  const [rankMsg, setRankMsg] = useState<SectionMsg>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)
  const disabled = loading || original === null || busy !== null || guest

  function notify(id: string, tone: 'error' | 'ok', text: string, returnFocus: HTMLElement | null) {
    setNotices((previous) => [
      { id, tone, text, returnFocus }, ...previous.filter((item) => item.id !== id),
    ])
  }

  const applyEnvironment = useCallback((env: EnvironmentSettings, pending?: PendingDrafts) => {
    const routes = Object.fromEntries(MODEL_ROLES.map((role) => {
      const value = env.model_routes[role.key] ?? ''
      return [role.key, value.startsWith('custom:') ? value : '']
    }))
    const preferences = {
      model_routes: routes,
      task_budget: env.task_budget ?? DEFAULT_BUDGET,
      rankings: env.rankings ?? DEFAULT_RANKINGS,
      thinking_enabled: env.thinking_enabled === true,
    }
    setOriginal(preferences)
    setRouteSel(pending ? preserveDrafts(routes, pending.draft.model_routes, pending.original.model_routes, 'model_routes', pending.committed) : routes)
    setTaskBudget(pending ? preserveDrafts(preferences.task_budget, pending.draft.task_budget, pending.original.task_budget, 'task_budget', pending.committed) : preferences.task_budget)
    setRankings(pending ? preserveDrafts(preferences.rankings, pending.draft.rankings, pending.original.rankings, 'rankings', pending.committed) : preferences.rankings)
    setThinkingEnabled(pending && pending.draft.thinking_enabled !== pending.original.thinking_enabled && !pending.committed.includes('thinking_enabled')
      ? pending.draft.thinking_enabled : preferences.thinking_enabled)
    setAvailableModels(env.available_models ?? [])
    setOverriddenFields(env.overridden_fields)
    setBudgetMessage(null)
    setRankMsg(null)
  }, [])

  const load = useCallback(async () => {
    setBanner(null)
    setOriginal(null)
    if (guest) { setLoading(false); return }
    setLoading(true)
    try {
      const [env, proj] = await Promise.all([api.getEnvironment(), api.listProjects()])
      applyEnvironment(env)
      setProjects(proj)
    } catch (err) {
      setBanner(formatApiError(err, '高级设置加载失败'))
    } finally { setLoading(false) }
  }, [guest, applyEnvironment])

  useEffect(() => { void load() }, [load])

  function applySavedEnvironment(env: EnvironmentSettings, committed: string[]) {
    applyEnvironment(env, original ? {
      original, draft: { model_routes: routeSel, task_budget: taskBudget, rankings, thinking_enabled: thinkingEnabled }, committed,
    } : undefined)
  }

  async function saveRoutes() {
    if (disabled || !original) return
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const routes = changedFields(routeSel, original.model_routes)
    const body: PreferenceUpdate = {}
    if (Object.keys(routes).length) body.model_routes = routes as Record<string, string>
    if (thinkingEnabled !== original.thinking_enabled) body.thinking_enabled = thinkingEnabled
    setBusy('routes')
    try {
      applySavedEnvironment(await api.updateEnvironment(body), [
        ...Object.keys(routes).map((key) => `model_routes.${key}`),
        ...(body.thinking_enabled !== undefined ? ['thinking_enabled'] : []),
      ])
      notify('save', 'ok', '模型偏好已保存', returnFocus)
    } catch (err) {
      notify('save', 'error', formatApiError(err), returnFocus)
    } finally { setBusy(null) }
  }

  async function saveRankings() {
    if (disabled || !original) return
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
      const changes = changedFields(rankings, original.rankings)
      applySavedEnvironment(await api.updateEnvironment({ rankings: changes }), Object.keys(changes).map((key) => `rankings.${key}`))
      setRankMsg({ tone: 'ok', text: '扫榜配置已保存' })
    } catch (err) {
      setRankMsg({ tone: 'error', text: formatApiError(err) })
    } finally { setBusy(null) }
  }

  async function saveBudget() {
    if (disabled || !original) return
    const b = taskBudget
    if (!Number.isSafeInteger(b.max_requests) || b.max_requests < 0 || b.max_requests > 2000000000 ||
        !Number.isSafeInteger(b.max_runtime_seconds) || b.max_runtime_seconds < 0 || b.max_runtime_seconds > 9000000000000 ||
        !Number.isFinite(b.max_cost_yuan) || b.max_cost_yuan < 0 || b.max_cost_yuan > 9000000000000 ||
        Math.abs(b.max_cost_yuan * 1e6 - Math.round(b.max_cost_yuan * 1e6)) > 0.0001) {
      setBudgetMessage({ tone: 'error', text: '预算必须为非负数；请求和秒数为整数，费用最多六位小数。' })
      return
    }
    setBusy('budget')
    setBudgetMessage(null)
    try {
      const changes = changedFields(b, original.task_budget)
      applySavedEnvironment(await api.updateEnvironment({ task_budget: changes }), Object.keys(changes).map((key) => `task_budget.${key}`))
      setBudgetMessage({ tone: 'ok', text: '已保存，仅影响新任务。' })
    } catch (err) { setBudgetMessage({ tone: 'error', text: formatApiError(err) }) }
    finally { setBusy(null) }
  }

  async function resetPreference(path: string) {
    if (disabled) return
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setBusy(path)
    try {
      applySavedEnvironment(await api.updateEnvironment({ reset_preferences: [path] }), [path])
      notify('reset', 'ok', '已恢复平台默认', returnFocus)
    } catch (err) {
      notify('reset', 'error', formatApiError(err), returnFocus)
    } finally { setBusy(null) }
  }

  function preferenceStatus(path: string, label: string) {
    const overridden = overriddenFields?.includes(path)
    return <div className={styles.preferenceStatus}>
      <span>{overridden === undefined ? '覆盖状态暂不可用' : overridden ? '当前使用个人设置' : '当前使用平台默认'}</span>
      <button type="button" className="btn btn-quiet" disabled={disabled || overridden === false}
        onClick={() => void resetPreference(path)}>恢复{label}默认值</button>
    </div>
  }

  return (
    <div className={styles.wrap}>
      <ConnectionNotices items={notices} onDismiss={(id) => setNotices((items) => items.filter((item) => item.id !== id))} />
      <ProjectRail projects={projects} onLogout={logout} />
      <main className={styles.main}>
        <div className={styles.inner}>
          <header className={styles.header}>
            <div>
              <h1>高级设置</h1>
              <div className={styles.crumb}><Link to="/long">返回长篇</Link></div>
            </div>
          </header>
          <p className={styles.hint}>平台已提供创作默认设置，可直接开始写作。如需调整个人偏好，请展开高级设置。</p>
          {banner && <div className="banner banner-error" role="alert">{banner}</div>}
          {banner && <button className="btn btn-secondary" disabled={loading || busy !== null} onClick={() => void load()}>重新加载高级设置</button>}
          {loading && <p role="status">正在加载高级设置…</p>}
          {guest && <p className={styles.hint}>登录后可调整个人偏好。</p>}
          <div>
            <button className="btn btn-secondary" type="button" aria-expanded={expanded} aria-controls="advanced-preferences"
              onClick={() => setExpanded((value) => !value)}>{expanded ? '收起高级设置' : '展开高级设置'}</button>
          </div>
          {expanded && <div id="advanced-preferences" className={styles.advancedPreferences}>
            <section className={`panel ${styles.section}`}>
              <h2 className={styles.sectionTitle}>模型偏好</h2>
              <p className={styles.hint}>选择管理员发布的模型；未指定时使用平台默认配置。保存仅更新已修改的字段。</p>
              {!loading && availableModels.length === 0 && <p className="empty">暂无已发布模型，将使用平台默认配置。</p>}
              <div>
                <label className={styles.routeRow}>
                  <span className={styles.routeLabel}>思考模式</span>
                  <select className="input" disabled={disabled} value={thinkingEnabled ? '1' : '0'}
                    onChange={(e) => setThinkingEnabled(e.target.value === '1')}>
                    <option value="0">关闭</option><option value="1">开启</option>
                  </select>
                </label>
                {preferenceStatus('thinking_enabled', '思考模式')}
              </div>
              <div className={styles.routeList}>
                {MODEL_ROLES.map((role) => <div key={role.key}>
                  <label className={styles.routeRow}>
                    <span className={styles.routeLabel}>{role.label}</span>
                    <select className="input" disabled={disabled} value={routeSel[role.key] ?? ''}
                      onChange={(e) => setRouteSel((value) => ({ ...value, [role.key]: e.target.value }))}>
                      {[EMPTY_ROUTE, ...availableModels.map((model) => ({ value: model.id, label: model.name }))].map((option) =>
                        <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                  </label>
                  {preferenceStatus(`model_routes.${role.key}`, role.label)}
                </div>)}
              </div>
              <div className={styles.saveRow}>
                <button type="button" className="btn btn-primary" disabled={disabled} onClick={() => void saveRoutes()}>
                  {busy === 'routes' ? '保存中…' : '保存模型偏好'}
                </button>
              </div>
            </section>
            <section className={`panel ${styles.section}`}>
              <h2 className={styles.sectionTitle}>任务总预算</h2>
              <p className={styles.hint}>每次 Agent 任务共用预算，批次的所有章节累计计算。0 表示不限；修改只影响新任务，仍受平台配额和权限限制。</p>
              {BUDGET_FIELDS.map(([key, label]) => <div key={key}>
                <label className={styles.field}>
                  <span>{label}</span>
                  <input className="input" type="number" min="0" step={key === 'max_cost_yuan' ? '0.000001' : '1'}
                    disabled={disabled} value={taskBudget[key]}
                    onChange={(e) => setTaskBudget((value) => ({ ...value, [key]: Number(e.target.value) }))} />
                </label>
                {preferenceStatus(`task_budget.${key}`, label)}
              </div>)}
              <button type="button" className="btn" disabled={disabled} onClick={() => void saveBudget()}>保存任务预算</button>
              {budgetMessage && <p role={budgetMessage.tone === 'error' ? 'alert' : 'status'}>{budgetMessage.text}</p>}
            </section>
            <section className={`panel ${styles.section}`}>
              <h2 className={styles.sectionTitle}>扫榜</h2>
              <p className={styles.hint}>数据来自番茄榜单，只作建书前灵感，不进记忆层。</p>
              <div>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>启用扫榜</span>
                  <select className="input" disabled={disabled} value={rankings.enabled ? '1' : '0'}
                    onChange={(e) => setRankings((value) => ({ ...value, enabled: e.target.value === '1' }))}>
                    <option value="1">开启</option><option value="0">关闭（只用示例数据）</option>
                  </select>
                </label>
                {preferenceStatus('rankings.enabled', '启用扫榜')}
              </div>
              {([['timeout', '扫榜超时', '超时（秒）', 60], ['limit', '扫榜条数', '条数上限', 50]] as const).map(([key, label, title, max]) => <div key={key}>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>{title}</span>
                  <input className="input" aria-label={label} type="number" min="1" max={max} disabled={disabled} value={rankings[key]}
                    onChange={(e) => setRankings((value) => ({ ...value, [key]: Number(e.target.value) }))} />
                </label>
                {preferenceStatus(`rankings.${key}`, label)}
              </div>)}
              <div className={styles.saveRow}>
                <button type="button" className="btn btn-primary" disabled={disabled} onClick={() => void saveRankings()}>
                  {busy === 'rankings' ? '保存中…' : '保存扫榜配置'}
                </button>
                {rankMsg && <span role={rankMsg.tone === 'error' ? 'alert' : 'status'} className={`${styles.saveMsg} ${rankMsg.tone === 'error' ? styles.saveMsgError : ''}`}>{rankMsg.text}</span>}
              </div>
            </section>
          </div>}
        </div>
      </main>
    </div>
  )
}
