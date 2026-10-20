import { Link, NavLink } from 'react-router-dom'
import styles from './AdminRail.module.css'

export function AdminRail({ onLogout }: { onLogout: () => Promise<void> }) {
  return (
    <aside className={styles.rail}>
      <Link className={styles.brand} to="/admin">Myink <small>平台管理</small></Link>
      <nav aria-label="平台管理导航">
        <NavLink to="/admin" end>运营概览</NavLink>
        <NavLink to="/admin/configuration">模型与平台配置</NavLink>
      </nav>
      <nav aria-label="管理账号">
        <Link to="/account">账号与安全</Link>
        <button className="btn btn-quiet" onClick={() => void onLogout()}>退出登录</button>
      </nav>
    </aside>
  )
}
