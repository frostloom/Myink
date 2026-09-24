import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Outlet, useNavigate, useOutletContext, useSearchParams } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { formatApiError } from '../lib/apiError'
import {
  adminApi,
  type AdminAccessLog,
  type AdminInvitation,
  type AdminInvitationCreated,
  type AdminOverview,
  type AdminPage as PageResult,
  type AdminProject,
  type AdminRun,
  type AdminTask,
  type AdminUser,
} from '../lib/adminApi'
import {
  creationStatusLabel,
  taskChapterLabel,
  taskStatusLabel,
  taskTypeLabel,
} from '../lib/labels'
import { Analytics } from './admin/Analytics'
import { RunTable } from './admin/RunDetail'
import {
  type AdminOutletContext,
  formatCost,
  formatDate,
  LoadState,
  Metrics,
  PAGE_SIZE,
  Pagination,
  RefreshButton,
  useResource,
} from './admin/shared'
import styles from './AdminPage.module.css'

type Tab = 'overview' | 'analytics' | 'users' | 'projects' | 'tasks' | 'runs' | 'logs' | 'invites'

const TABS: Array<[Tab, string]> = [
  ['overview', '概览'], ['analytics', '分析'], ['users', '用户'], ['projects', '作品'], ['tasks', '任务'],
  ['runs', '全部运行'], ['logs', '访问日志'], ['invites', '邀请码'],
]

function OverviewView({ token, onForbidden }: { token: string; onForbidden: () => void }) {
  const load = useCallback((signal: AbortSignal) => adminApi.getOverview(token, signal), [token])
  const resource = useResource<AdminOverview>(load, onForbidden)
  const value = resource.data
  return (
    <section className={styles.view} aria-labelledby="overview-heading">
      <div className={styles.viewHead}>
        <div><h2 id="overview-heading">全局概览</h2></div>
        <RefreshButton onClick={resource.retry} />
      </div>
      <LoadState {...resource} empty={!value}>
        {value && (
          <>
            <dl className={styles.counts}>
              <div><dt>用户</dt><dd>{value.user_count}</dd></div>
              <div><dt>作品</dt><dd>{value.project_count}</dd></div>
              <div><dt>章节</dt><dd>{value.chapter_count}</dd></div>
              <div><dt>任务</dt><dd>{value.task_count}</dd></div>
            </dl>
            <div className={`panel ${styles.panel}`}><h3>运行指标</h3><Metrics value={value.metrics} /></div>
            <div className={`panel ${styles.panel}`}>
              <h3>任务状态</h3>
              {Object.keys(value.task_status_counts).length === 0
                ? <div className="empty">暂无状态统计</div>
                : <dl className={styles.statusCounts}>{Object.entries(value.task_status_counts).map(([name, count]) => (
                  <div key={name}><dt>{taskStatusLabel(name)}</dt><dd>{count}</dd></div>
                ))}</dl>}
            </div>
          </>
        )}
      </LoadState>
    </section>
  )
}

function UsersView({ token, onForbidden }: { token: string; onForbidden: () => void }) {
  const [draftQ, setDraftQ] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const navigate = useNavigate()
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listUsers(token, { q, limit: PAGE_SIZE, offset }, signal),
    [offset, q, token],
  )
  const resource = useResource<PageResult<AdminUser>>(load, onForbidden)
  const submit = (event: FormEvent) => { event.preventDefault(); setOffset(0); setQ(draftQ.trim()) }
  return (
    <section className={styles.view} aria-labelledby="users-heading">
      <div className={styles.viewHead}><div><h2 id="users-heading">用户</h2></div><RefreshButton onClick={resource.retry} /></div>
      <form className={styles.filters} role="search" aria-label="用户筛选" onSubmit={submit}>
        <label><span>用户名或 ID</span><input className="input" value={draftQ} maxLength={128} onChange={(e) => setDraftQ(e.target.value)} /></label>
        <button className="btn btn-primary" type="submit">筛选</button>
      </form>
      <LoadState {...resource} empty={resource.data?.items.length === 0}>
        {resource.data && <>
          <div className={styles.tableWrap}><table><thead><tr>
            <th>用户</th><th>等级</th><th>作品</th><th>章节</th><th>字数</th><th>运行</th><th>总花费</th><th>操作</th>
          </tr></thead>
            <tbody>{resource.data.items.map((user) => <tr key={user.id}>
              <td><strong>{user.username}</strong></td>
              <td>{user.tier}</td>
              <td>{user.project_count}</td>
              <td>{user.chapter_count}</td>
              <td>{user.word_count.toLocaleString()}</td>
              <td>{user.metrics.run_count}</td>
              <td>{formatCost(user.metrics.cost_est)}</td>
              <td><button type="button" className="btn btn-quiet" aria-label={`查看用户 ${user.username}`} onClick={() => navigate(`/admin/users/${user.id}`)}>查看</button></td>
            </tr>)}</tbody></table></div>
          <Pagination total={resource.data.total} offset={offset} onChange={setOffset} />
        </>}
      </LoadState>
    </section>
  )
}

