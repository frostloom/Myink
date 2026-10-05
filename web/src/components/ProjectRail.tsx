// 左 rail：长篇/短篇两个分区 + 该书目的作品列表；进书后是设定/创作设置/全局审计；全局页才露出环境配置、主题和文风库。
// data-guest-exempt：未登录时整条 rail 仍是可用导航（GuestShell 的拦截器放行此子树）。
import { Link, NavLink, useLocation, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { isProjectDraft } from '../lib/projectCreation'
import type { Project } from '../types'
import { FEEDBACK_OPEN_EVENT } from './FeedbackWidget'
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
  // 短篇没有设定页/全局审计/分形态的创作设置——这三个入口只对长篇成立。
  // 判据取「确定是短篇才藏」：书还没加载进 projects 时 inBook 是 undefined，那时照样显示。
  const isShortBook = inBook?.form === 'short'
  return (
    <aside className={styles.rail} data-guest-exempt>
      <NavLink to="/long" className={styles.brand}>
        Myink
      </NavLink>
      {/* 模式与内容是两件事（§3.7d）。原来 长篇/短篇 与书名用同一套 .item，进书之后
          既看不出自己在哪种模式（两条都不亮，因为 NavLink 只按路径判 active），又容易把
          模式误读成某一页。现在模式是顶部分段控件：当前模式用中性描边，绿色留给「你正在
          读的这一项」——任一时刻最多一处绿。
          这里用 Link 而不是 NavLink：NavLink 会把 aria-current 收敛成「自己那条路径命中才给」
          （源码里 `isActive ? ariaCurrentProp : void 0`），而进书后恰恰是路径不命中、模式却
          正在生效的那个情形——那时读屏最需要知道当前分区。 */}
      <nav className={styles.sections} aria-label="作品分区">
        <Link
          to="/long"
          aria-current={section === 'long' ? 'true' : undefined}
          className={section === 'long' ? `${styles.sectionItem} ${styles.sectionCurrent}` : styles.sectionItem}
        >
          <span className={styles.title}>长篇</span>
        </Link>
        <Link
          to="/short"
          aria-current={section === 'short' ? 'true' : undefined}
          className={section === 'short' ? `${styles.sectionItem} ${styles.sectionCurrent}` : styles.sectionItem}
        >
          <span className={styles.title}>短篇</span>
        </Link>
      </nav>
      <nav className={styles.nav} aria-label="作品列表">
        {books.length > 0 && <span className={styles.groupHead} aria-hidden="true">作品</span>}
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
      {projectId && !isShortBook && (
        <nav className={styles.pageLinks} aria-label="本书页面">
          <span className={styles.groupHead} aria-hidden="true">本书</span>
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
        </nav>
      )}
      {!projectId && (
        <nav className={styles.settings} aria-label="全局设置">
          <span className={styles.groupHead} aria-hidden="true">全局</span>
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
          <NavLink
            to="/styles"
            className={({ isActive }) => (isActive ? `${styles.item} ${styles.active}` : styles.item)}
          >
            <span className={styles.title}>文风库</span>
          </NavLink>
        </nav>
      )}
      {/* 反馈入口的分工（2026-10-05 定）：桌面上入口就是那只灯本身——悬停或键盘聚焦会浮出
          「反馈」字样；导航里这一行只在灯被整只藏掉的窄屏出现（.feedbackPin 基准 display:none，
          640 档放回来并钉在横条右缘）。手机端不留灯泡是既定口径，但藏灯不能顺带藏掉反馈。
          它是 <button> 不是链接：不持有表单状态，只派发事件，面板由 <Outlet> 之外那个唯一挂件实例接住。
          放在 .foot 之外、foot 之前：窄屏里整条 rail 是横向滚动条，只有 rail 的直接子元素才钉得住
          （sticky 的容器是它自己那一格，藏在 foot 里就跟着 foot 一起滚出视口，实测 390 下 x=633）。
          游客不出现——提交反馈的接口要 require_user，给条走不通的路不如不给。 */}
      {status === 'authenticated' && (
        <button
          type="button"
          className={`${styles.item} ${styles.feedbackPin}`}
          onClick={() => window.dispatchEvent(new Event(FEEDBACK_OPEN_EVENT))}
        >
          <span className={styles.title}>反馈</span>
        </button>
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
