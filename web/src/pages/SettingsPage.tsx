// 创作设置页（阶段 4）：文风档案（查看/编辑/保存 + 样本提取确认 + 预设导入）+ 每 Agent 模型路由。
// 布局：rail（复用）+ 主区卡片纵向堆叠，保持与工作台一致的简洁风格。
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { api, ApiError } from '../lib/api'
import type { ConnectionTestResult, ModelConnection, ModelConnectionInput, ModelProbeRequest, Project, ProjectSettings, SkillPreset, StyleProfile } from '../types'
import styles from './SettingsPage.module.css'

// 文风档案键展示（§7.12 种子书档案键；数组键按行编辑，其余透传）
const KEY_LABELS: Record<string, string> = {
  pov: '视角',
  sentence_style: '句式风格',
  dialogue: '对话腔调',
  forbidden: '禁用表达（每行一条）',
  fatigue_words: '疲劳高频词（每行一条）',
  fatigue_patterns: '疲劳句式模式（每行一条）',
}
const KEY_ORDER = ['pov', 'sentence_style', 'dialogue', 'forbidden', 'fatigue_words', 'fatigue_patterns']

// 可配置角色 + 模型档（§6.10：planner/writer/validator_l2/extract；空值 = 不覆盖回落默认链）
const MODEL_ROLES = [
  { key: 'planner', label: '规划（planner）' },
  { key: 'writer', label: '写作（writer）' },
  { key: 'validator_l2', label: '语义校验（validator_l2）' },
  { key: 'extract', label: '抽取（extract）' },
]
const BUILTIN_MODEL_OPTIONS = [
  { value: '', label: '默认' },
  { value: 'deepseek-v4-flash', label: 'deepseek-v4-flash' },
  { value: 'deepseek-v4-pro', label: 'deepseek-v4-pro' },
]

type ModelConnectionDraft = ModelConnection & { api_key: string }

/** 单张连接卡片的探针瞬态（不进 draft、不落库）：加载态 + 拉取到的模型 + 最近一次结果 */
type ProbeState = {
  loading?: 'models' | 'test'
  models?: string[]
  listError?: string
  test?: ConnectionTestResult
}

type SectionMsg = { tone: 'error' | 'ok'; text: string } | null

function orderedKeys(profile: StyleProfile): string[] {
  const known = KEY_ORDER.filter((k) => k in profile)
  const rest = Object.keys(profile).filter((k) => !KEY_ORDER.includes(k))
  return [...known, ...rest]
}

/** 通用键值编辑器：字符串/数组 → textarea，其余 → 只读 JSON（用户 canon 不重写内容） */
function KeyField({
  name,
  value,
  onChange,
}: {
  name: string
  value: unknown
  onChange: (name: string, value: unknown) => void
}) {
  const label = KEY_LABELS[name] ?? name
  if (typeof value === 'string') {
    return (
      <label className={styles.field}>
        <span className={styles.fieldLabel}>{label}</span>
        <textarea rows={3} value={value} onChange={(e) => onChange(name, e.target.value)} />
      </label>
    )
  }
  if (Array.isArray(value)) {
    return (
      <label className={styles.field}>
        <span className={styles.fieldLabel}>{label}</span>
        <textarea
          rows={Math.min(6, Math.max(2, value.length))}
          value={value.join('\n')}
          onChange={(e) =>
            onChange(name, e.target.value.split('\n').map((s) => s.trim()).filter(Boolean))
          }
        />
      </label>
    )
  }
  return (
    <div className={styles.field}>
      <span className={styles.fieldLabel}>{label}</span>
      <code className={styles.readonly}>{JSON.stringify(value)}</code>
    </div>
  )
}

