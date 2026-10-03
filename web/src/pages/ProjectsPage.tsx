// 长篇 / 短篇各是一张书单：左 rail + 「新建长篇/短篇」+ 分隔线行（title/genre/current_chapter → 进入工作台）。
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { api, ApiError } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import { isProjectDraft, projectHref } from '../lib/projectCreation'
import type { Project } from '../types'
import styles from './ProjectsPage.module.css'

const FORM_LABEL = { long: '长篇', short: '短篇' } as const

export default function ProjectsPage({ form = 'long' }: { form?: 'long' | 'short' }) {
  const { logout } = useAuth()
  const guest = useGuest()
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // 删除/重载共用：删除成功后刷新列表
  const loadProjects = useCallback(() => {
    setError(null)
    if (guest) {
      setProjects([])
      return
    }
    api
      .listProjects()
      .then((list) => setProjects(list))
      .catch((err) => setError(formatApiError(err, '加载失败')))
  }, [guest])

  useEffect(() => {
    void loadProjects()
  }, [loadProjects])

  // 整本书删除（阶段 6 硬删）：按钮与整行链接是兄弟节点（不是嵌套的可交互元素），
  // 所以不需要再截断冒泡。
  // 有进行中任务 → Python 409（本书需先暂停/取消），前端给中文横幅。
  const handleDelete = useCallback(
    (p: Project) => {
      if (!window.confirm(`删除《${p.title}》？全书正文、记忆、向量与任务记录将一并移除，不可撤销。`)) return
      api
        .deleteProject(p.id)
        .then(() => {
          setDeleteError(null)
          void loadProjects()
        })
        .catch((err) => {
          if (err instanceof ApiError && err.status === 409) {
            setDeleteError(`《${p.title}》有进行中任务，无法删除。请先暂停/取消后再试。`)
          } else {
            setDeleteError(formatApiError(err, '删除失败'))
          }
        })
    },
    [loadProjects],
  )

  const mine = (projects ?? []).filter((p) => (p.form ?? 'long') === form)
  const label = FORM_LABEL[form]

  return (
    <div className={styles.wrap}>
      <ProjectRail projects={projects ?? []} onLogout={logout} />
      <main className={styles.main}>
        <div className={styles.head}>
          <h1>{label}</h1>
          <Link to={`/${form}/new`} className="btn btn-primary">
            新建{label}
          </Link>
        </div>
        {error && <div className="banner banner-error">加载失败：{error}</div>}
        {deleteError && <div className="banner banner-error">{deleteError}</div>}
        {projects === null ? (
          <div className="empty">加载中…</div>
        ) : mine.length === 0 ? (
          <div className="empty">还没有{label}作品。点击右上角「新建{label}」，一句话梗概即可创建第一本。</div>
        ) : (
          <>
          <h2 className={styles.sectionTitle}>正式作品</h2>
          {mine.every(isProjectDraft) && <p className="empty">尚无已完成建书的作品，请先完成下方草稿。</p>}
          <ul className={styles.list}>
            {mine.filter((p) => !isProjectDraft(p)).map((p) => (
              <li key={p.id} className={styles.row}>
                <Link to={projectHref(p)} className={styles.rowLink}>
                  <span className={styles.title}>{p.title}</span>
                  <span className={styles.meta}>
                    {p.genre} · 已写至第 {p.current_chapter} 章
                  </span>
                  <span className={styles.arrow} aria-hidden="true">
                    →
                  </span>
                </Link>
                <button
                  type="button"
                  className={styles.del}
                  onClick={() => handleDelete(p)}
                  aria-label={`删除《${p.title}》`}
                  title="删除本书"
                >
                  删除
                </button>
              </li>
            ))}
          </ul>
          {mine.some(isProjectDraft) && (
            <section aria-label="待完成作品">
              <h2 className={styles.sectionTitle}>待完成作品</h2>
              <ul className={styles.list}>
                {mine.filter(isProjectDraft).map((p) => (
                  <li key={p.id} className={styles.row}>
                    <Link to={projectHref(p)} className={styles.rowLink}>
                      <span className={styles.title}>{p.title}</span>
                      <span className={styles.meta}>
                        {p.creation_status === 'setup_confirmed' ? '设定已确认 · 待确认大纲' : '待完成设定与大纲'}
                      </span>
                      <span className={styles.arrow} aria-hidden="true">
                        →
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
          </>
        )}
      </main>
    </div>
  )
}
