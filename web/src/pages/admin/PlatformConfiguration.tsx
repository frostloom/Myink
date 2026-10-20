// 平台级配置仅由管理员维护；密钥只写入、不回显。
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import { ConnectionNotices, type ConnectionNotice } from '../../components/ConnectionNotices'
import { GenrePackFields } from '../../components/GenrePackFields'
import { composeFields, type GenreCatalogItem, type GenreFields } from '../../lib/genrePacks'
import { platformApi, type PlatformConfigurationData, type PlatformConnectionInput } from '../../lib/platformApi'
import { api } from '../../lib/api'
import { formatApiError } from '../../lib/apiError'
import type {
  ConnectionTestResult,
  ModelConnection,
  ModelProbeRequest,
  UserDefaults,
} from '../../types'
import type { AdminOutletContext } from './shared'
import styles from '../SettingsPage.module.css'

const MODEL_ROLES = [
  { key: 'planner', label: '规划（planner）' },
  { key: 'writer', label: '写作（writer）' },
  { key: 'validator_l2', label: '语义校验（validator_l2）' },
  { key: 'extract', label: '抽取（extract）' },
  { key: 'audit', label: '审核（audit）' },
  { key: 'summarize', label: '摘要（summarize）' },
]
const EMPTY_ROUTE = { value: '', label: '未指定' }
const DEFAULT_USER_PREFERENCES: UserDefaults = {
  thinking_enabled: false,
  task_budget: { max_requests: 100, max_cost_yuan: 5, max_runtime_seconds: 1800 },
  rankings: { enabled: true, timeout: 10, limit: 10 },
}

type ConnectionField = 'name' | 'base_url' | 'model' | 'api_key'
type FieldProblem = { key: string; text: string } | null

type ModelConnectionDraft = ModelConnection & {
  enabled: boolean
  user_visible: boolean
  api_key: string
}

type ProbeState = {
  loading?: 'models' | 'test'
  models?: string[]
  listError?: string
  test?: ConnectionTestResult
}


function normalizeGenreOverrides(
  overrides: PlatformConfigurationData['genre_packs'],
  catalog: GenreCatalogItem[],
): Record<string, GenreFields> {
  return Object.fromEntries(Object.entries(overrides).map(([id, override]) => {
    const defaults = composeFields(catalog.find((item) => item.id === id))
    const fields = Object.fromEntries((Object.keys(defaults) as Array<keyof GenreFields>)
      .map((key) => [key, override[key] ?? defaults[key]])) as unknown as GenreFields
    return [id, fields]
  }))
}

