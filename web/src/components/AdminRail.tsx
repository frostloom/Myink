import {useState} from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import styles from './AdminRail.module.css'
const views = [
  ['overview', '运营概览'],
  ['analytics', '数据分析'],
  ['users', '用户'],
  ['projects', '作品'],
  ['tasks', '任务'],
  ['runs', '全部运行'],
  ['logs', '访问日志'],
  ['invites', '邀请码'],
  ['feedback', '反馈'],
] as const
const resources = [
  ['models', 'AI 模型'],
  ['model-routes', '模型分配'],
  ['writing-resources', '写作资源'],
  ['defaults', '用户默认设置'],
] as const
export function AdminRail({ onLogout }: { onLogout: () => Promise<void> }) {
  const [open,setOpen]=useState(false)
  const location = useLocation()
  const detailView=location.pathname.match(/^\/admin\/(tasks|runs|users|projects)\//)?.[1]
  const current = detailView ?? new URLSearchParams(location.search).get('tab') ?? 'overview'
  return (
    <aside className={styles.rail}>
      <div className={styles.railHead}><Link className={styles.brand} to="/admin">
        Myink <small>平台管理</small>
      </Link><button type="button" className={`btn btn-secondary ${styles.menuToggle}`} aria-expanded={open} aria-controls="admin-navigation" onClick={()=>setOpen(!open)}>管理导航</button></div>
      <div id="admin-navigation" className={`${styles.navigation} ${open?styles.open:''}`} onClick={event=>{if((event.target as HTMLElement).closest('a'))setOpen(false)}}>
      <nav aria-label="平台管理导航">
        <span className={styles.groupTitle}>运营管理</span>
        {views.map(([id, label]) => (
          <Link
            key={id}
            to={id === 'overview' ? '/admin' : `/admin?tab=${id}`}
            aria-current={
              (location.pathname === '/admin' || Boolean(detailView)) && current === id
                ? 'page'
                : undefined
            }
          >
            {label}
          </Link>
        ))}
      </nav>
      <nav aria-label="AI 资源管理">
        <span className={styles.groupTitle}>AI 资源管理</span>
        {resources.map(([path, label]) => (
          <NavLink key={path} to={`/admin/${path}`}>
            {label}
          </NavLink>
        ))}
      </nav>
      <nav aria-label="管理账号">
        <Link to="/account">账号与安全</Link>
        <button className="btn btn-quiet" onClick={() => void onLogout()}>
          退出登录
        </button>
      </nav>
      </div>
    </aside>
  )
}