function ProfileEditor({
  draft,
  onChange,
  onSave,
  busy,
  saveLabel,
  emptyHint,
}: {
  draft: StyleProfile
  onChange: (name: string, value: unknown) => void
  onSave: () => void
  busy: boolean
  saveLabel: string
  emptyHint: string
}) {
  const keys = orderedKeys(draft)
  if (keys.length === 0) {
    return <div className="empty">{emptyHint}</div>
  }
  return (
    <div>
      {keys.map((k) => (
        <KeyField key={k} name={k} value={draft[k]} onChange={onChange} />
      ))}
      <div className={styles.saveRow}>
        <button type="button" className="btn btn-primary" disabled={busy} onClick={onSave}>
          {busy ? '保存中…' : saveLabel}
        </button>
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const { projectId = '' } = useParams()
  const { logout } = useAuth()

  const [projects, setProjects] = useState<Project[]>([])
  const [settings, setSettings] = useState<ProjectSettings | null>(null)
  const [presets, setPresets] = useState<SkillPreset[]>([])
  const [profileDraft, setProfileDraft] = useState<StyleProfile>({})
  const [routeSel, setRouteSel] = useState<Record<string, string>>({})
  const [connectionDrafts, setConnectionDrafts] = useState<ModelConnectionDraft[]>([])
  // 每连接探针瞬态（按 connection.id 索引）：拉取到的模型 + 测试结果，纯前端展示不落库
  const [probes, setProbes] = useState<Record<string, ProbeState>>({})
  // 模型连接区的就地反馈：页面顶部那条 banner 离保存按钮太远（点保存看不到任何反应，
  // 未保存的草稿一刷新就没了），这里把校验/保存结果渲染在按钮旁。
  const [connMsg, setConnMsg] = useState<SectionMsg>(null)
  // 每章目标字数（§6.9 三层字数控制；从 projects 取该书当前值，可改保存）
  const [targetWords, setTargetWords] = useState('3000')
  // 样本提取草稿（提取后编辑再确认；draftDraft 非空显示编辑区）
  const [sampleText, setSampleText] = useState('')
  const [draftDraft, setDraftDraft] = useState<StyleProfile | null>(null)
  const [extractError, setExtractError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  const load = useCallback(async () => {
    setBanner(null)
    try {
      const [s, pre, proj] = await Promise.all([
        api.getSettings(projectId),
        api.listSkillPresets(),
        api.listProjects(),
      ])
      setSettings(s)
      setProfileDraft(s.style_profile)
      setRouteSel(
        Object.fromEntries(MODEL_ROLES.map((r) => [r.key, s.model_routes[r.key] ?? ''])),
      )
      setConnectionDrafts((s.model_connections ?? []).map((connection) => ({ ...connection, api_key: '' })))
      setPresets(pre)
      setProjects(proj)
      const cur = proj.find((p) => p.id === projectId)
      // 该书已显式置空 → 回落默认 3000（与生成侧 or 3000 语义一致），不留上一本书残留值
      setTargetWords(cur?.target_words != null ? String(cur.target_words) : '3000')
    } catch (err) {
      setBanner(err instanceof ApiError ? err.code : '设置加载失败')
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  function showError(err: unknown) {
    setOk(null)
    if (err instanceof ApiError && err.code) setBanner(err.code)
    else setBanner('请求失败，请重试')
  }

  async function saveProfile() {
    setBusy('profile')
    setBanner(null)
    try {
      await api.putStyleProfile(projectId, profileDraft)
      await load()
      setOk('文风档案已保存')
    } catch (err) {
      showError(err)
    } finally {
      setBusy(null)
    }
  }

  async function extractSample() {
    const samples = sampleText
      .split(/\n\s*\n/)
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 2)
    if (samples.length === 0) {
      setBanner('请先粘贴至少一段作者样本')
      return
    }
    setBusy('extract')
    setBanner(null)
    setOk(null)
    try {
      const resp = await api.extractStyleSample(projectId, samples)
      const { extract_error, ...profile } = resp.draft
      setExtractError(extract_error ?? null)
      setDraftDraft(profile)
      setOk(extract_error ? '已提取统计草稿（LLM 提炼降级，可手动补充后确认）' : '已提取文风草稿，可编辑后确认落库')
    } catch (err) {
      showError(err)
    } finally {
      setBusy(null)
    }
  }

  async function confirmDraft() {
    if (!draftDraft) return
    setBusy('confirm')
    setBanner(null)
    try {
      await api.putStyleProfile(projectId, draftDraft)
      setDraftDraft(null)
      setExtractError(null)
      await load()
      setOk('文风草稿已确认落库')
    } catch (err) {
      showError(err)
    } finally {
      setBusy(null)
    }
  }

  async function applyPreset(p: SkillPreset) {
    setBusy(`preset:${p.id}`)
    setBanner(null)
    try {
      await api.putStyleProfile(projectId, p.style_profile, p.id)
      await load()
      setOk(`已应用预设《${p.name}》`)
    } catch (err) {
      showError(err)
    } finally {
      setBusy(null)
    }
  }

  async function saveTargetWords() {
    const words = Number(targetWords)
    if (!Number.isInteger(words) || words < 500 || words > 20000) {
      setBanner('目标字数需为 500–20000 的整数')
      return
    }
    setBusy('words')
    setBanner(null)
    setOk(null)
    try {
      await api.updateProject(projectId, { target_words: words })
      await load()
      setOk('目标字数已保存，对新生成章节生效')
    } catch (err) {
      showError(err)
    } finally {
      setBusy(null)
    }
  }

  async function saveRoutes() {
    const routes = Object.fromEntries(
      MODEL_ROLES.map((r) => [r.key, routeSel[r.key]]).filter(([, v]) => v),
    ) as Record<string, string>
    setBusy('routes')
    setBanner(null)
    setOk(null)
    setConnMsg(null)
    const connections: ModelConnectionInput[] = []
    for (const [index, draft] of connectionDrafts.entries()) {
      const name = draft.name.trim()
      const baseUrl = draft.base_url.trim().replace(/\/$/, '')
      const model = draft.model.trim()
      // 报缺哪个字段：原来三项合成一句，用户看不出究竟差什么，点保存像没反应
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
      await api.updateSettings(projectId, routes, connections)
      await load()
      setConnMsg({ tone: 'ok', text: `已保存 ${connections.length} 个模型连接与路由` })
    } catch (err) {
      setConnMsg({ tone: 'error', text: err instanceof ApiError ? err.code : '请求失败，请重试' })
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

  /** 探针请求体：明文 key 优先；已保存连接留空则传 connection_id 让后端复用密文密钥。 */
  function probeBody(draft: ModelConnectionDraft): ModelProbeRequest {
    const apiKey = draft.api_key.trim()
    return {
      protocol: draft.protocol,
      base_url: draft.base_url.trim().replace(/\/$/, ''),
      ...(draft.model.trim() ? { model: draft.model.trim() } : {}),
      ...(apiKey ? { api_key: apiKey } : draft.has_api_key ? { connection_id: draft.id } : {}),
    }
  }

  /** 探针前置校验（未保存的新连接必须已有明文 key；测试还需模型 id）。 */
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
      const res = await api.listModels(projectId, probeBody(draft))
      setProbes((p) => ({ ...p, [draft.id]: {
        loading: undefined, models: res.models, listError: res.ok ? undefined : (res.error ?? '拉取失败'),
      } }))
    } catch (err) {
      setProbes((p) => ({ ...p, [draft.id]: {
        loading: undefined, listError: err instanceof ApiError ? err.code : '拉取失败',
      } }))
    }
  }

  async function runTest(draft: ModelConnectionDraft) {
    if (!probeReady(draft, true)) return
    setConnMsg(null)
    setProbes((p) => ({ ...p, [draft.id]: { ...p[draft.id], loading: 'test' } }))
    try {
      const res = await api.testConnection(projectId, probeBody(draft))
      setProbes((p) => ({ ...p, [draft.id]: { ...p[draft.id], loading: undefined, test: res } }))
    } catch (err) {
      setProbes((p) => ({ ...p, [draft.id]: { loading: undefined, test: {
        ok: false, latency_ms: 0, reply: null, error: err instanceof ApiError ? err.code : '测试失败',
      } } }))
    }
  }

  return (
    <div className={styles.wrap}>
      <ProjectRail projects={projects} onLogout={logout} />
      <main className={styles.main}>
        <div className={styles.inner}>
          <header className={styles.header}>
            <div>
              <h1>创作设置</h1>
              <div className={styles.crumb}>
                <Link to={`/projects/${projectId}`}>返回工作台</Link>
                {settings && <span className="badge">v{settings.version}</span>}
              </div>
            </div>
            {settings?.skill_pack && (
              <span className="badge badge-accent">预设：{settings.skill_pack}</span>
            )}
          </header>

          {banner && <div className="banner banner-error">{banner}</div>}
          {ok && <div className="banner banner-warning">{ok}</div>}

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>文风档案</h2>
            <p className={styles.hint}>
              写作生成的硬约束（§7.12）：视角 / 句式 / 禁用表达 / 疲劳词与句式模式 / 对话腔调。
              直接编辑即改全书文风，保存后生效。
            </p>
            {settings ? (
              <ProfileEditor
                draft={profileDraft}
                onChange={(k, v) => setProfileDraft((d) => ({ ...d, [k]: v }))}
                onSave={saveProfile}
                busy={busy !== null}
                saveLabel="保存文风档案"
                emptyHint="该书尚无文风档案，可从下方提取或导入预设。"
              />
            ) : (
              <div className="empty">加载中…</div>
            )}
          </section>

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>样本提取</h2>
            <p className={styles.hint}>
              粘贴 1–2 篇你的样章（合计 ≤1.2 万字），系统做统计层分析 + LLM 提炼，生成文风草稿供确认。
            </p>
            <textarea
              className="textarea"
              rows={4}
              value={sampleText}
              onChange={(e) => setSampleText(e.target.value)}
              placeholder="粘贴样本段落（空行分隔，最多取前两段）"
            />
            <div className={styles.saveRow}>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busy !== null}
                onClick={extractSample}
              >
                {busy === 'extract' ? '提取中…' : '提取文风草稿'}
              </button>
            </div>
            {draftDraft && (
              <div className={styles.draftBox}>
                <h3 className={styles.draftTitle}>草稿（可编辑后确认）</h3>
                {extractError && <div className="banner banner-warning">LLM 提炼降级：{extractError}</div>}
                <ProfileEditor
                  draft={draftDraft}
                  onChange={(k, v) => setDraftDraft((d) => ({ ...(d ?? {}), [k]: v }))}
                  onSave={confirmDraft}
                  busy={busy !== null}
                  saveLabel="确认落库"
                  emptyHint=""
                />
              </div>
            )}
          </section>

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>题材预设</h2>
            <p className={styles.hint}>
              4 个题材预设即 4 本种子书的文风档案（§7.12），一键导入覆盖当前文风并记录预设标记。
            </p>
            <div className={styles.presetGrid}>
              {presets.map((p) => (
                <div key={p.id} className={styles.preset}>
                  <div className={styles.presetHead}>
                    <span className={styles.presetName}>{p.name}</span>
                    <span className="badge">{p.genre}</span>
                  </div>
                  <button
                    type="button"
                    className="btn btn-quiet"
                    disabled={busy !== null}
                    onClick={() => applyPreset(p)}
                  >
                    {busy === `preset:${p.id}` ? '应用中…' : '应用'}
                  </button>
                </div>
              ))}
            </div>
          </section>

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>生成设置</h2>
            <p className={styles.hint}>
              每章目标字数（§6.9 三层字数控制）：驱动单章生成长度，新生成章节按
              [0.8×目标, 1.3×目标] 校验，越界自动重写。默认 3000，范围 500–20000。
            </p>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>每章目标字数</span>
              <input
                className="input"
                type="number"
                min={500}
                max={20000}
                step={100}
                value={targetWords}
                onChange={(e) => setTargetWords(e.target.value)}
              />
            </label>
            <div className={styles.saveRow}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy !== null}
                onClick={() => void saveTargetWords()}
              >
                {busy === 'words' ? '保存中…' : '保存目标字数'}
              </button>
            </div>
          </section>

          <section className={`panel ${styles.section}`}>
            <div className={styles.connectionTitleRow}>
              <div>
                <h2 className={styles.sectionTitle}>模型连接与路由</h2>
                <p className={styles.hint}>
                  可添加 OpenAI 兼容接口或 Anthropic 原生接口。API Key 由后端加密保存，页面不会再次显示原文。
                </p>
              </div>
              <button type="button" className="btn btn-secondary" disabled={busy !== null} onClick={addConnection}>
                添加网络模型
              </button>
            </div>

            {connectionDrafts.length === 0 ? (
              <div className="empty">尚未添加网络模型；下方仍可使用内置 DeepSeek。</div>
            ) : (
              <div className={styles.connectionList}>
                {connectionDrafts.map((connection) => (
                  <article key={connection.id} className={styles.connectionCard}>
                    <div className={styles.connectionHead}>
                      <input className="input" aria-label="连接名称" value={connection.name}
                        onChange={(e) => updateConnection(connection.id, { name: e.target.value })}
                        placeholder="例如：我的 Claude" />
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
                          placeholder={connection.protocol === 'anthropic' ? 'claude-sonnet-4-5' : 'gpt-5'} />
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
              <p className={styles.hint}>未指定时使用默认降级链；自定义接口调用失败时也会自动回落到内置模型。</p>
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
                      ...BUILTIN_MODEL_OPTIONS,
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
                onClick={saveRoutes}
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
        </div>
      </main>
    </div>
  )
}
