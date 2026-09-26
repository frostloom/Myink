/** 账号级文风库：内置几套只读，我的档可新建/改名/改备注/删除。
 *
 * 档案形状沿用 StyleProfile（与 project_settings.style_profile 同构），库里取出来直接写进书，
 * 不需要转换。已有项只允许改名与改备注——PATCH 不收 profile，改档案只走新建流，免得为改
 * 档案里一个键再开一个端点。所以档案编辑器只在「新建」里可编辑，看已有项时是只读的。
 *
 * 展示口径：主区只放**写作文笔**（叙事声音 / 对话 / 场景 / 衔接 / 节奏 / 用词 / 情绪 / 习惯
 * 八维 + 视角与禁忌），统计层的数字（句长分布 / 段落结构 / 高频词串）收进折叠的「统计指纹」。
 * 以前不分主次，把档案的原始键名连统计一起摊成一张表单，看着像配置文件而不是文风。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import { styleLibraryApi, type StyleLibraryItem } from '../lib/styleLibraryApi'
import type { Project } from '../types'
import styles from './StyleLibraryPage.module.css'

/** 文笔八维：与后端 prompts._STYLE_PROSE_DIMS 同一份口径（键 → 中文名，顺序即展示顺序）。
 *  那边负责给模型看，这边给人看，键名改动要两边一起改。 */
const PROSE_DIMS: Array<[string, string]> = [
  ['narrative_voice', '叙事声音与语气'],
  ['dialogue_style', '对话风格'],
  ['scene_description', '场景描写特征'],
  ['transitions', '转折与衔接手法'],
  ['pacing', '节奏特征'],
  ['diction', '词汇偏好'],
  ['emotional_expression', '情绪表达方式'],
  ['distinctive_habits', '独特习惯'],
]

/** 主区的键与中文名，顺序即展示顺序：文笔八维在前，短约束在后，清单收尾。 */
const MAIN_ORDER: Array<[string, string]> = [
  ['pov', '视角'],
  ...PROSE_DIMS,
  ['sentence_style', '句式风格'],
  ['lexicon_tendency', '词汇修辞倾向'],
  ['dialogue', '对话腔调'],
  ['forbidden', '禁用表达（每行一条）'],
  ['reference_excerpts', '样本摘录（每行一条）'],
]

/** 统计层的键（确定性测量）：认得出的给中文名，认不出的原样显示键名——不能因为不认识就丢。 */
const STAT_LABELS: Record<string, string> = {
  sentence_len_dist: '句长分布',
  dialogue_ratio: '对话占比',
  para_stats: '段落结构',
  frequent_words: '高频词串',
  source: '来源',
}

/** 只认这两种形状：字符串与字符串数组。数字 / 嵌套对象是统计层的中间结果，手改没有意义。 */
function editable(value: unknown): value is string | string[] {
  return typeof value === 'string'
    || (Array.isArray(value) && value.every((entry) => typeof entry === 'string'))
}

/** 统计值一行化：数组用顿号连，别的原样 JSON——嵌套对象也得看得见。 */
function describe(value: unknown): string {
  if (Array.isArray(value)) return value.join('、')
  return typeof value === 'string' ? value : JSON.stringify(value)
}

function MainField({ label, value, readOnly, onChange }: {
  label: string
  value: string | string[]
  readOnly: boolean
  onChange: (next: unknown) => void
}) {
  const lines = Array.isArray(value)
  // 看已有项是读，不是填表：串成一段话/一串条目，别把八维摊成八个只读输入框。
  if (readOnly) {
    return (
      <div className={styles.field}>
        <span className={styles.fieldLabel}>{label}</span>
        {lines
          ? <ul className={styles.fieldList}>{value.map((entry) => <li key={entry}>{entry}</li>)}</ul>
          : <p className={styles.fieldText}>{value}</p>}
      </div>
    )
  }
  return (
    <label>
      <span>{label}</span>
      <textarea className="input" rows={lines ? 3 : 2} aria-label={label}
                value={lines ? value.join('\n') : value}
                onChange={(e) => onChange(lines
                  ? e.target.value.split('\n')
                  : e.target.value)} />
    </label>
  )
}