function ProjectsView({ token, onForbidden }: {
  token: string
  onForbidden: () => void
}) {
  const [draftQ, setDraftQ] = useState('')
  const [draftUser, setDraftUser] = useState('')
  const [filters, setFilters] = useState({ q: '', userId: '' })
  const [offset, setOffset] = useState(0)
  const navigate = useNavigate()
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listProjects(token, { ...filters, limit: PAGE_SIZE, offset }, signal),
    [filters, offset, token],
  )
  const resource = useResource<PageResult<AdminProject>>(load, onForbidden)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setOffset(0)
    setFilters({ q: draftQ.trim(), userId: draftUser.trim() })
  }
  return (
    <section className={styles.view} aria-labelledby="projects-heading">
      <div className={styles.viewHead}><div><h2 id="projects-heading">作品</h2></div><RefreshButton onClick={resource.retry} /></div>
      <form className={styles.filters} role="search" aria-label="作品筛选" onSubmit={submit}>
        <label><span>作品搜索</span><input className="input" value={draftQ} maxLength={128} onChange={(event) => setDraftQ(event.target.value)} /></label>
        <label><span>用户 ID</span><input className="input" value={draftUser} onChange={(event) => setDraftUser(event.target.value)} /></label>
        <button className="btn btn-primary" type="submit">筛选</button>
      </form>
      <LoadState {...resource} empty={resource.data?.items.length === 0}>
        {resource.data && <>
          <div className={styles.tableWrap}><table><thead><tr>
            <th>作品</th><th>作者</th><th>状态</th><th>章节</th><th>字数</th><th>任务</th><th>运行</th><th>预估成本</th><th>操作</th>
          </tr></thead>
            <tbody>{resource.data.items.map((project) => <tr key={project.id}>
              <td><strong>{project.title}</strong></td>
              <td>{project.username}</td>
              <td>{creationStatusLabel(project.creation_status)}</td>
              <td>{project.chapter_count}</td>
              <td>{project.word_count.toLocaleString()}</td>
              <td>{project.task_count}</td>
              <td>{project.metrics.run_count}</td>
              <td>{formatCost(project.metrics.cost_est)}</td>
              <td><button type="button" className="btn btn-quiet" aria-label={`查看《${project.title}》`} onClick={() => navigate(`/admin/projects/${project.id}`)}>查看</button></td>
            </tr>)}</tbody></table></div>
          <Pagination total={resource.data.total} offset={offset} onChange={setOffset} />
        </>}
      </LoadState>
    </section>
  )
}

