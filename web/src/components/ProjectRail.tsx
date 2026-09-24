// 左 rail：长篇/短篇两个分区 + 该书目的作品列表；进书后是设定/创作设置/全局审计；全局页才露出环境配置和主题。
// data-guest-exempt：未登录时整条 rail 仍是可用导航（GuestShell 的拦截器放行此子树）。
import { NavLink, useLocation, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { isProjectDraft } from '../lib/projectCreation'
import type { Project } from '../types'
import styles from './ProjectRail.module.css'

interface Props {
  projects: Project[]
  onLogout: () => void | Promise<void>
}

export function ProjectRail({ projects, onLogout }: Props) {
  const { session, status } = useAuth()
  const guest = useGuest()
  const { projectId } = useParams()
  const { pathname } = useLocation()
  // 当前在哪个分区：分区页看路径，书内页看这本书的形态，其余页面（账号/主题/管理）不分区、列全部。
  const inBook = projectId ? projects.find((p) => p.id === projectId) : undefined
  const section = pathname.startsWith('/short') ? 'short'
    : pathname.startsWith('/long') ? 'long'
      : inBook ? inBook.form ?? 'long' : null
  const books = projects.filter((p) => !isProjectDraft(p)
    && (section === null || (p.form ?? 'long') === section))
  return (
    <aside className={styles.rail} data-guest-exempt>
      <NavLink to="/long" className={styles.brand}>
        Myink
      </NavLink>
      <nav className={styles.sections} aria-label="作品分区">
        <NavLink
          to="/long"
          className={({ isActive }) => (isActive ? `${styles.item} ${styles.active}` : styles.item)}
        >
          <span className={styles.title}>长篇</span>
        </NavLink>
        <NavLink
          to="/short"
          className={({ isActive }) => (isActive ? `${styles.item} ${styles.active}` : styles.item)}
        >
          <span className={styles.title}>短篇</span>
        </NavLink>
      </nav>
      <nav className={styles.nav} aria-label="作品列表">
        {books.map((p) => (
          <NavLink
            key={p.id}
            to={`/projects/${p.id}`}
            className={({ isActive }) => (isActive ? `${styles.item} ${styles.active}` : styles.item)}
          >
            <span className={styles.title}>{p.title}</span>
          </NavLink>
        ))}
      </nav>
      {projectId && (
        <div className={styles.pageLinks}>
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
        </div>
      )}
      {!projectId && (
        <nav className={styles.settings} aria-label="全局设置">
          <NavLink
            to="/environment"
            className={({ isActive }) => (isActive ? `${styles.item} ${styles.active}` : styles.item)}
          >
            <span className={styles.title}>环境配置</span>
          </NavLink>
          <NavLink
            to="/theme"
            className={({ isActive }) => (isActive ? `${styles.item} ${styles.active}` : styles.item)}
          >
            <span className={styles.title}>主题</span>
          </NavLink>
        </nav>
      )}
      <div className={styles.foot}>
        {status === 'authenticated' && session?.role === 'admin' && session.roleVerified === true && (
          <NavLink
            to="/admin"
            className={({ isActive }) => (isActive ? `${styles.item} ${styles.active}` : styles.item)}
          >
            <span className={styles.title}>管理后台</span>
          </NavLink>
        )}
        <NavLink
          to="/account"
          className={({ isActive }) => (isActive ? `${styles.item} ${styles.active}` : styles.item)}
        >
          <span className={styles.title}>账号</span>
        </NavLink>
        <div className={styles.userRow}>
          <span className={styles.user}>{guest ? '未登录' : session?.username}</span>
          {guest
            ? <NavLink to="/login" className="btn btn-quiet">登录</NavLink>
            : <button type="button" className="btn btn-quiet" onClick={() => void onLogout()}>登出</button>}
        </div>
      </div>
    </aside>
  )
}
