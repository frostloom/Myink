// 左 rail：项目切换（active 高亮）+ 当前用户 + 登出。
import { NavLink, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import type { Project } from '../types'
import styles from './ProjectRail.module.css'

interface Props {
  projects: Project[]
  onLogout: () => void
}

export function ProjectRail({ projects, onLogout }: Props) {
  const { session } = useAuth()
  const { projectId } = useParams()
  return (
    <aside className={styles.rail}>
      <NavLink to="/projects" className={styles.brand}>
        Ai Ink
      </NavLink>
      <nav className={styles.nav} aria-label="作品列表">
        {projects.map((p) => (
          <NavLink
            key={p.id}
            to={`/projects/${p.id}`}
            className={({ isActive }) => (isActive ? `${styles.item} ${styles.active}` : styles.item)}
          >
            <span className={styles.title}>{p.title}</span>
          </NavLink>
        ))}
      </nav>
      <div className={styles.pageLinks}>
        {!projectId && (
          <NavLink
            to="/environment"
            className={({ isActive }) =>
              isActive ? `${styles.item} ${styles.active}` : styles.item
            }
          >
            <span className={styles.title}>环境配置</span>
          </NavLink>
        )}
        {projectId && (
          <>
            <NavLink
              to={`/projects/${projectId}/lore`}
              className={({ isActive }) =>
                isActive ? `${styles.item} ${styles.active}` : styles.item
              }
            >
              <span className={styles.title}>设定</span>
            </NavLink>
            <NavLink
              to={`/projects/${projectId}/settings`}
              className={({ isActive }) =>
                isActive ? `${styles.item} ${styles.active}` : styles.item
              }
            >
              <span className={styles.title}>创作设置</span>
            </NavLink>
            <NavLink
              to={`/projects/${projectId}/audit`}
              className={({ isActive }) =>
                isActive ? `${styles.item} ${styles.active}` : styles.item
              }
            >
              <span className={styles.title}>全局审计</span>
            </NavLink>
          </>
        )}
      </div>
      <div className={styles.foot}>
        <span className={styles.user}>{session?.username}</span>
        <button type="button" className="btn btn-quiet" onClick={onLogout}>
          登出
        </button>
      </div>
    </aside>
  )
}