function TasksView({ token, onForbidden }: {
  token: string
  onForbidden: () => void
}) {
  const [draft, setDraft] = useState({ userId: '', projectId: '', status: '' })
  const [filters, setFilters] = useState(draft)
  const [offset, setOffset] = useState(0)
  const navigate = useNavigate()
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listTasks(token, { ...filters, limit: PAGE_SIZE, offset }, signal),
    [filters, offset, token],
  )
  const resource = useResource<PageResult<AdminTask>>(load, onForbidden)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setOffset(0)
    setFilters({
      userId: draft.userId.trim(), projectId: draft.projectId.trim(), status: draft.status.trim(),
    })
  }
  return (
    <section className={styles.view} aria-labelledby="tasks-heading">
      <div className={styles.viewHead}><div><h2 id="tasks-heading">任务</h2></div><RefreshButton onClick={resource.retry} /></div>
      <form className={styles.filters} aria-label="任务筛选" onSubmit={submit}>
        <label><span>用户 ID</span><input className="input" value={draft.userId} onChange={(event) => setDraft({ ...draft, userId: event.target.value })} /></label>
        <label><span>作品 ID</span><input className="input" value={draft.projectId} onChange={(event) => setDraft({ ...draft, projectId: event.target.value })} /></label>
        <label><span>状态</span><input className="input" maxLength={32} value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })} /></label>
        <button className="btn btn-primary" type="submit">筛选</button>
      </form>
      <LoadState {...resource} empty={resource.data?.items.length === 0}>
        {resource.data && <>
          <div className={styles.tableWrap}><table><thead><tr>
            <th>作品</th><th>用户</th><th>类型</th><th>状态</th><th>目标章节</th><th>重试</th><th>运行</th><th>token 合计</th><th>创建时间</th><th>操作</th>
          </tr></thead>
            <tbody>{resource.data.items.map((task) => <tr key={task.id}>
              <td><strong>{task.project_title}</strong></td>
              <td>{task.username}</td>
              <td>{taskTypeLabel(task.task_type)}</td>
              <td>{taskStatusLabel(task.status)}</td>
              <td>{taskChapterLabel(task)}</td>
              <td>{task.retry_count}</td>
              <td>{task.metrics.run_count}</td>
              <td>{(task.metrics.input_tokens + task.metrics.output_tokens).toLocaleString()}</td>
              <td>{formatDate(task.created_at)}</td>
              <td><button type="button" className="btn btn-quiet" aria-label={`查看任务 ${task.id}`} onClick={() => navigate(`/admin/tasks/${task.id}`)}>查看</button></td>
            </tr>)}</tbody></table></div>
          <Pagination total={resource.data.total} offset={offset} onChange={setOffset} />
        </>}
      </LoadState>
    </section>
  )
}

function RunsView({ token, onForbidden }: { token: string; onForbidden: () => void }) {
  const [draft, setDraft] = useState({ userId: '', projectId: '', node: '' })
  const [filters, setFilters] = useState(draft)
  const [offset, setOffset] = useState(0)
  const navigate = useNavigate()
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listRuns(token, { ...filters, limit: PAGE_SIZE, offset }, signal),
    [filters, offset, token],
  )
  const resource = useResource<PageResult<AdminRun>>(load, onForbidden)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setOffset(0)
    setFilters({
      userId: draft.userId.trim(), projectId: draft.projectId.trim(), node: draft.node.trim(),
    })
  }
  return (
    <section className={styles.view} aria-labelledby="runs-heading">
      <div className={styles.viewHead}><div><h2 id="runs-heading">全部运行</h2></div><RefreshButton onClick={resource.retry} /></div>
      <form className={styles.filters} aria-label="运行筛选" onSubmit={submit}>
        <label><span>用户 ID</span><input className="input" value={draft.userId} onChange={(event) => setDraft({ ...draft, userId: event.target.value })} /></label>
        <label><span>作品 ID</span><input className="input" value={draft.projectId} onChange={(event) => setDraft({ ...draft, projectId: event.target.value })} /></label>
        <label><span>节点</span><input className="input" maxLength={64} value={draft.node} onChange={(event) => setDraft({ ...draft, node: event.target.value })} /></label>
        <button className="btn btn-primary" type="submit">筛选</button>
      </form>
      <LoadState {...resource} empty={resource.data?.items.length === 0}>
        {resource.data && <><RunTable runs={resource.data.items} onSelect={(run) => navigate(`/admin/runs/${run.id}`)} /><Pagination total={resource.data.total} offset={offset} onChange={setOffset} /></>}
      </LoadState>
    </section>
  )
}

