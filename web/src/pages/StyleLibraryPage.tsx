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
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import { styleLibraryApi, type StyleLibraryItem } from '../lib/styleLibraryApi'
import type { Project } from '../types'
import shell from './SettingsPage.module.css'
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
                  ? e.target.value.split('\n').filter((line) => line.trim() !== '')
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
          <summary>统计指纹（句长 / 段落 / 高频词——样本的确定性测量，不作为文笔）</summary>
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
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // rail 的书目：与别的页面同一个来源，拿不到就当空列表（rail 的分区链接照样在）。
  useEffect(() => {
    if (guest) { setProjects([]); return }
    api.listProjects().then(setProjects).catch(() => setProjects([]))
  }, [guest])

  const reload = useCallback(async () => {
    try {
      setItems((await styleLibraryApi.list(token)).items)
    } catch (reason) {
      setError(formatApiError(reason, '读不到文风库，请稍后重试'))
    }
  }, [token])

  useEffect(() => { void reload() }, [reload])

  const run = async (action: () => Promise<void>, fallback: string) => {
    setError(null)
    setBusy(true)
    try {
      await action()
    } catch (reason) {
      setError(formatApiError(reason, fallback))
    } finally {
      setBusy(false)
    }
  }

  const selected = items.find((item) => item.id === selectedId) ?? null
  const builtins = items.filter((item) => item.builtin)
  const mine = items.filter((item) => !item.builtin)

  // 同一时刻只开一个面板：新建与查看互斥，页面上不会同时出现两个「文风名」。
  const openItem = (item: StyleLibraryItem) => {
    setNewOpen(false)
    setSelectedId(item.id)
    setName(item.name)
    setNote(item.note)
  }

  const openNew = () => {
    setSelectedId(null)
    setNewOpen(true)
    setNewName('')
    setSampleText('')
    setDraft(null)
  }

  const extract = () => void run(async () => {
    setDraft((await styleLibraryApi.extract(token, [sampleText])).draft)
  }, '提取失败，请重试')

  const saveNew = () => void run(async () => {
    // extract_error 只是页面上的降级提示，不是档案的一部分，不落库。
    const { extract_error: _omit, ...profile } = draft ?? {}
    const saved = await styleLibraryApi.save(token, { name: newName.trim(), profile })
    // 追加而不是重拉：列表已经按「内置在前」排好，插到末尾不会打乱。
    setItems((prev) => [...prev, saved])
    openItem(saved)
  }, '保存失败，请重试')

  const rename = () => void run(async () => {
    if (selected === null) return
    const next = await styleLibraryApi.patch(token, selected.id, { name: name.trim(), note })
    setItems((prev) => prev.map((item) => (item.id === next.id ? next : item)))
    setName(next.name)
    setNote(next.note)
  }, '改名失败，请重试')

  const remove = (item: StyleLibraryItem) => void run(async () => {
    if (!window.confirm(`删除文风「${item.name}」？`)) return
    await styleLibraryApi.remove(token, item.id)
    setItems((prev) => prev.filter((row) => row.id !== item.id))
    if (selectedId === item.id) setSelectedId(null)
  }, '删除失败，请重试')

  const row = (item: StyleLibraryItem) => (
    <li key={item.id}>
      <button type="button" aria-pressed={item.id === selectedId}
              className={item.id === selectedId ? `${styles.item} ${styles.itemOn}` : styles.item}
              onClick={() => openItem(item)}>
        {item.name}
      </button>
    </li>
  )

  return (
    <div className={shell.wrap}>
      <ProjectRail projects={projects} onLogout={logout} />
      <main className={shell.main}>
        <div className={shell.inner}>
          <header className={shell.header}>
            <div>
              <h1>文风库</h1>
              <div className={shell.crumb}>
                <Link to="/long">返回长篇</Link>
              </div>
            </div>
          </header>

          {error && <div className="banner banner-error">{error}</div>}

          <div className={styles.layout}>
            <div>
              <ul className={styles.list} aria-label="文风">
                {builtins.length > 0 && <li className={styles.groupTitle}>内置</li>}
                {builtins.map(row)}
                {mine.length > 0 && <li className={styles.groupTitle}>我的</li>}
                {mine.map(row)}
              </ul>
              <button type="button" className="btn btn-secondary" onClick={openNew}>新建文风</button>
            </div>

            {newOpen ? (
              <div className={styles.newBox}>
                <label>
                  <span>粘贴文章</span>
                  <textarea className="input" rows={6} aria-label="粘贴文章" value={sampleText}
                            placeholder="贴一段你想照着写的小说正文，越像你想写的那本就越好"
                            onChange={(e) => setSampleText(e.target.value)} />
                </label>
                <div className={styles.actions}>
                  <button type="button" className="btn btn-secondary" aria-label="提取文风"
                          disabled={busy || sampleText.trim() === ''} onClick={extract}>
                    提取文风
                  </button>
                </div>

                {typeof draft?.extract_error === 'string' && (
                  <div className="banner banner-warning" role="alert">{draft.extract_error}</div>
                )}

                {draft !== null && (
                  <ProfileFields profile={draft} readOnly={false}
                                 onChange={(key, next) => setDraft((prev) => ({ ...(prev ?? {}), [key]: next }))} />
                )}

                <label>
                  <span>文风名</span>
                  <input className="input" aria-label="文风名" value={newName} placeholder="给这套文风起个名字"
                         onChange={(e) => setNewName(e.target.value)} />
                </label>
                <div className={styles.actions}>
                  <button type="button" className="btn btn-primary" aria-label="保存文风"
                          disabled={busy} onClick={saveNew}>
                    保存文风
                  </button>
                  <button type="button" className="btn btn-quiet" onClick={() => setNewOpen(false)}>取消</button>
                </div>
              </div>
            ) : selected === null ? (
              <p className={shell.hint}>从左边选一套文风看看，或者新建一套自己的。</p>
            ) : (
              <div className={styles.detail}>
                <h2 className={shell.sectionTitle}>{selected.name}</h2>
                {selected.builtin ? (
                  <p className={shell.hint}>内置文风不能改。想要一版自己的，照着新建一套。</p>
                ) : (
                  <>
                    <label>
                      <span>文风名</span>
                      <input className="input" aria-label="文风名" value={name}
                             onChange={(e) => setName(e.target.value)} />
                    </label>
                    <label>
                      <span>备注</span>
                      <input className="input" aria-label="备注" value={note}
                             placeholder="这套文风是照着哪本、哪一篇提的"
                             onChange={(e) => setNote(e.target.value)} />
                    </label>
                    <div className={styles.actions}>
                      <button type="button" className="btn btn-primary" aria-label="重命名"
                              disabled={busy} onClick={rename}>
                        重命名
                      </button>
                      <button type="button" className="btn btn-quiet" aria-label="删除文风"
                              disabled={busy} onClick={() => remove(selected)}>
                        删除文风
                      </button>
                    </div>
                  </>
                )}
                <ProfileFields profile={selected.profile} readOnly onChange={() => undefined} />
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
