// 账号级环境配置：模型连接/路由 + MCP 扫榜。作品库即可进入，不绑具体书。
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
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
  source: 'qidian',
  tool: '',
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
  const [connMsg, setConnMsg] = useState<SectionMsg>(null)
  const [rankMsg, setRankMsg] = useState<SectionMsg>(null)
  const [rankProbe, setRankProbe] = useState<{ loading: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)

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
    const routes = Object.fromEntries(
      MODEL_ROLES.map((r) => [r.key, routeSel[r.key]]).filter(([, v]) => v),
    ) as Record<string, string>
    setBusy('routes')
    setBanner(null)
    setConnMsg(null)
    const connections: ModelConnectionInput[] = []
    for (const [index, draft] of connectionDrafts.entries()) {
      const name = draft.name.trim()
      const baseUrl = draft.base_url.trim().replace(/\/$/, '')
      const model = draft.model.trim()
      const missing = [
        !name && '连接名称', !baseUrl && '请求地址', !model && '模型 id',
      ].filter(Boolean).join('、')
      if (missing) {
        setBusy(null)
        setConnMsg({ tone: 'error', text: `第 ${index + 1} 个模型连接缺少：${missing}` })
        return
      }
      try {
        const parsed = new URL(baseUrl)
        if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('scheme')
      } catch {
        setBusy(null)
        setConnMsg({ tone: 'error', text: `模型连接“${name}”的请求地址无效` })
        return
      }
      if (!draft.has_api_key && !draft.api_key.trim()) {
        setBusy(null)
        setConnMsg({ tone: 'error', text: `新模型连接“${name}”需要填写 API Key` })
        return
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
      setConnMsg({ tone: 'ok', text: `已保存 ${connections.length} 个模型连接与路由` })
    } catch (err) {
      setConnMsg({ tone: 'error', text: formatApiError(err) })
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
    if (!draft.base_url.trim()) {
      setConnMsg({ tone: 'error', text: '请先填写请求地址' })
      return false
    }
    if (needModel && !draft.model.trim()) {
      setConnMsg({ tone: 'error', text: '请先填写模型 id' })
      return false
    }
    if (!draft.has_api_key && !draft.api_key.trim()) {
      setConnMsg({ tone: 'error', text: '请先填写 API Key' })
      return false
    }
    return true
  }

  async function fetchModels(draft: ModelConnectionDraft) {
    if (!probeReady(draft, false)) return
    setConnMsg(null)
    setProbes((p) => ({ ...p, [draft.id]: { ...p[draft.id], loading: 'models' } }))
    try {
      const res = await api.listModels(probeBody(draft))
      setProbes((p) => ({ ...p, [draft.id]: {
        loading: undefined, models: res.models, listError: res.ok ? undefined : (res.error ?? '拉取失败'),
      } }))
    } catch (err) {
      setProbes((p) => ({ ...p, [draft.id]: {
        loading: undefined, listError: formatApiError(err, '拉取失败'),
      } }))
    }
  }

  async function runTest(draft: ModelConnectionDraft) {
    if (!probeReady(draft, true)) return
    setConnMsg(null)
    setProbes((p) => ({ ...p, [draft.id]: { ...p[draft.id], loading: 'test' } }))
    try {
      const res = await api.testConnection(probeBody(draft))
      setProbes((p) => ({ ...p, [draft.id]: { ...p[draft.id], loading: undefined, test: res } }))
    } catch (err) {
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
          source: rankings.source.trim(),
          tool: rankings.tool.trim(),
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
      <ProjectRail projects={projects} onLogout={logout} />
      <main className={styles.main}>
        <div className={styles.inner}>
          <header className={styles.header}>
            <div>
              <h1>环境配置</h1>
              <div className={styles.crumb}>
                <Link to="/projects">返回作品库</Link>
              </div>
            </div>
          </header>

          {banner && <div className="banner banner-error">{banner}</div>}

          <section className={`panel ${styles.section}`}>
            <div className={styles.connectionTitleRow}>
              <div>
                <h2 className={styles.sectionTitle}>模型连接与路由</h2>
                <p className={styles.hint}>
                  在这里填写自己的模型 API Key，对全部作品生效。支持 OpenAI 兼容接口或 Anthropic 原生接口。
                  密钥由后端加密保存，页面不会再次显示原文。章节费用按官方标价估算，不用手填单价。
                </p>
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
                      <input className="input" aria-label="连接名称" value={connection.name}
                        onChange={(e) => updateConnection(connection.id, { name: e.target.value })}
                        placeholder="例如：DeepSeek / 我的 Claude" />
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
                        <input className="input" value={connection.base_url}
                          onChange={(e) => updateConnection(connection.id, { base_url: e.target.value })}
                          placeholder={connection.protocol === 'anthropic' ? 'https://api.anthropic.com' : 'https://api.openai.com/v1'} />
                      </label>
                      <label className={styles.compactField}>
                        <span>模型 id</span>
                        <input className="input" list={`models-${connection.id}`} value={connection.model}
                          onChange={(e) => updateConnection(connection.id, { model: e.target.value })}
                          placeholder={connection.protocol === 'anthropic' ? 'claude-sonnet-4-5' : 'gpt-4o'} />
                        <datalist id={`models-${connection.id}`}>
                          {(probes[connection.id]?.models ?? []).map((m) => <option key={m} value={m} />)}
                        </datalist>
                      </label>
                      <label className={`${styles.compactField} ${styles.keyField}`}>
                        <span>API Key {connection.has_api_key && <em>已保存，留空即保留</em>}</span>
                        <input className="input" type="password" autoComplete="new-password" value={connection.api_key}
                          onChange={(e) => updateConnection(connection.id, { api_key: e.target.value })}
                          placeholder={connection.has_api_key ? '••••••••（留空保留）' : '输入 API Key'} />
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
              <p className={styles.hint}>规划、写作、校验、抽取、审核、摘要都在这里指定。未指定则该角色不绑定连接。</p>
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
            <p className={styles.hint}>
              能关就关；关不了就把思考拆到独立字段；若仍写进正文开头会自动剥掉。章节只用正文，思考永不落库。开启后规划、审核、抽取、摘要可以使用模型思考。
            </p>
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
              {connMsg && (
                <span
                  role="status"
                  className={`${styles.saveMsg} ${connMsg.tone === 'error' ? styles.saveMsgError : ''}`}
                >
                  {connMsg.text}
                </span>
              )}
            </div>
          </section>

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>外接 MCP 扫榜</h2>
            <p className={styles.hint}>
              建书向导的榜单灵感来自外部 MCP。可改地址、超时和工具名；关闭后只展示内置示例。
            </p>
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
              <span className={styles.fieldLabel}>MCP 地址</span>
              <input
                className="input"
                aria-label="MCP 地址"
                value={rankings.mcp_url}
                onChange={(e) => setRankings((r) => ({ ...r, mcp_url: e.target.value }))}
                placeholder="https://daosearch.io/api/mcp"
              />
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
            <label className={styles.field}>
              <span className={styles.fieldLabel}>来源（source）</span>
              <input
                className="input"
                aria-label="榜单来源"
                value={rankings.source}
                onChange={(e) => setRankings((r) => ({ ...r, source: e.target.value }))}
                placeholder="qidian"
              />
            </label>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>工具名（留空自动发现）</span>
              <input
                className="input"
                aria-label="扫榜工具名"
                value={rankings.tool}
                onChange={(e) => setRankings((r) => ({ ...r, tool: e.target.value }))}
                placeholder="留空则按名称自动匹配"
              />
            </label>
            <div className={styles.probeRow}>
              <button
                type="button"
                className="btn btn-quiet"
                disabled={busy !== null || rankProbe?.loading === true}
                onClick={() => void testRankings()}
              >
                {rankProbe?.loading ? '测试中…' : '测试扫榜连接'}
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
