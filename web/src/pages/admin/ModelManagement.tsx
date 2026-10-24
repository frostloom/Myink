import { useCallback, useEffect, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import {
  platformApi,
  type PlatformConfigurationData,
  type PlatformConfigurationInput,
  type PlatformConnection,
  type PlatformConnectionInput,
} from '../../lib/platformApi'
import { formatApiError, formatErrorText } from '../../lib/apiError'
import type { ModelProbeRequest } from '../../types'
import type { AdminOutletContext } from './shared'
import styles from './AdminResources.module.css'
import { AdminDialog } from './AdminDialog'

const PROVIDERS = [
  { id: 'openai', name: 'OpenAI', protocol: 'openai', url: 'https://api.openai.com/v1' },
  { id: 'anthropic', name: 'Anthropic', protocol: 'anthropic', url: 'https://api.anthropic.com/v1' },
  { id: 'deepseek', name: 'DeepSeek', protocol: 'openai', url: 'https://api.deepseek.com/v1' },
  {
    id: 'dashscope',
    name: '通义千问（DashScope）',
    protocol: 'openai',
    url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  },
  { id: 'zhipu', name: '智谱 GLM', protocol: 'openai', url: 'https://open.bigmodel.cn/api/paas/v4' },
  { id: 'custom', name: '自定义 / 中转服务', protocol: 'openai', url: '' },
] as const
function providerFor(connection: PlatformConnection) {
  return PROVIDERS.find((p) => p.url && connection.base_url.replace(/\/$/, '') === p.url) ?? PROVIDERS[5]
}
function input(connection: PlatformConnection): PlatformConnectionInput {
  return {
    id: connection.id,
    name: connection.name,
    protocol: connection.protocol,
    base_url: connection.base_url,
    model: connection.model,
    enabled: connection.enabled,
    user_visible: connection.user_visible,
    input_price: connection.input_price,
    output_price: connection.output_price,
  }
}

type Draft = PlatformConnection & { api_key: string }
export default function ModelManagement() {
  const { onForbidden } = useOutletContext<AdminOutletContext>()
  const [configuration, setConfiguration] = useState<PlatformConfigurationData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [provider, setProvider] = useState('custom')
  const [deleting, setDeleting] = useState<PlatformConnection | null>(null)
  const [replacement, setReplacement] = useState('')
  const [busy, setBusy] = useState(false)
  const [probeBusy, setProbeBusy] = useState(false)
  const [probeResult, setProbeResult] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [probeError, setProbeError] = useState('')
  const [showKey, setShowKey] = useState(false)
  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setConfiguration(await platformApi.getConfiguration())
    } catch (err) {
      if ((err as { status?: number }).status === 403) onForbidden()
      setError(formatApiError(err, '模型加载失败'))
    } finally {
      setLoading(false)
    }
  }, [onForbidden])
  useEffect(() => {
    void load()
  }, [load])
  function edit(connection?: PlatformConnection) {
    setError('')
    setNotice('')
    setModels([])
    setProbeResult('')
    setProbeError('')
    setShowKey(false)
    setProvider(connection ? providerFor(connection).id : 'openai')
    setDraft(
      connection
        ? { ...connection, api_key: '' }
        : {
            id: crypto.randomUUID(),
            name: '',
            protocol: 'openai',
            base_url: PROVIDERS[0].url,
            model: '',
            api_key: '',
            has_api_key: false,
            enabled: true,
            user_visible: true,
          },
    )
  }
  function patch(values: Partial<Draft>) {
    setDraft((previous) => (previous ? { ...previous, ...values } : previous))
    setProbeResult('')
    setProbeError('')
    setModels([])
  }
  async function persist(connections: PlatformConnectionInput[], routes: Record<string, string>) {
    if (!configuration) return false
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const saved = await platformApi.updateConfiguration({
        ...configuration,
        model_connections: connections,
        model_routes: routes,
        genre_packs: configuration.genre_packs as PlatformConfigurationInput['genre_packs'],
      })
      setConfiguration(saved)
      setNotice('模型配置已保存')
      return true
    } catch (err) {
      if ((err as { status?: number }).status === 403) onForbidden()
      setError(
        (err as { status?: number }).status === 409
          ? '配置已被其他管理员更新，草稿已保留。请取消后重新加载配置，再核对更改。'
          : formatApiError(err, '保存失败，请重试'),
      )
      return false
    } finally {
      setBusy(false)
    }
  }
  async function save() {
    if (!draft || !configuration) return
    const changed = {
      ...input(draft),
      name: draft.name.trim(),
      base_url: draft.base_url.trim().replace(/\/$/, ''),
      model: draft.model.trim(),
      ...(draft.api_key.trim() ? { api_key: draft.api_key.trim() } : {}),
    }
    if (
      !changed.name ||
      !changed.model ||
      !changed.base_url ||
      (!draft.has_api_key && !draft.api_key.trim())
    ) {
      setError('请填写显示名称、模型 ID、请求地址和 API Key')
      return
    }
    try {
      if (!['http:', 'https:'].includes(new URL(changed.base_url).protocol)) throw new Error('protocol')
    } catch {
      setError('请输入有效的 http/https 请求地址')
      return
    }
    if (!changed.enabled && Object.values(configuration.model_routes).includes(`custom:${draft.id}`)) {
      setError('此模型仍用于平台任务，请先在“模型分配”中更换模型，再停用。')
      return
    }
    const routes = { ...configuration.model_routes }
    if (!routes.writer) {
      if (!changed.enabled) {
        setError('请先启用第一个模型，作为平台的默认写作模型。')
        return
      }
      routes.writer = `custom:${draft.id}`
    }
    const exists = configuration.model_connections.some((c) => c.id === draft.id)
    const connections = configuration.model_connections.map((c) => (c.id === draft.id ? changed : input(c)))
    if (!exists) connections.push(changed)
    if (await persist(connections, routes)) setDraft(null)
  }
  async function remove() {
    if (!deleting || !configuration) return
    const connections = configuration.model_connections.filter((c) => c.id !== deleting.id).map(input)
    const routes = Object.fromEntries(
      Object.entries(configuration.model_routes).filter(([, value]) => value !== `custom:${deleting.id}`),
    )
    if (connections.length && configuration.model_routes.writer === `custom:${deleting.id}`) {
      if (!connections.some((c) => c.enabled && `custom:${c.id}` === replacement)) {
        setError('请选择一个已启用的替代写作模型，再确认删除。')
        return
      }
      routes.writer = replacement
    }
    if (await persist(connections, routes)) setDeleting(null)
  }
  async function probe(operation: 'models' | 'test') {
    if (!draft) return
    if (
      !draft.base_url.trim() ||
      (!draft.has_api_key && !draft.api_key.trim()) ||
      (operation === 'test' && !draft.model.trim())
    ) {
      setProbeError('请先填写请求地址、API Key 和测试所需的模型 ID')
      return
    }
    const body: ModelProbeRequest = {
      protocol: draft.protocol,
      base_url: draft.base_url.trim(),
      ...(draft.model.trim() ? { model: draft.model.trim() } : {}),
      ...(draft.api_key.trim() ? { api_key: draft.api_key.trim() } : { connection_id: draft.id }),
    }
    setProbeBusy(true)
    setProbeResult('')
    setProbeError('')
    try {
      if (operation === 'models') {
        const result = await platformApi.listModels(body)
        if (!result.ok) {
          setProbeError(
            formatErrorText(result.error, undefined, '获取模型列表失败，请检查地址和接口支持情况'),
          )
          return
        }
        setModels(result.models)
        setProbeResult(`已获取 ${result.models.length} 个模型，点击下方模型即可选用`)
      } else {
        const result = await platformApi.testConnection(body)
        if (!result.ok) {
          setProbeError(formatErrorText(result.error, undefined, '连接测试失败，请检查模型 ID 和服务配置'))
          return
        }
        setProbeResult(`连接正常 · ${result.latency_ms ?? 0} ms`)
      }
    } catch (err) {
      if ((err as { status?: number }).status === 403) onForbidden()
      setProbeError(
        formatApiError(err, operation === 'models' ? '获取模型列表失败，请重试' : '连接测试失败，请重试'),
      )
    } finally {
      setProbeBusy(false)
    }
  }
  const filtered = (configuration?.model_connections ?? []).filter((c) =>
    `${c.name} ${c.model} ${providerFor(c).name}`.toLowerCase().includes(search.trim().toLowerCase()),
  )
  const editingExisting = draft && configuration?.model_connections.some((c) => c.id === draft.id)
  return (
    <div className={styles.page}>
      <header className={styles.pageHead}>
        <div>
          <h1>AI 模型</h1>
          <p>管理平台内置模型和自建服务，供创作与平台任务使用。</p>
          <Link to="/admin/model-routes">调整模型分配</Link>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!configuration || loading}
          onClick={() => edit()}
        >
          新增模型
        </button>
      </header>
      {!draft && !deleting && error && (
        <div role="alert" className="banner banner-error">
          {error}
        </div>
      )}
      {notice && <div role="status">{notice}</div>}
      <div className={styles.toolbar}>
        <input
          className="input"
          aria-label="搜索模型"
          placeholder="搜索名称、模型 ID 或服务商"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span>{filtered.length} 个模型</span>
        <button className="btn btn-quiet" disabled={loading} onClick={() => void load()}>
          重新加载配置
        </button>
      </div>
      {loading ? (
        <p role="status">正在加载模型…</p>
      ) : !configuration ? (
        <p className="empty">模型加载失败，请重新加载配置。</p>
      ) : filtered.length === 0 ? (
        <div className={styles.empty}>
          <h2>{search ? '没有匹配的模型' : '还没有添加模型'}</h2>
          <p>{search ? '试试其他名称或模型 ID。' : '点击“新增模型”，填写你自己的模型服务地址和密钥。'}</p>
        </div>
      ) : (
        <div className={styles.grid}>
          {filtered.map((connection) => (
            <article key={connection.id} className={styles.card}>
              <div className={styles.cardHead}>
                <span className={styles.provider}>{providerFor(connection).name}</span>
                <span>{connection.enabled ? '已启用' : '已停用'}</span>
              </div>
              <h2>{connection.name}</h2>
              {connection.model !== connection.name && <code>{connection.model}</code>}
              <p className={styles.address}>{connection.base_url}</p>
              <div className={styles.tags}>
                {connection.origin === 'builtin' && <span>平台内置</span>}
                <span>{connection.protocol === 'anthropic' ? 'Anthropic 原生' : 'OpenAI 兼容'}</span>
                <span>{connection.user_visible ? '用户可选' : '仅后台使用'}</span>
                <span>{connection.has_api_key ? '密钥已保存' : '待配置密钥'}</span>
              </div>
              <footer>
                <button
                  type="button"
                  className="btn btn-secondary"
                  aria-label={`编辑 ${connection.name}`}
                  onClick={() => edit(connection)}
                >
                  编辑
                </button>
                <button
                  type="button"
                  className="btn btn-quiet"
                  aria-label={`删除 ${connection.name}`}
                  onClick={() => {
                    setError('')
                    setReplacement('')
                    setDeleting(connection)
                  }}
                >
                  删除
                </button>
              </footer>
            </article>
          ))}
        </div>
      )}
      {draft && (
        <AdminDialog
          title={editingExisting ? '编辑模型' : '新增模型'}
          busy={busy || probeBusy}
          onClose={() => {
            setDraft(null)
            setError('')
          }}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void save()
            }}
          >
            {!configuration?.model_routes.writer && (
              <p className={styles.hint}>第一个模型将作为默认写作模型，之后可在“模型分配”中调整。</p>
            )}
            <fieldset disabled={busy || probeBusy} className={styles.fields}>
              <label>
                显示名称
                <input
                  className="input"
                  autoFocus
                  required
                  value={draft.name}
                  onChange={(e) => patch({ name: e.target.value })}
                  placeholder="例如：我的 DeepSeek"
                />
              </label>
              <label>
                模型服务商
                <select
                  className="input"
                  value={provider}
                  onChange={(e) => {
                    const next = PROVIDERS.find((p) => p.id === e.target.value)!
                    const previous = PROVIDERS.find((p) => p.id === provider)
                    setProvider(next.id)
                    patch({
                      protocol: next.protocol,
                      ...(!draft.base_url || draft.base_url === previous?.url ? { base_url: next.url } : {}),
                    })
                  }}
                >
                  {PROVIDERS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                请求地址
                <input
                  className="input"
                  required
                  type="url"
                  value={draft.base_url}
                  onChange={(e) => patch({ base_url: e.target.value })}
                  placeholder="https://api.example.com/v1"
                />
              </label>
              <label>
                接口协议
                <select
                  className="input"
                  value={draft.protocol}
                  onChange={(e) => patch({ protocol: e.target.value as 'openai' | 'anthropic' })}
                >
                  <option value="openai">OpenAI 兼容</option>
                  <option value="anthropic">Anthropic 原生</option>
                </select>
              </label>
              <label>
                模型 ID
                <input
                  className="input"
                  required
                  value={draft.model}
                  onChange={(e) => patch({ model: e.target.value })}
                  placeholder="填写服务商提供的模型 ID"
                />
              </label>
              <label>
                API Key
                <input
                  className="input"
                  type={showKey ? 'text' : 'password'}
                  autoComplete="new-password"
                  required={!draft.has_api_key}
                  value={draft.api_key}
                  onChange={(e) => patch({ api_key: e.target.value })}
                  placeholder={draft.has_api_key ? '已保存，留空保留原密钥' : '填写 API Key'}
                />
              </label>
              <button type="button" className="btn btn-quiet" onClick={() => setShowKey(!showKey)}>
                {showKey ? '隐藏输入的密钥' : '显示输入的密钥'}
              </button>
              <div className={styles.options}>
                <label>
                  <input
                    type="checkbox"
                    checked={draft.enabled}
                    onChange={(e) => patch({ enabled: e.target.checked })}
                  />
                  启用模型
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={draft.user_visible}
                    onChange={(e) => patch({ user_visible: e.target.checked })}
                  />
                  向用户发布
                </label>
              </div>
              <div className={styles.probe}>
                <button type="button" className="btn btn-secondary" onClick={() => void probe('models')}>
                  获取模型列表
                </button>
                <button type="button" className="btn btn-secondary" onClick={() => void probe('test')}>
                  测试连接
                </button>
              </div>
            </fieldset>
            {probeBusy && <p role="status">正在连接模型服务…</p>}
            {probeResult && <p role="status">{probeResult}</p>}
            {probeError && <p role="alert">{probeError}</p>}
            {models.length > 0 && (
              <div className={styles.suggestions} aria-label="上游可用模型">
                {models.map((model) => (
                  <button
                    className="btn btn-quiet"
                    type="button"
                    key={model}
                    disabled={busy || probeBusy}
                    onClick={() => {
                      setDraft({ ...draft, model })
                      setProbeResult('')
                      setProbeError('')
                    }}
                  >
                    {model}
                  </button>
                ))}
              </div>
            )}
            {error && (
              <p role="alert" className="banner banner-error">
                {error}
              </p>
            )}
            <footer className={styles.actions}>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busy || probeBusy}
                onClick={() => {
                  setDraft(null)
                  setError('')
                }}
              >
                取消
              </button>
              <button className="btn btn-primary" type="submit" disabled={busy || probeBusy}>
                {busy ? '保存中…' : '保存模型'}
              </button>
            </footer>
          </form>
        </AdminDialog>
      )}
      {deleting && (
        <AdminDialog
          title="删除模型"
          busy={busy}
          onClose={() => {
            setDeleting(null)
            setError('')
          }}
        >
          <p>确认删除“{deleting.name}”？对应角色的模型分配也会被清除，请及时重新分配。</p>
          {configuration?.model_routes.writer === `custom:${deleting.id}` &&
            configuration.model_connections.length > 1 && (
              <label className={styles.replacement}>
                替代写作模型
                <select
                  className="input"
                  value={replacement}
                  disabled={busy}
                  onChange={(e) => setReplacement(e.target.value)}
                >
                  <option value="">请选择替代写作模型</option>
                  {configuration.model_connections
                    .filter((c) => c.id !== deleting.id && c.enabled)
                    .map((c) => (
                      <option key={c.id} value={`custom:${c.id}`}>
                        {c.name}
                      </option>
                    ))}
                </select>
              </label>
            )}
          {error && <p role="alert">{error}</p>}
          <footer className={styles.actions}>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busy}
              onClick={() => {
                setDeleting(null)
                setError('')
              }}
            >
              取消
            </button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void remove()}>
              {busy ? '删除中…' : '确认删除'}
            </button>
          </footer>
        </AdminDialog>
      )}
    </div>
  )
}