/** 档案正文：主区放文笔，统计指纹折起来。新建与查看共用，两边看到的东西才是同一份。 */
function ProfileFields({ profile, readOnly, onChange }: {
  profile: Record<string, unknown>
  readOnly: boolean
  onChange: (key: string, next: unknown) => void
}) {
  const main = MAIN_ORDER.filter(([key]) => editable(profile[key]))
  const shown = new Set(main.map(([key]) => key))
  // extract_error 是页面上单独的降级提示，不是档案的一部分。
  const stats = Object.keys(profile).filter((key) => !shown.has(key) && key !== 'extract_error')

  return (
    <>
      {main.length > 0 && <h3 className={styles.blockTitle}>文笔</h3>}
      {main.map(([key, label]) => (
        <MainField key={key} label={label} value={profile[key] as string | string[]}
                   readOnly={readOnly} onChange={(next) => onChange(key, next)} />
      ))}
      {stats.length > 0 && (
        <details className={styles.stats}>
          <summary>统计指纹 · 句长、段落与高频词</summary>
          <div className={styles.statList}>
            {stats.map((key) => (
              <div className={styles.stat} key={key}>
                <span>{STAT_LABELS[key] ?? key}</span>
                <code>{describe(profile[key])}</code>
              </div>
            ))}
          </div>
        </details>
      )}
    </>
  )
}

function hasContent(value: unknown): boolean {
  if (typeof value === 'string') return value.trim().length > 0
  if (typeof value === 'number') return Number.isFinite(value)
  if (Array.isArray(value)) return value.some(hasContent)
  if (value !== null && typeof value === 'object') return Object.values(value).some(hasContent)
  return false
}

function profileSummary(profile: Record<string, unknown>): string {
  return ['narrative_voice', 'pacing', 'pov'].map((key) => profile[key])
    .filter((value): value is string => typeof value === 'string' && value.trim() !== '')
    .slice(0, 2).join(' · ')
}

