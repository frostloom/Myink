/** 账号级文风库：内置几套只读，我的档可新建/改名/改备注/删除。
 *
 * 档案形状沿用 StyleProfile（与 project_settings.style_profile 同构），库里取出来直接写进书，
 * 不需要转换。已有项只允许改名与改备注——PATCH 不收 profile，改档案只走新建流，免得为改
 * 档案里一个键再开一个端点。所以档案编辑器只在「新建」里可编辑，看已有项时是只读的。
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

/** 档案里每个键按值的形状给一种控件；认不出的形状（嵌套对象、混合数组）只读展示——
 *  那是统计层的中间结果，手改没有意义，但也不能因为不认识就把这个键丢了。 */
function ProfileField({ label, value, readOnly, onChange }: {
  label: string
  value: unknown
  readOnly: boolean
  onChange: (next: unknown) => void
}) {
  if (Array.isArray(value) && value.every((entry) => typeof entry === 'string')) {
    return (
      <label>
        <span>{label}</span>
        <textarea className="input" rows={3} aria-label={label} readOnly={readOnly}
                  value={value.join('\n')}
                  onChange={(e) => onChange(e.target.value.split('\n').filter((line) => line.trim() !== ''))} />
      </label>
    )
  }
  if (typeof value === 'number') {
    return (
      <label>
        <span>{label}</span>
        <input className="input" type="number" aria-label={label} readOnly={readOnly} value={value}
               onChange={(e) => onChange(e.target.value === '' ? 0 : Number(e.target.value))} />
      </label>
    )
  }
  if (typeof value === 'string') {
    return (
      <label>
        <span>{label}</span>
        <textarea className="input" rows={2} aria-label={label} readOnly={readOnly} value={value}
                  onChange={(e) => onChange(e.target.value)} />
      </label>
    )
  }
  return (
    <div className={styles.readonly}>
      <span>{label}</span>
      <code>{JSON.stringify(value)}</code>
    </div>
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

                {draft !== null && Object.entries(draft)
                  .filter(([key]) => key !== 'extract_error')
                  .map(([key, value]) => (
                    <ProfileField key={key} label={key} value={value} readOnly={false}
                                  onChange={(next) => setDraft((prev) => ({ ...(prev ?? {}), [key]: next }))} />
                  ))}

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
                {Object.entries(selected.profile).map(([key, value]) => (
                  <ProfileField key={key} label={key} value={value} readOnly
                                onChange={() => undefined} />
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