function LogsView({ token, onForbidden }: { token: string; onForbidden: () => void }) {
  const [offset, setOffset] = useState(0)
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listAccessLogs(token, { limit: PAGE_SIZE, offset }, signal),
    [offset, token],
  )
  const resource = useResource<PageResult<AdminAccessLog>>(load, onForbidden)
  return (
    <section className={styles.view} aria-labelledby="logs-heading">
      <div className={styles.viewHead}><div><h2 id="logs-heading">访问日志</h2></div><RefreshButton onClick={resource.retry} /></div>
      <LoadState {...resource} empty={resource.data?.items.length === 0}>
        {resource.data && <>
          <div className={styles.tableWrap}><table><thead><tr><th>时间</th><th>管理员</th><th>动作</th><th>目标</th></tr></thead>
            <tbody>{resource.data.items.map((entry) => <tr key={entry.id}><td>{formatDate(entry.created_at)}</td><td>{entry.actor_id}</td><td>{entry.action}</td><td>{entry.target}</td></tr>)}</tbody></table></div>
          <Pagination total={resource.data.total} offset={offset} onChange={setOffset} />
        </>}
      </LoadState>
    </section>
  )
}

function InviteBadge({ invite }: { invite: AdminInvitation }) {
  if (invite.revoked_at) return <span className="badge badge-error">已撤销</span>
  if (new Date(invite.expires_at).getTime() <= Date.now()) return <span className="badge badge-warning">已过期</span>
  if (invite.redemption_count >= invite.max_redemptions) return <span className="badge">已用完</span>
  return <span className="badge badge-success">可用</span>
}

function InvitesView({ token, onForbidden }: { token: string; onForbidden: () => void }) {
  const [offset, setOffset] = useState(0)
  const [expiresDays, setExpiresDays] = useState('7')
  const [maxRedemptions, setMaxRedemptions] = useState('1')
  const [label, setLabel] = useState('')
  const [code, setCode] = useState('')
  const [minted, setMinted] = useState<AdminInvitationCreated | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listInvitations(token, { limit: PAGE_SIZE, offset }, signal),
    [offset, token],
  )
  const resource = useResource<PageResult<AdminInvitation>>(load, onForbidden)

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

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void run(async () => {
      const created = await adminApi.createInvitation(token, {
        expiresDays: Number(expiresDays),
        maxRedemptions: Number(maxRedemptions),
        label,
        code,
      })
      setMinted(created)
      setCopied(false)
      setLabel('')
      setCode('')
      setOffset(0)
      resource.retry()
    }, '创建失败，请稍后重试')
  }

  const revoke = (invitationId: string) => void run(async () => {
    await adminApi.revokeInvitation(token, invitationId)
    resource.retry()
  }, '撤销失败，请稍后重试')

  const copy = () => {
    if (!minted) return
    navigator.clipboard.writeText(minted.code)
      .then(() => setCopied(true))
      .catch(() => setError('复制失败，请手动选中上方文本'))
  }

  return (
    <section className={styles.view} aria-labelledby="invites-heading">
      <div className={styles.viewHead}>
        <div><h2 id="invites-heading">邀请码</h2></div>
        <RefreshButton onClick={resource.retry} />
      </div>
      <form className={styles.filters} aria-label="生成邀请码" onSubmit={submit}>
        <label><span>有效天数</span><input className="input" type="number" min={1} max={365} required
          value={expiresDays} onChange={(event) => setExpiresDays(event.target.value)} /></label>
        <label><span>可用次数</span><input className="input" type="number" min={1} max={1000} required
          value={maxRedemptions} onChange={(event) => setMaxRedemptions(event.target.value)} /></label>
        <label><span>备注</span><input className="input" maxLength={64}
          value={label} onChange={(event) => setLabel(event.target.value)} /></label>
        <label><span>自定义码（留空随机生成）</span><input className="input" minLength={4} maxLength={64}
          value={code} onChange={(event) => setCode(event.target.value)} /></label>
        <button className="btn btn-primary" type="submit" disabled={busy}>生成邀请码</button>
      </form>
      {minted && (
        <div className={`panel ${styles.panel}`}>
          <h3>邀请码（只显示这一次）</h3>
          <pre className={styles.pre}>{minted.code}</pre>
          <div className={styles.actions}>
            <button type="button" className="btn btn-secondary" onClick={copy}>{copied ? '已复制' : '复制'}</button>
            <button type="button" className="btn btn-quiet" onClick={() => setMinted(null)}>关闭</button>
          </div>
        </div>
      )}
      {error && <div className="banner banner-error" role="alert"><span>{error}</span></div>}
      <LoadState {...resource} empty={resource.data?.items.length === 0}>
        {resource.data && <>
          <div className={styles.tableWrap}><table><thead><tr>
            <th>备注</th><th>状态</th><th>有效期至</th><th>已用/上限</th><th>创建人</th><th>操作</th>
          </tr></thead>
            <tbody>{resource.data.items.map((invite) => <tr key={invite.id}>
              <td>{invite.label ?? '—'}</td>
              <td><InviteBadge invite={invite} /></td>
              <td>{formatDate(invite.expires_at)}</td>
              <td>{invite.redemption_count} / {invite.max_redemptions}</td>
              <td>{invite.created_by_username ?? '—'}</td>
              <td className={styles.actions}>
                <button type="button" className="btn btn-quiet" disabled={busy || invite.revoked_at !== null}
                  onClick={() => revoke(invite.id)}>撤销</button>
              </td>
            </tr>)}</tbody></table></div>
          <Pagination total={resource.data.total} offset={offset} onChange={setOffset} />
        </>}
      </LoadState>
    </section>
  )
}