export default function PlatformConfiguration() {
  const { onForbidden } = useOutletContext<AdminOutletContext>()
  const [version, setVersion] = useState(0)
  const [userDefaults, setUserDefaults] = useState<UserDefaults>(DEFAULT_USER_PREFERENCES)
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [prompts, setPrompts] = useState<Record<string, string>>({})
  const [genrePacks, setGenrePacks] = useState<Record<string, GenreFields>>({})
  const [catalog, setCatalog] = useState<GenreCatalogItem[]>([])
  const [genreId, setGenreId] = useState('')
  const [routeSel, setRouteSel] = useState<Record<string, string>>({})
  const [connectionDrafts, setConnectionDrafts] = useState<ModelConnectionDraft[]>([])
  const [probes, setProbes] = useState<Record<string, ProbeState>>({})
  const [notices, setNotices] = useState<ConnectionNotice[]>([])
  const [fieldProblem, setFieldProblem] = useState<FieldProblem>(null)
  const fieldRefs = useRef(new Map<string, HTMLInputElement>())
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
    setLoading(true)
    setLoaded(false)
    try {
      const [env, items] = await Promise.all([platformApi.getConfiguration(), api.listGenrePacks()])
      setVersion(env.version)
      setUserDefaults(env.user_defaults ?? DEFAULT_USER_PREFERENCES)
      setPrompts(env.prompts)
      setGenrePacks(normalizeGenreOverrides(env.genre_packs, items))
      setCatalog(items)
      setGenreId((id) => id || items[0]?.id || '')
      setRouteSel(Object.fromEntries(MODEL_ROLES.map((r) => {
        const value = env.model_routes[r.key] ?? ''
        return [r.key, value.startsWith('custom:') ? value : '']
      })))
      setConnectionDrafts((env.model_connections ?? []).map((connection) => ({ ...connection, api_key: '' })))
      setLoaded(true)
    } catch (err) {
      if ((err as { status?: number }).status === 403) {
        onForbidden()
        return
      }
      setBanner(formatApiError(err, '平台配置加载失败'))
    } finally { setLoading(false) }
  }, [onForbidden])

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
    const connections: PlatformConnectionInput[] = []
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
        enabled: draft.enabled,
        user_visible: draft.user_visible,
        input_price: draft.input_price,
        output_price: draft.output_price,
        base_url: baseUrl,
        model,
        ...(draft.api_key.trim() ? { api_key: draft.api_key.trim() } : {}),
      })
    }
    try {
      const saved = await platformApi.updateConfiguration({
        version, model_routes: routes, model_connections: connections, prompts, genre_packs: genrePacks, user_defaults: userDefaults,
      })
      setVersion(saved.version)
      setUserDefaults(saved.user_defaults ?? userDefaults)
      setConnectionDrafts(saved.model_connections.map((connection) => ({ ...connection, api_key: '' })))
      setPrompts(saved.prompts)
      setGenrePacks(normalizeGenreOverrides(saved.genre_packs, catalog))
      notify('save', 'ok', '平台配置已保存', returnFocus)
    } catch (err) {
      if ((err as { status?: number }).status === 403) {
        onForbidden()
        return
      }
      const message = (err as { status?: number }).status === 409
        ? '配置已被其他管理员更新。请重新加载后核对并保存；当前草稿仍保留。'
        : formatApiError(err)
      notify('save', 'error', message, returnFocus)
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
      enabled: true,
      user_visible: true,
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
      const res = await platformApi.listModels(probeBody(draft))
      notify(`probe:${draft.id}`, res.ok ? 'ok' : 'error',
        `${draft.name.trim() || '模型连接'}：${res.ok ? `已获取 ${res.models.length} 个模型` : (res.error ?? '获取模型列表失败')}`, returnFocus)
      setProbes((p) => ({ ...p, [draft.id]: {
        loading: undefined, models: res.models, listError: res.ok ? undefined : (res.error ?? '拉取失败'),
      } }))
    } catch (err) {
      if ((err as { status?: number }).status === 403) {
        onForbidden()
        return
      }
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
      const res = await platformApi.testConnection(probeBody(draft))
      notify(`probe:${draft.id}`, res.ok ? 'ok' : 'error',
        `${draft.name.trim() || '模型连接'}：${res.ok ? `连接正常 · ${res.latency_ms} ms` : (res.error ?? '连接测试失败')}`, returnFocus)
      setProbes((p) => ({ ...p, [draft.id]: { ...p[draft.id], loading: undefined, test: res } }))
    } catch (err) {
      if ((err as { status?: number }).status === 403) {
        onForbidden()
        return
      }
      notify(`probe:${draft.id}`, 'error', `${draft.name.trim() || '模型连接'}：${formatApiError(err, '连接测试失败')}`, returnFocus)
      setProbes((p) => ({ ...p, [draft.id]: { loading: undefined, test: {
        ok: false, latency_ms: 0, reply: null, error: formatApiError(err, '测试失败'),
      } } }))
    }
  }

  return (
    <div>
      <ConnectionNotices items={notices} onDismiss={(id) => setNotices((items) => items.filter((item) => item.id !== id))} />
      <div>
        <div className={styles.inner}>
          <header className={styles.header}>
            <div>
              <h1>模型与平台配置</h1>
              <div className={styles.crumb}>
                <Link to="/admin">返回管理概览</Link>
              </div>
            </div>
          </header>

          {banner && <div className="banner banner-error" role="alert">{banner}</div>}
          <div className={styles.saveRow}>
            <button className="btn btn-secondary" disabled={loading || busy !== null} onClick={() => void load()}>
              重新加载配置
            </button>
            <span>版本 {version}</span>
            <button className="btn btn-primary" disabled={loading || !loaded || busy !== null} onClick={() => void saveRoutes()}>
              {busy === 'routes' ? '保存中…' : '保存平台配置'}
            </button>
          </div>
          {loading && <p role="status">正在加载平台配置…</p>}
          <fieldset disabled={loading || !loaded || busy !== null} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
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
                      <div className={styles.probeRow}>
                        <label>
                          <input type="checkbox" checked={connection.enabled}
                            onChange={(e) => updateConnection(connection.id, { enabled: e.target.checked })} />启用连接
                        </label>
                        <label>
                          <input type="checkbox" checked={connection.user_visible}
                            onChange={(e) => updateConnection(connection.id, { user_visible: e.target.checked })} />向用户发布
                        </label>
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
                        ...connectionDrafts.filter((connection) => connection.enabled).map((connection) => ({
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
            </section>

            <section className={`panel ${styles.section}`}>
              <h2 className={styles.sectionTitle}>用户默认设置</h2>
              <p className={styles.hint}>未设置个人偏好的用户将使用这些默认值；已有个人设置继续生效。预算修改仅影响新任务，已有任务保留原预算快照。</p>
              <label className={styles.field}>
                <span>默认思考模式</span>
                <select className="input" value={userDefaults.thinking_enabled ? '1' : '0'}
                  onChange={(e) => setUserDefaults((value) => ({ ...value, thinking_enabled: e.target.value === '1' }))}>
                  <option value="0">关闭</option><option value="1">开启</option>
                </select>
              </label>
              <h3>任务总预算</h3>
              <p className={styles.hint}>0 表示不限，个人预算仍受平台配额和权限限制。</p>
              {([
                ['max_requests', '默认任务请求上限'],
                ['max_cost_yuan', '默认任务费用上限（元）'],
                ['max_runtime_seconds', '默认任务运行上限（秒）'],
              ] as const).map(([key, label]) => (
                <label key={key} className={styles.field}>
                  <span>{label}</span>
                  <input className="input" type="number" min="0" step={key === 'max_cost_yuan' ? '0.000001' : '1'}
                    value={userDefaults.task_budget[key]}
                    onChange={(e) => setUserDefaults((value) => ({ ...value, task_budget: { ...value.task_budget, [key]: Number(e.target.value) } }))} />
                </label>
              ))}
              <h3>扫榜</h3>
              <label className={styles.field}>
                <span>默认启用扫榜</span>
                <select className="input" value={userDefaults.rankings.enabled ? '1' : '0'}
                  onChange={(e) => setUserDefaults((value) => ({ ...value, rankings: { ...value.rankings, enabled: e.target.value === '1' } }))}>
                  <option value="1">开启</option><option value="0">关闭（只用示例数据）</option>
                </select>
              </label>
              {([['timeout', '默认扫榜超时', 60], ['limit', '默认扫榜条数', 50]] as const).map(([key, label, max]) => (
                <label key={key} className={styles.field}>
                  <span>{label}</span>
                  <input className="input" type="number" min="1" max={max} value={userDefaults.rankings[key]}
                    onChange={(e) => setUserDefaults((value) => ({ ...value, rankings: { ...value.rankings, [key]: Number(e.target.value) } }))} />
                </label>
              ))}
            </section>
            <section className={`panel ${styles.section}`}>
              <h2 className={styles.sectionTitle}>角色提示词</h2>
              <p className={styles.hint}>追加到系统指令中，结构化输出规则始终保留。留空使用内置提示词。</p>
              {MODEL_ROLES.map((role) => (
                <label key={role.key} className={styles.field}>
                  <span>{role.label}追加指令</span>
                  <textarea className="textarea" rows={4} value={prompts[role.key] ?? ''}
                    onChange={(e) => setPrompts((previous) => ({ ...previous, [role.key]: e.target.value }))} />
                </label>
              ))}
            </section>
            <section className={`panel ${styles.section}`}>
              <h2 className={styles.sectionTitle}>平台题材包</h2>
              <label className={styles.field}>
                <span>编辑根题材</span>
                <select className="input" value={genreId} onChange={(e) => setGenreId(e.target.value)}>
                  {catalog.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </label>
              <p className={styles.hint}>更改用于新建作品，已有作品保留建书时的快照。</p>
              {genreId && (
                <GenrePackFields
                  value={genrePacks[genreId] ?? composeFields(catalog.find((item) => item.id === genreId))}
                  onChange={(fields) => setGenrePacks((previous) => ({ ...previous, [genreId]: fields }))}
                />
              )}
              <button className="btn btn-secondary" type="button" disabled={!genrePacks[genreId]}
                onClick={() => setGenrePacks((previous) => {
                  const next = { ...previous }
                  delete next[genreId]
                  return next
                })}>
                移除此题材覆盖（保存后生效）
              </button>
            </section>
            <div className={styles.saveRow}>
              <button className="btn btn-primary" type="button" onClick={() => void saveRoutes()}>保存全部更改</button>
            </div>
          </fieldset>
        </div>
      </div>
    </div>
  )
}
