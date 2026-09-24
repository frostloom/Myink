// 账号级环境配置：模型连接/路由 + 扫榜。作品库即可进入，不绑具体书。
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ConnectionNotices, type ConnectionNotice } from '../components/ConnectionNotices'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import type {
  ConnectionTestResult,
  ModelConnection,
  ModelConnectionInput,
  ModelProbeRequest,
  Project,
  RankingsConfig,
} from '../types'
import styles from './SettingsPage.module.css'

const MODEL_ROLES = [
  { key: 'planner', label: '规划（planner）' },
  { key: 'writer', label: '写作（writer）' },
  { key: 'validator_l2', label: '语义校验（validator_l2）' },
  { key: 'extract', label: '抽取（extract）' },
  { key: 'audit', label: '审核（audit）' },
  { key: 'summarize', label: '摘要（summarize）' },
]
const EMPTY_ROUTE = { value: '', label: '未指定' }

type ConnectionField = 'name' | 'base_url' | 'model' | 'api_key'
type FieldProblem = { key: string; text: string } | null

type ModelConnectionDraft = ModelConnection & { api_key: string }

type ProbeState = {
  loading?: 'models' | 'test'
  models?: string[]
  listError?: string
  test?: ConnectionTestResult
}

type SectionMsg = { tone: 'error' | 'ok'; text: string } | null

const EMPTY_RANKINGS: RankingsConfig = {
  enabled: true,
  mcp_url: 'https://daosearch.io/api/mcp',
  timeout: 10,
  limit: 10,
}