/** 控制台首页：标签栏与当前标签的内容。tab 放在 URL 上，详情页返回时才能回到原来的标签。 */
export function AdminConsole() {
  const { token, onForbidden } = useOutletContext<AdminOutletContext>()
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const tab = TABS.some(([id]) => id === requested) ? requested as Tab : 'overview'
  return (
    <>
      <header className={styles.header}>
        <div><h1>管理员控制台</h1></div>
      </header>
      <nav className={styles.tabs} aria-label="管理视图">
        {TABS.map(([id, label]) => <button
          key={id}
          type="button"
          className={tab === id ? styles.activeTab : ''}
          aria-pressed={tab === id}
          onClick={() => setParams({ tab: id }, { replace: true })}
        >{label}</button>)}
      </nav>
      {tab === 'overview' && <OverviewView token={token} onForbidden={onForbidden} />}
      {tab === 'analytics' && <Analytics token={token} onForbidden={onForbidden} />}
      {tab === 'users' && <UsersView token={token} onForbidden={onForbidden} />}
      {tab === 'projects' && <ProjectsView token={token} onForbidden={onForbidden} />}
      {tab === 'tasks' && <TasksView token={token} onForbidden={onForbidden} />}
      {tab === 'runs' && <RunsView token={token} onForbidden={onForbidden} />}
      {tab === 'logs' && <LogsView token={token} onForbidden={onForbidden} />}
      {tab === 'invites' && <InvitesView token={token} onForbidden={onForbidden} />}
    </>
  )
}

/** /admin 的闸门与外壳：详情页是它的子路由，权限一变整棵子树（含详情页）一起换掉。 */
export default function AdminPage() {
  const { session, status, revalidate, logout } = useAuth()
  const [forbidden, setForbidden] = useState(false)
  const identity = session ? `${session.userId}:${session.token}` : ''
  useEffect(() => setForbidden(false), [identity])
  const onForbidden = useCallback(() => {
    setForbidden(true)
    revalidate()
  }, [revalidate])

  const allowed = status === 'authenticated'
    && session?.role === 'admin'
    && session.roleVerified === true
  if (!allowed || !session) {
    // 未登录或非管理员：给一页带左 rail 的空态，而不是白屏（游客仍能从这里走回其它页）。
    return (
      <div className={styles.wrap}>
        <ProjectRail projects={[]} onLogout={logout} />
        <main className={styles.main}>
          <div className="empty">只有管理员可以打开控制台。</div>
        </main>
      </div>
    )
  }
  if (forbidden) {
    return (
      <div className={styles.denied} role="alert">
        <h1>管理员权限已变化</h1>
        <p>受保护数据已清除，正在重新验证当前会话。</p>
      </div>
    )
  }
  return (
    <div className={styles.wrap}>
      <ProjectRail projects={[]} onLogout={logout} />
      <main className={styles.main}>
        <Outlet key={identity} context={{ token: session.token, onForbidden }} />
      </main>
    </div>
  )
}
