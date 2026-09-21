// 路由：/login 公开；其余挂 RequireAuth（无会话 → 只读的 GuestShell，不再跳登录）。
import { createBrowserRouter, Navigate, Outlet, Link } from 'react-router-dom'
import { GuestShell } from './components/GuestShell'
import { useAuth } from './context/AuthContext'
import { useGuest } from './hooks/useGuest'
import AuditPage from './pages/AuditPage'
import AccountPage from './pages/AccountPage'
import AdminPage from './pages/AdminPage'
import AppearancePage from './pages/AppearancePage'
import EnvironmentPage from './pages/EnvironmentPage'
import LoginPage from './pages/LoginPage'
import LorePage from './pages/LorePage'
import NewProjectPage from './pages/NewProjectPage'
import ProjectsPage from './pages/ProjectsPage'
import SettingsPage from './pages/SettingsPage'
import WorkspacePage from './pages/WorkspacePage'

function RequireAuth() {
  const { session, status, validationError, revalidate, logout } = useAuth()
  if (status === 'checking') return <div className="empty">正在验证登录状态…</div>
  if (status === 'unavailable') {
    return (
      <div className="empty">
        <p>{validationError}</p>
        <button type="button" className="btn btn-primary" onClick={revalidate}>重试</button>{' '}
        <button type="button" className="btn btn-quiet" onClick={() => void logout()}>退出登录</button>
      </div>
    )
  }
  // 游客没有会话，也就没有可打开的作品：先挡住，页内那批挂载期请求一处都不会发。
  if (!session) return <GuestShell />
  // token 或账号改变即卸载整个受保护子树，旧 fetch 状态与 SSE 随组件清理一并丢弃。
  return <Outlet key={`${session.userId}:${session.token}`} />
}

function RequireProject() {
  const guest = useGuest()
  if (guest) {
    return (
      // data-guest-exempt：这是给游客的几个逃生口之一，不能再被 GuestShell 的拦截器吞掉。
      <div className="empty" data-guest-exempt>
        <p>未登录，无法打开作品。</p>
        <Link to="/login" className="btn btn-primary">登录</Link>
      </div>
    )
  }
  return <Outlet />
}

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      { path: '/', element: <Navigate to="/projects" replace /> },
      { path: '/projects', element: <ProjectsPage /> },
      { path: '/account', element: <AccountPage /> },
      { path: '/admin', element: <AdminPage /> },
      { path: '/environment', element: <EnvironmentPage /> },
      { path: '/theme', element: <AppearancePage /> },
      { path: '/appearance', element: <Navigate to="/theme" replace /> },
      { path: '/projects/new', element: <NewProjectPage /> },
      {
        element: <RequireProject />,
        children: [
          { path: '/projects/:projectId', element: <WorkspacePage /> },
          { path: '/projects/:projectId/settings', element: <SettingsPage /> },
          { path: '/projects/:projectId/audit', element: <AuditPage /> },
          { path: '/projects/:projectId/lore', element: <LorePage /> },
        ],
      },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])
