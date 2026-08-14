// 创作设置页（阶段 4）：文风档案（查看/编辑/保存 + 样本提取确认 + 预设导入）+ 每 Agent 模型路由。
// 布局：rail（复用）+ 主区卡片纵向堆叠，保持与工作台一致的简洁风格。
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { api, ApiError } from '../lib/api'
import type { Project, ProjectSettings, SkillPreset, StyleProfile } from '../types'
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
const MODEL_OPTIONS = [
  { value: '', label: '默认' },
  { value: 'deepseek-v4-flash', label: 'deepseek-v4-flash' },
  { value: 'deepseek-v4-pro', label: 'deepseek-v4-pro' },
]

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
      setPresets(pre)
      setProjects(proj)
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

  async function saveRoutes() {
    const routes = Object.fromEntries(
      MODEL_ROLES.map((r) => [r.key, routeSel[r.key]]).filter(([, v]) => v),
    ) as Record<string, string>
    setBusy('routes')
    setBanner(null)
    try {
      await api.updateSettings(projectId, routes)
      await load()
      setOk('模型路由已保存')
    } catch (err) {
      showError(err)
    } finally {
      setBusy(null)
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
            <h2 className={styles.sectionTitle}>每 Agent 模型路由</h2>
            <p className={styles.hint}>
              为各角色指定主模型（§6.10），未指定的角色回落默认降级链；写作 / 抽取等角色独立调优。
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
                    {MODEL_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
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
                {busy === 'routes' ? '保存中…' : '保存模型路由'}
              </button>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}
