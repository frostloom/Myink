// 创作设置页：本书题材字段 + 每章目标字数。
// 原题材/文风保留建书历史；启用写作资源后，以当前资源快照为准。
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import { isManagedPack, type BookGenrePack } from '../lib/genrePacks'
import type { Project, ProjectSettings } from '../types'
import styles from './SettingsPage.module.css'
import { WritingResourcePicker } from '../components/WritingResourcePicker'

export default function SettingsPage() {
  const { projectId = '' } = useParams()
  const { logout } = useAuth()

  const [projects, setProjects] = useState<Project[]>([])
  const [settings, setSettings] = useState<ProjectSettings | null>(null)
  const [genrePack, setGenrePack] = useState<BookGenrePack | null>(null)
  // 每章目标字数（§6.9 三层字数控制；从 projects 取该书当前值，可改保存）
  const [targetWords, setTargetWords] = useState('3000')
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
      if (isManagedPack(s.genre_pack)) {
        setGenrePack(s.genre_pack)
      } else {
        setGenrePack(null)
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

          <WritingResourcePicker key={projectId} projectId={projectId} />

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>本书题材</h2>
            <p className={styles.hint}>以下为建书历史题材；启用写作资源后，当前题材与主辅顺序以「本书写作资源」中已保存的快照为准。</p>
            {genrePack ? (
              <>
                <p className={styles.hint}>
                  根题材：{genrePack.source_name}
                  {genrePack.secondary_name ? ` · 辅题材：${genrePack.secondary_name}` : ''}
                </p>
                <p>{genrePack.selling_point}</p>
                <p className={styles.hint}>此处保留建书时的历史快照，不随资源选择更新。</p>
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
              <Link className="btn btn-quiet" to="/environment">高级设置</Link>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}
