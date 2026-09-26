// 创作设置页：文风档案（导入/提取）+ 本书题材字段 + 每章目标字数。
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import { GenrePackFields } from '../components/GenrePackFields'
import { emptyFields, isManagedPack, type BookGenrePack, type GenreFields } from '../lib/genrePacks'
import type { Project, ProjectSettings, StyleProfile } from '../types'
import styles from './SettingsPage.module.css'

// 文风档案键展示（§7.12 种子书档案键 + 样本提取的文笔八维；数组键按行编辑，其余透传）。
// 八维那份与 StyleLibraryPage 的 PROSE_DIMS 同一口径，改键名要一起改。
const KEY_LABELS: Record<string, string> = {
  pov: '视角',
  narrative_voice: '叙事声音与语气',
  dialogue_style: '对话风格',
  scene_description: '场景描写特征',
  transitions: '转折与衔接手法',
  pacing: '节奏特征',
  diction: '词汇偏好',
  emotional_expression: '情绪表达方式',
  distinctive_habits: '独特习惯',
  sentence_style: '句式风格',
  lexicon_tendency: '词汇修辞倾向',
  dialogue: '对话腔调',
  forbidden: '禁用表达（每行一条）',
  reference_excerpts: '样本摘录（每行一条）',
}
const KEY_ORDER = [
  'pov', 'narrative_voice', 'dialogue_style', 'scene_description', 'transitions',
  'pacing', 'diction', 'emotional_expression', 'distinctive_habits',
  'sentence_style', 'lexicon_tendency', 'dialogue', 'forbidden', 'reference_excerpts',
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
        <textarea
          className="textarea"
          rows={3}
          value={value}
          onChange={(e) => onChange(name, e.target.value)}
        />
      </label>
    )
  }
  if (Array.isArray(value)) {
    return (
      <label className={styles.field}>
        <span className={styles.fieldLabel}>{label}</span>
        <textarea
          className="textarea"
          rows={Math.min(8, Math.max(3, value.length + 1))}
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
  const [profileDraft, setProfileDraft] = useState<StyleProfile>({})
  const [genreDraft, setGenreDraft] = useState<GenreFields>(emptyFields())
  const [genrePack, setGenrePack] = useState<BookGenrePack | null>(null)
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
      const [s, proj] = await Promise.all([
        api.getSettings(projectId),
        api.listProjects(),
      ])
      setSettings(s)
      setProfileDraft(s.style_profile)
      if (isManagedPack(s.genre_pack)) {
        setGenrePack(s.genre_pack)
        setGenreDraft({
          selling_point: s.genre_pack.selling_point,
          subgenres: s.genre_pack.subgenres,
          taboos: s.genre_pack.taboos,
          pacing: s.genre_pack.pacing,
          satisfaction: s.genre_pack.satisfaction,
          mechanics: s.genre_pack.mechanics,
          world_hints: s.genre_pack.world_hints,
        })
      } else {
        setGenrePack(null)
        setGenreDraft(emptyFields())
      }
      setProjects(proj)
      const cur = proj.find((p) => p.id === projectId)
      // 该书已显式置空 → 回落默认 3000（与生成侧 or 3000 语义一致），不留上一本书残留值
      setTargetWords(cur?.target_words != null ? String(cur.target_words) : '3000')
    } catch (err) {
      setBanner(formatApiError(err, '设置加载失败'))
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  function showError(err: unknown) {
    setOk(null)
    setBanner(formatApiError(err))
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

  async function saveGenrePack() {
    if (!genrePack) return
    setBusy('genre')
    setBanner(null)
    setOk(null)
    try {
      const next = await api.putGenrePack(projectId, genreDraft)
      setGenrePack(next)
      await load()
      setOk('本书题材已保存，之后写章/修订会用新字段')
    } catch (err) {
      showError(err)
    } finally {
      setBusy(null)
    }
  }

  async function restoreGenrePack() {
    if (!genrePack) return
    setBusy('genre-restore')
    setBanner(null)
    setOk(null)
    try {
      const next = await api.restoreGenrePack(projectId)
      setGenrePack(next)
      await load()
      setOk('已恢复建书时的题材字段')
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
            {genrePack && (
              <span className="badge badge-accent">
                {genrePack.secondary_name
                  ? `${genrePack.source_name}+${genrePack.secondary_name}`
                  : genrePack.source_name}
              </span>
            )}
          </header>

          {banner && <div className="banner banner-error">{banner}</div>}
          {ok && <div className="banner banner-warning">{ok}</div>}

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>文风档案</h2>
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
            <textarea
              className="textarea"
              rows={4}
              value={sampleText}
              onChange={(e) => setSampleText(e.target.value)}
              placeholder="粘贴样本段落（空行分隔，最多取前两段，合计不超过 1.2 万字）"
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
            <h2 className={styles.sectionTitle}>本书题材</h2>
            {genrePack ? (
              <>
                <p className={styles.hint}>
                  根题材：{genrePack.source_name}
                  {genrePack.secondary_name ? ` · 辅题材：${genrePack.secondary_name}` : ''}
                </p>
                <GenrePackFields value={genreDraft} onChange={setGenreDraft} />
                <div className={styles.saveRow}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    disabled={busy !== null}
                    onClick={() => void restoreGenrePack()}
                  >
                    {busy === 'genre-restore' ? '恢复中…' : '恢复建书时的题材字段'}
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busy !== null}
                    onClick={() => void saveGenrePack()}
                  >
                    {busy === 'genre' ? '保存中…' : '保存本书题材'}
                  </button>
                </div>
              </>
            ) : (
              <p className={styles.hint}>本书创建时未选题材包，不回填。新书请在建书页选择。</p>
            )}
          </section>

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>生成设置</h2>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>每章目标字数（500–20000）</span>
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
              <Link className="btn btn-quiet" to="/environment">模型连接与扫榜</Link>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}