export default function StyleLibraryPage() {
  const { session, logout } = useAuth()
  const guest = useGuest()
  const token = session?.token ?? ''
  const [projects, setProjects] = useState<Project[]>([])
  const [items, setItems] = useState<StyleLibraryItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [note, setNote] = useState('')
  const [newOpen, setNewOpen] = useState(false)
  const [sampleText, setSampleText] = useState('')
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState<'extract' | 'save' | 'rename' | 'delete' | null>(null)
  const inFlight = useRef(false)
  const [loading, setLoading] = useState(true)
  const [extractedSample, setExtractedSample] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  // rail 的书目：与别的页面同一个来源，拿不到就当空列表（rail 的分区链接照样在）。
  useEffect(() => {
    if (guest) { setProjects([]); return }
    api.listProjects().then(setProjects).catch(() => setProjects([]))
  }, [guest])

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setItems((await styleLibraryApi.list(token)).items)
    } catch (reason) {
      setError(formatApiError(reason, '读不到文风库，请稍后重试'))
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { void reload() }, [reload])

  const run = async (operation: NonNullable<typeof busy>, action: () => Promise<void>, fallback: string) => {
    if (inFlight.current) return
    inFlight.current = true
    setError(null)
    setMessage(null)
    setBusy(operation)
    try {
      await action()
    } catch (reason) {
      setError(formatApiError(reason, fallback))
    } finally {
      setBusy(null)
      inFlight.current = false
    }
  }

  const selected = items.find((item) => item.id === selectedId) ?? null
  const builtins = items.filter((item) => item.builtin)
  const mine = items.filter((item) => !item.builtin)
  const hasDraft = sampleText !== '' || draft !== null || newName !== ''
  const usableDraft = draft !== null && Object.entries(draft)
    .some(([key, value]) => key !== 'extract_error' && key !== 'source' && hasContent(value))
  const sampleChanged = draft !== null && sampleText !== extractedSample
  const canSave = usableDraft && newName.trim() !== '' && !sampleChanged
  const busyMessage = busy === 'extract' ? '正在提取文风…'
    : busy === 'save' ? '正在保存文风…'
    : busy === 'rename' ? '正在保存修改…'
    : busy === 'delete' ? '正在删除文风…' : null

  // 同一时刻只开一个面板：新建与查看互斥，页面上不会同时出现两个「文风名」。
  const openItem = (item: StyleLibraryItem) => {
    setNewOpen(false)
    setSelectedId(item.id)
    setName(item.name)
    setNote(item.note)
    setError(null)
    setMessage(null)
  }

  const openNew = () => {
    setSelectedId(null)
    setNewOpen(true)
    setError(null)
    setMessage(null)
  }

  const extract = () => sampleText.trim() !== '' && void run('extract', async () => {
    setDraft((await styleLibraryApi.extract(token, [sampleText])).draft)
    setExtractedSample(sampleText)
  }, '提取失败，请重试')

  const saveNew = () => canSave && void run('save', async () => {
    // extract_error 只是页面上的降级提示，不是档案的一部分，不落库。
    const { extract_error: _omit, ...profile } = draft ?? {}
    // 编辑中保留空行，避免 Enter 被受控输入吞掉；仅在保存时整理已知清单。
    for (const key of ['forbidden', 'reference_excerpts']) {
      const value = profile[key]
      if (Array.isArray(value) && value.every((entry) => typeof entry === 'string')) {
        profile[key] = value.map((entry) => entry.trim()).filter((entry) => entry !== '')
      }
    }
    const saved = await styleLibraryApi.save(token, {
      name: newName.trim(), profile, sample_chars: Array.from(extractedSample).length,
    })
    // 追加而不是重拉：列表已经按「内置在前」排好，插到末尾不会打乱。
    setItems((prev) => [...prev, saved])
    openItem(saved)
    setNewName('')
    setSampleText('')
    setExtractedSample('')
    setDraft(null)
    setMessage('文风已保存，可在创作时选用。')
  }, '保存失败，请重试')

  const rename = () => name.trim() !== '' && void run('rename', async () => {
    if (selected === null) return
    const next = await styleLibraryApi.patch(token, selected.id, { name: name.trim(), note })
    setItems((prev) => prev.map((item) => (item.id === next.id ? next : item)))
    setName(next.name)
    setNote(next.note)
    setMessage('名称与备注已保存。')
  }, '保存修改失败，请重试')

  const remove = (item: StyleLibraryItem) => void run('delete', async () => {
    if (!window.confirm(`删除文风「${item.name}」？`)) return
    await styleLibraryApi.remove(token, item.id)
    setItems((prev) => prev.filter((row) => row.id !== item.id))
    if (selectedId === item.id) setSelectedId(null)
    setMessage('文风已删除。')
  }, '删除失败，请重试')

  const row = (item: StyleLibraryItem) => (
    <li key={item.id}>
      <button type="button" aria-label={item.name} aria-pressed={item.id === selectedId} disabled={busy !== null}
              className={item.id === selectedId ? `${styles.item} ${styles.itemOn}` : styles.item}
              onClick={() => openItem(item)}>
        <span className={styles.itemName}>{item.name}</span>
        <span className={styles.itemSummary}>{item.note || `文风 · ${profileSummary(item.profile) || '查看文笔与写作约束'}`}</span>
      </button>
    </li>
  )

  return (
    <div className={styles.wrap}>
      <div className={styles.rail}><ProjectRail projects={projects} onLogout={logout} /></div>
      <main className={styles.main}>
        <div className={styles.inner}>
          <header className={styles.header}>
            <div>
              <div className={styles.eyebrow}>写作资源</div>
              <h1>文风库</h1>
              <p className={styles.hint}>收藏写作风格，用于长篇与短篇创作。</p>
            </div>
            <Link className={styles.back} to="/long">返回长篇</Link>
          </header>

          <div className={styles.layout}>
            <aside className={styles.catalog} aria-label="文风目录">
              <div className={styles.catalogHead}>
                <h2>全部文风 <span>{items.length}</span></h2>
                <button type="button" className="btn btn-secondary" disabled={busy !== null} onClick={openNew}>
                  {hasDraft ? '继续新建文风' : '新建文风'}
                </button>
              </div>
              {loading && <p className={styles.hint} role="status">正在加载文风库…</p>}
              <ul className={styles.list} aria-label="文风">
                {builtins.length > 0 && <li className={styles.groupTitle}>内置文风 <span>{builtins.length}</span></li>}
                {builtins.map(row)}
                <li className={styles.groupTitle}>我的文风 <span>{mine.length}</span></li>
                {mine.map(row)}
              </ul>
              {!loading && mine.length === 0 && <p className={styles.hint}>尚未保存个人文风</p>}
            </aside>

            {newOpen ? (
              <section className={styles.newBox} aria-label="新建文风">
                <div className={styles.detailHead}>
                  <div className={styles.eyebrow}>个人文风</div>
                  <h2>{draft === null ? '从文章中提取文风' : '预览与调整'}</h2>
                  <ol className={styles.steps} aria-label="新建步骤">
                    <li aria-current={draft === null ? 'step' : undefined}>01 文章样本</li>
                    <li aria-current={draft !== null ? 'step' : undefined}>02 文风预览</li>
                    <li>03 保存选用</li>
                  </ol>
                </div>
                <details className={styles.sample} open={draft === null}>
                  <summary>{draft === null ? '文章样本' : `查看或更换样本 · ${Array.from(sampleText).length} 字`}</summary>
                  <label>
                    <span>粘贴文章</span>
                    <textarea className="input" rows={9} aria-label="粘贴文章" value={sampleText} disabled={busy !== null}
                              placeholder="粘贴具有代表性的小说正文，保留叙述、对话与场景描写。"
                              onChange={(e) => setSampleText(e.target.value)} />
                  </label>
                  {draft !== null && <div className={styles.actions}>
                    <button type="button" className="btn btn-secondary" aria-label="提取文风"
                            disabled={busy !== null || sampleText.trim() === ''} onClick={extract}>
                      {busy === 'extract' ? '提取中…' : '重新提取文风'}
                    </button>
                    <span className={styles.hint}>重新提取会替换当前文风预览。</span>
                  </div>}
                </details>
                {typeof draft?.extract_error === 'string' && (
                  <div className="banner banner-warning" role="alert">{draft.extract_error}</div>
                )}
                {draft !== null && (
                  <fieldset className={styles.editorFields} disabled={busy !== null}>
                    <label className={styles.nameField}>
                      <span>文风名</span>
                      <input className="input" aria-label="文风名" value={newName} maxLength={64} placeholder="例如：渡口白描"
                             onChange={(e) => setNewName(e.target.value)} />
                    </label>
                    <p className={styles.hint}>调整提取结果后保存。已保存文风仅支持修改名称与备注。</p>
                    <ProfileFields profile={draft} readOnly={false}
                                   onChange={(key, next) => setDraft((prev) => ({ ...(prev ?? {}), [key]: next }))} />
                  </fieldset>
                )}
              </section>
            ) : selected === null ? (
              <section className={styles.empty}>
                <span className={styles.eyebrow}>文笔 · 节奏 · 表达</span>
                <h2>选择文风，查看写作特征</h2>
                <p className={styles.hint}>选择文风查看叙事特点与样本摘录，或导入文章，提取自己的写作风格。</p>
              </section>
            ) : (
              <section className={styles.detail} aria-label="文风详情">
                <div className={styles.detailHead}>
                  <div className={styles.eyebrow}>{selected.builtin ? '内置文风 · 只读' : '我的文风'}</div>
                  <h2>{selected.name}</h2>
                  {profileSummary(selected.profile) && <p className={styles.summary}>文风概要：{profileSummary(selected.profile)}</p>}
                  {Array.isArray(selected.profile.reference_excerpts) && typeof selected.profile.reference_excerpts[0] === 'string' && (
                    <blockquote className={styles.excerpt}>{selected.profile.reference_excerpts[0]}</blockquote>
                  )}
                </div>
                {!selected.builtin && (
                  <fieldset className={styles.metadata} disabled={busy !== null}>
                    <label>
                      <span>文风名</span>
                      <input className="input" aria-label="文风名" value={name} maxLength={64}
                             onChange={(e) => setName(e.target.value)} />
                    </label>
                    <label>
                      <span>备注</span>
                      <input className="input" aria-label="备注" value={note} maxLength={200}
                             placeholder="记录样本来源或适用题材"
                             onChange={(e) => setNote(e.target.value)} />
                    </label>
                  </fieldset>
                )}
                <ProfileFields profile={selected.profile} readOnly onChange={() => undefined} />
              </section>
            )}
          </div>
        </div>
        <div className={styles.actionBar}>
          <div className={styles.feedback}>
            {error ? <p className={styles.error} role="alert">{error}</p>
              : <p role="status">{busyMessage || message || (newOpen
                ? draft === null ? '先提取文章中的文笔与表达特征。'
                  : sampleChanged ? '样本已更改，请重新提取后保存。'
                    : !usableDraft ? '未提取到有效文风，请调整样本后重试。'
                      : !newName.trim() ? '填写文风名后即可保存。' : '保存后可在长篇与短篇创作中选用。'
                : selected?.builtin ? '内置文风可直接用于创作。'
                  : selected ? '文风内容只读，可修改名称与备注。' : '选择文风，或从文章中提取。')}</p>}
          </div>
          <div className={styles.actions}>
            {newOpen ? <>
              <button type="button" className="btn btn-quiet" disabled={busy !== null} onClick={() => setNewOpen(false)}>暂存并关闭</button>
              {draft === null
                ? <button type="button" className="btn btn-primary" aria-label="提取文风"
                          disabled={busy !== null || sampleText.trim() === ''} onClick={extract}>{busy === 'extract' ? '提取中…' : '提取文风'}</button>
                : <button type="button" className="btn btn-primary" aria-label="保存文风"
                          disabled={busy !== null || !canSave} onClick={saveNew}>{busy === 'save' ? '保存中…' : '保存文风'}</button>}
            </> : selected && !selected.builtin ? <>
              {selected.removable && <button type="button" className="btn btn-quiet" aria-label="删除文风"
                      disabled={busy !== null} onClick={() => remove(selected)}>删除文风</button>}
              <button type="button" className="btn btn-primary" aria-label="重命名"
                      disabled={busy !== null || !name.trim() || (name === selected.name && note === selected.note)} onClick={rename}>
                {busy === 'rename' ? '保存中…' : '保存修改'}
              </button>
            </> : error && <button type="button" className="btn btn-secondary" disabled={loading} onClick={() => void reload()}>重新加载</button>}
          </div>
        </div>
      </main>
    </div>
  )
}