export default function EnvironmentPage() {
  const { logout } = useAuth()
  const guest = useGuest()
  const [projects, setProjects] = useState<Project[]>([])
  const [routeSel, setRouteSel] = useState<Record<string, string>>({})
  const [connectionDrafts, setConnectionDrafts] = useState<ModelConnectionDraft[]>([])
  const [probes, setProbes] = useState<Record<string, ProbeState>>({})
  const [rankings, setRankings] = useState<RankingsConfig>(EMPTY_RANKINGS)
  const [thinkingEnabled, setThinkingEnabled] = useState(false)
  const [notices, setNotices] = useState<ConnectionNotice[]>([])
  const [fieldProblem, setFieldProblem] = useState<FieldProblem>(null)
  const fieldRefs = useRef(new Map<string, HTMLInputElement>())
  const [rankMsg, setRankMsg] = useState<SectionMsg>(null)
  const [rankProbe, setRankProbe] = useState<{ loading: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)

  function notify(id: string, tone: 'error' | 'ok', text: string, returnFocus: HTMLElement | null) {
    setNotices((previous) => [
      { id, tone, text, returnFocus }, ...previous.filter((item) => item.id !== id),
    ])
  }

  function rejectField(id: string, field: ConnectionField, text: string) {
    const key = `${id}:${field}`
    setFieldProblem({ key, text })
    setBusy(null)
    fieldRefs.current.get(key)?.focus()
    fieldRefs.current.get(key)?.scrollIntoView({ block: 'center', behavior: 'auto' })
    return false
  }

  function fieldAttributes(id: string, field: ConnectionField) {
    const key = `${id}:${field}`
    return {
      ref: (element: HTMLInputElement | null) => {
        if (element) fieldRefs.current.set(key, element)
        else fieldRefs.current.delete(key)
      },
      'aria-invalid': fieldProblem?.key === key || undefined,
      'aria-describedby': fieldProblem?.key === key ? `error-${key}` : undefined,
    }
  }

  function fieldMessage(id: string, field: ConnectionField) {
    const key = `${id}:${field}`
    return fieldProblem?.key === key
      ? <span id={`error-${key}`} className={styles.fieldError}>{fieldProblem.text}</span>
      : null
  }

  const load = useCallback(async () => {
    setBanner(null)
    // 游客读不到环境配置（403），这里直接留空，免得进页面就顶一条红条。
    if (guest) return
    try {
      const [env, proj] = await Promise.all([api.getEnvironment(), api.listProjects()])
      setRouteSel(Object.fromEntries(MODEL_ROLES.map((r) => {
        const value = env.model_routes[r.key] ?? ''
        return [r.key, value.startsWith('custom:') ? value : '']
      })))
      setConnectionDrafts((env.model_connections ?? []).map((connection) => ({ ...connection, api_key: '' })))
      setRankings(env.rankings ?? EMPTY_RANKINGS)
      setThinkingEnabled(env.thinking_enabled === true)
      setProjects(proj)
    } catch (err) {
      setBanner(formatApiError(err, '环境配置加载失败'))
    }
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
    setFieldProblem(null)
    const connections: ModelConnectionInput[] = []
    for (const draft of connectionDrafts) {
      const name = draft.name.trim()
      const baseUrl = draft.base_url.trim().replace(/\/$/, '')
      const model = draft.model.trim()
      if (!name) return rejectField(draft.id, 'name', '请填写连接名称')
      if (!baseUrl) return rejectField(draft.id, 'base_url', '请填写请求地址')
      if (!model) return rejectField(draft.id, 'model', '请填写模型 id')
      try {
        const parsed = new URL(baseUrl)
        if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('scheme')
      } catch {
        return rejectField(draft.id, 'base_url', '请输入有效的 http/https 请求地址')
      }
      if (!draft.has_api_key && !draft.api_key.trim()) {
        return rejectField(draft.id, 'api_key', '请填写 API Key')
      }
      connections.push({
        id: draft.id,
        name,
        protocol: draft.protocol,
        base_url: baseUrl,
        model,
        ...(draft.api_key.trim() ? { api_key: draft.api_key.trim() } : {}),
      })
    }
    try {
      await api.updateEnvironment({
        model_routes: routes, model_connections: connections, thinking_enabled: thinkingEnabled,
      })
      await load()
      notify('save', 'ok', '模型连接与路由已保存', returnFocus)
    } catch (err) {
      notify('save', 'error', formatApiError(err), returnFocus)
    } finally {
      setBusy(null)
    }
  }

  function addConnection() {
    setConnectionDrafts((items) => [...items, {
      id: crypto.randomUUID(),
      name: '',
      protocol: 'openai',
      base_url: '',
      model: '',
      api_key: '',
      has_api_key: false,
    }])
  }

  function updateConnection(id: string, patch: Partial<ModelConnectionDraft>) {
    setFieldProblem((problem) => problem && Object.keys(patch).some((field) => problem.key === `${id}:${field}`) ? null : problem)
    setConnectionDrafts((items) => items.map((item) => item.id === id ? { ...item, ...patch } : item))
  }

  function removeConnection(id: string) {
    setConnectionDrafts((items) => items.filter((item) => item.id !== id))
    setRouteSel((routes) => Object.fromEntries(
      Object.entries(routes).map(([role, model]) => [role, model === `custom:${id}` ? '' : model]),
    ))
    setProbes((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
  }

  function probeBody(draft: ModelConnectionDraft): ModelProbeRequest {
    const apiKey = draft.api_key.trim()
    return {
      protocol: draft.protocol,
      base_url: draft.base_url.trim().replace(/\/$/, ''),
      ...(draft.model.trim() ? { model: draft.model.trim() } : {}),
      ...(apiKey ? { api_key: apiKey } : draft.has_api_key ? { connection_id: draft.id } : {}),
    }
  }

  function probeReady(draft: ModelConnectionDraft, needModel: boolean): boolean {
    setFieldProblem(null)
    if (!draft.base_url.trim()) {
      return rejectField(draft.id, 'base_url', '请填写请求地址')
    }
    if (needModel && !draft.model.trim()) {
      return rejectField(draft.id, 'model', '请填写模型 id')
    }
    if (!draft.has_api_key && !draft.api_key.trim()) {
      return rejectField(draft.id, 'api_key', '请填写 API Key')
    }
    return true
  }

  async function fetchModels(draft: ModelConnectionDraft) {
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (!probeReady(draft, false)) return
    setFieldProblem(null)
    setProbes((p) => ({ ...p, [draft.id]: { ...p[draft.id], loading: 'models' } }))
    try {
      const res = await api.listModels(probeBody(draft))
      notify(`probe:${draft.id}`, res.ok ? 'ok' : 'error',
        `${draft.name.trim() || '模型连接'}：${res.ok ? `已获取 ${res.models.length} 个模型` : (res.error ?? '获取模型列表失败')}`, returnFocus)
      setProbes((p) => ({ ...p, [draft.id]: {
        loading: undefined, models: res.models, listError: res.ok ? undefined : (res.error ?? '拉取失败'),
      } }))
    } catch (err) {
      notify(`probe:${draft.id}`, 'error', `${draft.name.trim() || '模型连接'}：${formatApiError(err, '获取模型列表失败')}`, returnFocus)
      setProbes((p) => ({ ...p, [draft.id]: {
        loading: undefined, listError: formatApiError(err, '拉取失败'),
      } }))
    }
  }

  async function runTest(draft: ModelConnectionDraft) {
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (!probeReady(draft, true)) return
    setFieldProblem(null)
    setProbes((p) => ({ ...p, [draft.id]: { ...p[draft.id], loading: 'test' } }))
    try {
      const res = await api.testConnection(probeBody(draft))
      notify(`probe:${draft.id}`, res.ok ? 'ok' : 'error',
        `${draft.name.trim() || '模型连接'}：${res.ok ? `连接正常 · ${res.latency_ms} ms` : (res.error ?? '连接测试失败')}`, returnFocus)
      setProbes((p) => ({ ...p, [draft.id]: { ...p[draft.id], loading: undefined, test: res } }))
    } catch (err) {
      notify(`probe:${draft.id}`, 'error', `${draft.name.trim() || '模型连接'}：${formatApiError(err, '连接测试失败')}`, returnFocus)
      setProbes((p) => ({ ...p, [draft.id]: { loading: undefined, test: {
        ok: false, latency_ms: 0, reply: null, error: formatApiError(err, '测试失败'),
      } } }))
    }
  }

  async function saveRankings() {
    const url = rankings.mcp_url.trim().replace(/\/$/, '')
    if (rankings.enabled) {
      try {
        const parsed = new URL(url)
        if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('scheme')
      } catch {
        setRankMsg({ tone: 'error', text: 'MCP 地址必须是有效的 http/https 地址' })
        return
      }
    }
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
          mcp_url: url,
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

  async function testRankings() {
    const url = rankings.mcp_url.trim().replace(/\/$/, '')
    if (!url) {
      setRankMsg({ tone: 'error', text: '请先填写 MCP 地址' })
      return
    }
    setRankMsg(null)
    setRankProbe({ loading: true, text: '' })
    try {
      const res = await api.testRankings({ mcp_url: url, timeout: rankings.timeout })
      if (res.ok) {
        setRankProbe({ loading: false, text: `连接正常 · 发现 ${res.tools.length} 个工具` })
      } else {
        setRankProbe({ loading: false, text: `连接失败：${res.error ?? '未知错误'}` })
      }
    } catch (err) {
      setRankProbe({ loading: false, text: formatApiError(err, '测试失败') })
    }
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
            <div className={styles.connectionTitleRow}>
              <div>
                <h2 className={styles.sectionTitle}>模型连接与路由</h2>
              </div>
              <button type="button" className="btn btn-secondary" disabled={busy !== null} onClick={addConnection}>
                添加网络模型
              </button>
            </div>

            {connectionDrafts.length === 0 ? (
              <div className="empty">尚未添加网络模型。添加后即可在下方为各 Agent 指定主模型。</div>
            ) : (
              <div className={styles.connectionList}>
                {connectionDrafts.map((connection) => (
                  <article key={connection.id} className={styles.connectionCard}>
                    <div className={styles.connectionHead}>
                      <div className={styles.compactField}>
                      <input {...fieldAttributes(connection.id, 'name')} className="input" aria-label="连接名称" value={connection.name}
                        onChange={(e) => updateConnection(connection.id, { name: e.target.value })}
                        placeholder="例如：DeepSeek / 我的 Claude" />
                      {fieldMessage(connection.id, 'name')}
                      </div>
                      <select className="input" aria-label="接口协议" value={connection.protocol}
                        onChange={(e) => updateConnection(connection.id, { protocol: e.target.value as 'openai' | 'anthropic' })}>
                        <option value="openai">OpenAI 兼容</option>
                        <option value="anthropic">Anthropic 原生</option>
                      </select>
                      <button type="button" className="btn btn-quiet" disabled={busy !== null}
                        onClick={() => removeConnection(connection.id)}>移除</button>
                    </div>
                    <div className={styles.connectionGrid}>
                      <label className={styles.compactField}>
                        <span>请求地址</span>
                        <input {...fieldAttributes(connection.id, 'base_url')} className="input" value={connection.base_url}
                          onChange={(e) => updateConnection(connection.id, { base_url: e.target.value })}
                          placeholder={connection.protocol === 'anthropic' ? 'https://api.anthropic.com' : 'https://api.openai.com/v1'} />
                        {fieldMessage(connection.id, 'base_url')}
                      </label>
                      <label className={styles.compactField}>
                        <span>模型 id</span>
                        <input {...fieldAttributes(connection.id, 'model')} className="input" list={`models-${connection.id}`} value={connection.model}
                          onChange={(e) => updateConnection(connection.id, { model: e.target.value })}
                          placeholder={connection.protocol === 'anthropic' ? 'claude-sonnet-4-5' : 'gpt-4o'} />
                        {fieldMessage(connection.id, 'model')}
                        <datalist id={`models-${connection.id}`}>
                          {(probes[connection.id]?.models ?? []).map((m) => <option key={m} value={m} />)}
                        </datalist>
                      </label>
                      <label className={`${styles.compactField} ${styles.keyField}`}>
                        <span>API Key {connection.has_api_key && <em>已保存，留空即保留</em>}</span>
                        <input {...fieldAttributes(connection.id, 'api_key')} className="input" type="password" autoComplete="new-password" value={connection.api_key}
                          onChange={(e) => updateConnection(connection.id, { api_key: e.target.value })}
                          placeholder={connection.has_api_key ? '••••••••（留空保留）' : '输入 API Key（保存后不再显示原文）'} />
                        {fieldMessage(connection.id, 'api_key')}
                      </label>
                    </div>
                    <div className={styles.probeRow}>
                      <button type="button" className="btn btn-quiet"
                        disabled={busy !== null || probes[connection.id]?.loading !== undefined}
                        onClick={() => void fetchModels(connection)}>
                        {probes[connection.id]?.loading === 'models' ? '获取中…' : '获取模型列表'}
                      </button>
                      <button type="button" className="btn btn-quiet"
                        disabled={busy !== null || probes[connection.id]?.loading !== undefined}
                        onClick={() => void runTest(connection)}>
                        {probes[connection.id]?.loading === 'test' ? '测试中…' : '测试连接'}
                      </button>
                      <span className={styles.probeStatus}>
                        {probes[connection.id]?.test?.ok === true &&
                          `连接正常 · ${probes[connection.id]?.test?.latency_ms ?? 0} ms`}
                        {probes[connection.id]?.test?.ok === false &&
                          `连接失败：${probes[connection.id]?.test?.error ?? '未知错误'}`}
                        {probes[connection.id]?.listError &&
                          `模型列表不可用：${probes[connection.id]?.listError}`}
                        {probes[connection.id]?.models !== undefined && !probes[connection.id]?.listError &&
                          `已获取 ${probes[connection.id]?.models?.length ?? 0} 个模型`}
                      </span>
                    </div>
                  </article>
                ))}
              </div>
            )}

            <div className={styles.routeDivider}>
              <h3>每 Agent 主模型</h3>
            </div>
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
                      ...connectionDrafts.map((connection) => ({
                        value: `custom:${connection.id}`,
                        label: `${connection.name.trim() || '未命名连接'} · ${connection.model.trim() || '未填写模型'}`,
                      })),
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
                disabled={busy !== null}
                onClick={() => void saveRoutes()}
              >
                {busy === 'routes' ? '保存中…' : '保存连接与路由'}
              </button>
            </div>
          </section>

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>扫榜</h2>
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
            <div className={styles.routeDivider}>
              <h3>MCP 服务</h3>
            </div>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>MCP 地址</span>
              <input
                className="input"
                aria-label="MCP 地址"
                value={rankings.mcp_url}
                onChange={(e) => setRankings((r) => ({ ...r, mcp_url: e.target.value }))}
                placeholder="https://daosearch.io/api/mcp"
              />
            </label>
            <div className={styles.probeRow}>
              <button
                type="button"
                className="btn btn-quiet"
                disabled={busy !== null || rankProbe?.loading === true}
                onClick={() => void testRankings()}
              >
                {rankProbe?.loading ? '测试中…' : '测试 MCP 连接'}
              </button>
              {rankProbe && !rankProbe.loading && (
                <span className={styles.probeStatus}>{rankProbe.text}</span>
              )}
            </div>
            <div className={styles.saveRow}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy !== null}
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
