// 项目库：左 rail + 项目卡（title/genre/current_chapter → 进入工作台）。
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { api, ApiError } from '../lib/api'
import type { Project } from '../types'
import styles from './ProjectsPage.module.css'

export default function ProjectsPage() {
  const { logout } = useAuth()
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    api
      .listProjects()
      .then((list) => alive && setProjects(list))
      .catch((err) => alive && setError(err instanceof ApiError ? err.code : '加载失败'))
    return () => {
      alive = false
    }
  }, [])

  return (
    <div className={styles.wrap}>
      <ProjectRail projects={projects ?? []} onLogout={logout} />
      <main className={styles.main}>
        <h1>作品库</h1>
        {error && <div className="banner banner-error">加载失败：{error}</div>}
        {projects === null ? (
          <div className="empty">加载中…</div>
        ) : projects.length === 0 ? (
          <div className="empty">还没有作品。先用 seed 创建一个演示项目，刷新后即出现在这里。</div>
        ) : (
          <div className={styles.grid}>
            {projects.map((p) => (
              <Link key={p.id} to={`/projects/${p.id}`} className={`panel ${styles.card}`}>
                <h2 className={styles.title}>{p.title}</h2>
                <div className={styles.meta}>
                  {p.genre} · 已写至第 {p.current_chapter} 章
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
