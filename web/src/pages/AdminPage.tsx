import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { formatApiError } from '../lib/apiError'
import {
  adminApi,
  type AdminAccessLog,
  type AdminChapterDetail,
  type AdminContext,
  type AdminInvitation,
  type AdminInvitationCreated,
  type AdminOverview,
  type AdminPage as PageResult,
  type AdminProject,
  type AdminRun,
  type AdminRunDetail,
  type AdminTask,
  type AdminTaskDetail,
} from '../lib/adminApi'
import { Analytics } from './admin/Analytics'
import {
  CapturedView,
  formatDate,
  formatDuration,
  JsonText,
  LoadState,
  Metrics,
  PAGE_SIZE,
  Pagination,
  RefreshButton,
  useResource,
} from './admin/shared'
import styles from './AdminPage.module.css'

type Tab = 'overview' | 'analytics' | 'projects' | 'tasks' | 'runs' | 'logs' | 'invites'

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
                  <div key={name}><dt>{name}</dt><dd>{count}</dd></div>
                ))}</dl>}
            </div>
          </>
        )}
      </LoadState>
    </section>
  )
}

function ChapterDetailView({ token, projectId, chapterId, onForbidden }: {
  token: string
  projectId: string
  chapterId: string
  onForbidden: () => void
}) {
  const load = useCallback(
    (signal: AbortSignal) => adminApi.getChapter(token, projectId, chapterId, signal),
    [chapterId, projectId, token],
  )
  const resource = useResource<AdminChapterDetail>(load, onForbidden)
  return (
    <LoadState {...resource} empty={!resource.data}>
      {resource.data && <article className={`panel ${styles.detail}`}>
        <h3>{resource.data.title ?? `第 ${resource.data.chapter_seq} 章`} · v{resource.data.version}</h3>
        <h4>摘要</h4><JsonText value={resource.data.summary} />
        <h4>全文</h4><JsonText value={resource.data.content} />
      </article>}
    </LoadState>
  )
}

function ContextView({ value }: { value: AdminContext }) {
  const collections: Array<[string, AdminContext[keyof Pick<AdminContext,
    'outlines' | 'events' | 'facts' | 'characters' | 'foreshadows' | 'threads'
  >]]> = [
    ['大纲', value.outlines], ['事件', value.events], ['事实', value.facts],
    ['人物', value.characters], ['伏笔', value.foreshadows], ['故事线', value.threads],
  ]
  return (
    <div className={styles.context}>
      <CapturedView value={value.settings} label="作品设置" />
      {collections.map(([label, collection]) => <section className={styles.capture} key={label}>
        <h4>{label}（显示 {collection.items.length} / 共 {collection.total}）</h4>
        {collection.truncated && <span className="badge badge-warning">集合已截断</span>}
        {collection.items.length === 0
          ? <p className={styles.muted}>暂无记录</p>
          : collection.items.map((item, index) => <CapturedView key={`${label}-${index}`} value={item} label={`${label} ${index + 1}`} />)}
      </section>)}
    </div>
  )
}

function ProjectDetailView({ token, project, onForbidden }: {
  token: string
  project: AdminProject
  onForbidden: () => void
}) {
  const [offset, setOffset] = useState(0)
  const [chapterId, setChapterId] = useState<string | null>(null)
  const loadChapters = useCallback(
    (signal: AbortSignal) => adminApi.listChapters(
      token, project.id, { limit: PAGE_SIZE, offset }, signal,
    ),
    [offset, project.id, token],
  )
  const loadContext = useCallback(
    (signal: AbortSignal) => adminApi.getProjectContext(token, project.id, PAGE_SIZE, signal),
    [project.id, token],
  )
  const chapters = useResource(loadChapters, onForbidden)
  const context = useResource(loadContext, onForbidden)
  return (
    <div className={styles.drilldown}>
      <div className={styles.detailHead}>
        <div><h3>《{project.title}》</h3><p>{project.username} · {project.genre} · {project.creation_status}</p></div>
        <div><RefreshButton onClick={chapters.retry} /> <button type="button" className="btn btn-secondary" onClick={context.retry}>刷新设定</button></div>
      </div>
      <div className={styles.split}>
        <section className={`panel ${styles.detail}`}>
          <h3>章节元数据</h3>
          <LoadState {...chapters} empty={chapters.data?.items.length === 0}>
            {chapters.data && <>
              <ul className={styles.list}>{chapters.data.items.map((chapter) => <li key={chapter.id}>
                <div><strong>{chapter.title ?? `第 ${chapter.chapter_seq} 章`}</strong><small>{chapter.status} · {chapter.word_count.toLocaleString()} 字 · {formatDate(chapter.updated_at)}</small></div>
                <button type="button" className="btn btn-quiet" aria-label={`查看${chapter.title ?? `第 ${chapter.chapter_seq} 章`}全文`} onClick={() => setChapterId(chapter.id)}>全文</button>
              </li>)}</ul>
              <Pagination total={chapters.data.total} offset={offset} onChange={(next) => { setChapterId(null); setOffset(next) }} />
            </>}
          </LoadState>
        </section>
        <section className={`panel ${styles.detail}`}>
          <h3>受限上下文快照</h3>
          <LoadState {...context} empty={!context.data}>{context.data && <ContextView value={context.data} />}</LoadState>
        </section>
      </div>
      {chapterId && <ChapterDetailView key={chapterId} token={token} projectId={project.id} chapterId={chapterId} onForbidden={onForbidden} />}
    </div>
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
  const [selected, setSelected] = useState<AdminProject | null>(null)
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listProjects(token, { ...filters, limit: PAGE_SIZE, offset }, signal),
    [filters, offset, token],
  )
  const resource = useResource<PageResult<AdminProject>>(load, onForbidden)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setSelected(null)
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
          <div className={styles.tableWrap}><table><thead><tr><th>作品</th><th>作者</th><th>状态</th><th>章节/字数/任务</th><th>运行/预估成本</th><th>操作</th></tr></thead>
            <tbody>{resource.data.items.map((project) => <tr key={project.id}>
              <td><strong>{project.title}</strong><small>{project.id}</small></td><td>{project.username}</td>
              <td>{project.creation_status}</td><td>{project.chapter_count} / {project.word_count.toLocaleString()} / {project.task_count}</td>
              <td>{project.metrics.run_count} / {project.metrics.cost_est.toFixed(4)}</td>
              <td><button type="button" className="btn btn-quiet" aria-label={`查看《${project.title}》`} onClick={() => setSelected(project)}>查看</button></td>
            </tr>)}</tbody></table></div>
          <Pagination total={resource.data.total} offset={offset} onChange={(next) => { setSelected(null); setOffset(next) }} />
        </>}
      </LoadState>
      {selected && <ProjectDetailView key={selected.id} token={token} project={selected} onForbidden={onForbidden} />}
    </section>
  )
}

function RunTable({ runs, onSelect }: { runs: AdminRun[]; onSelect: (run: AdminRun) => void }) {
  return (
    <div className={styles.tableWrap}><table><thead><tr><th># / 节点</th><th>作品/任务</th><th>模型</th><th>Token</th><th>预估成本</th><th>计时</th><th>状态</th><th>操作</th></tr></thead>
      <tbody>{runs.map((run) => <tr key={run.id}>
        <td><strong>#{run.id} {run.node}</strong><small>{formatDate(run.created_at)}</small></td>
        <td>{run.project_title}<small>{run.task_id ?? '无关联任务'}</small></td>
        <td>{run.model_id ?? '未记录'}<small>{run.role ?? '未记录角色'}</small></td>
        <td>{run.input_tokens.toLocaleString()} / {run.output_tokens.toLocaleString()}</td>
        <td>{run.cost_est.toFixed(4)}（估算）</td>
        <td>{formatDuration(run.duration_ms)}{run.duration_ms === 0 && <small>0 表示未记录</small>}</td>
        <td>{run.degraded ? '降级' : '未降级'} · 重试 {run.retry_count}</td>
        <td><button type="button" className="btn btn-quiet" aria-label={`查看节点 ${run.node} #${run.id}`} onClick={() => onSelect(run)}>详情</button></td>
      </tr>)}</tbody></table></div>
  )
}

function RunDetailView({ token, runId, onForbidden }: {
  token: string
  runId: number
  onForbidden: () => void
}) {
  const load = useCallback(
    (signal: AbortSignal) => adminApi.getRun(token, runId, signal),
    [runId, token],
  )
  const resource = useResource<AdminRunDetail>(load, onForbidden)
  return (
    <LoadState {...resource} empty={!resource.data}>
      {resource.data && <article className={`panel ${styles.detail}`}>
        <div className={styles.detailHead}><div><h3>节点 {resource.data.node} #{resource.data.id}</h3><p>{resource.data.model_id ?? '未记录模型'} · {formatDuration(resource.data.duration_ms)}</p></div><RefreshButton onClick={resource.retry} /></div>
        {resource.data.duration_ms === 0 && <p className="banner banner-warning">节点时长 0 表示未记录，不代表瞬时完成。</p>}
        {resource.data.detail_missing && <p className="banner banner-warning">旧记录未保存详情，无法重建。</p>}
        {resource.data.prompt_missing && <p className="banner banner-warning">旧记录未保存提示词，无法重建。</p>}
        <CapturedView value={resource.data.detail} label="实际调试详情（提示词、输出、审计与召回片段）" />
        <CapturedView value={resource.data.error} label="错误详情" />
      </article>}
    </LoadState>
  )
}

function TaskDetailView({ token, task, onForbidden }: {
  token: string
  task: AdminTask
  onForbidden: () => void
}) {
  const [offset, setOffset] = useState(0)
  const [runId, setRunId] = useState<number | null>(null)
  const loadTask = useCallback(
    (signal: AbortSignal) => adminApi.getTask(token, task.id, signal),
    [task.id, token],
  )
  const loadRuns = useCallback(
    (signal: AbortSignal) => adminApi.listTaskRuns(token, task.id, { limit: PAGE_SIZE, offset }, signal),
    [offset, task.id, token],
  )
  const detail = useResource<AdminTaskDetail>(loadTask, onForbidden)
  const runs = useResource<PageResult<AdminRun>>(loadRuns, onForbidden)
  return (
    <div className={styles.drilldown}>
      <section className={`panel ${styles.detail}`}>
        <div className={styles.detailHead}><div><h3>任务 {task.id}</h3><p>{task.project_title} · {task.task_type} · {detail.data?.status ?? task.status}</p></div><RefreshButton onClick={detail.retry} /></div>
        <LoadState {...detail} empty={!detail.data}>{detail.data && <>
          <dl className={styles.summaryList}>
            <div><dt>创建/更新</dt><dd>{formatDate(detail.data.created_at)} / {formatDate(detail.data.updated_at)}</dd></div>
            <div><dt>任务跨度</dt><dd>{formatDuration(detail.data.elapsed_ms)} <small>包含排队、暂停与人工等待</small></dd></div>
            <div><dt>章节/批次</dt><dd>{detail.data.chapter_seq ?? '无'} / {detail.data.batch_task_id ?? '无'}</dd></div>
          </dl>
          <CapturedView value={detail.data.payload} label="任务载荷" />
          <CapturedView value={detail.data.error} label="任务错误" />
        </>}</LoadState>
      </section>
      <section className={`panel ${styles.detail}`}>
        <div className={styles.detailHead}><div><h3>有序节点流</h3></div><RefreshButton onClick={runs.retry} /></div>
        <LoadState {...runs} empty={runs.data?.items.length === 0}>
          {runs.data && <><RunTable runs={runs.data.items} onSelect={(run) => setRunId(run.id)} /><Pagination total={runs.data.total} offset={offset} onChange={(next) => { setRunId(null); setOffset(next) }} /></>}
        </LoadState>
      </section>
      {runId !== null && <RunDetailView key={runId} token={token} runId={runId} onForbidden={onForbidden} />}
    </div>
  )
}

function TasksView({ token, onForbidden }: {
  token: string
  onForbidden: () => void
}) {
  const [draft, setDraft] = useState({ userId: '', projectId: '', status: '' })
  const [filters, setFilters] = useState(draft)
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<AdminTask | null>(null)
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listTasks(token, { ...filters, limit: PAGE_SIZE, offset }, signal),
    [filters, offset, token],
  )
  const resource = useResource<PageResult<AdminTask>>(load, onForbidden)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setSelected(null)
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
          <div className={styles.tableWrap}><table><thead><tr><th>任务</th><th>用户/作品</th><th>类型/状态</th><th>章节/重试</th><th>运行/Token</th><th>操作</th></tr></thead>
            <tbody>{resource.data.items.map((task) => <tr key={task.id}>
              <td><strong>{task.id}</strong><small>{formatDate(task.created_at)}</small></td><td>{task.username}<small>{task.project_title}</small></td>
              <td>{task.task_type} / {task.status}</td><td>{task.chapter_seq ?? '无'} / {task.retry_count}</td>
              <td>{task.metrics.run_count} / {(task.metrics.input_tokens + task.metrics.output_tokens).toLocaleString()}</td>
              <td><button type="button" className="btn btn-quiet" aria-label={`查看任务 ${task.id}`} onClick={() => setSelected(task)}>查看</button></td>
            </tr>)}</tbody></table></div>
          <Pagination total={resource.data.total} offset={offset} onChange={(next) => { setSelected(null); setOffset(next) }} />
        </>}
      </LoadState>
      {selected && <TaskDetailView key={selected.id} token={token} task={selected} onForbidden={onForbidden} />}
    </section>
  )
}

function RunsView({ token, onForbidden }: { token: string; onForbidden: () => void }) {
  const [draft, setDraft] = useState({ userId: '', projectId: '', node: '' })
  const [filters, setFilters] = useState(draft)
  const [offset, setOffset] = useState(0)
  const [runId, setRunId] = useState<number | null>(null)
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listRuns(token, { ...filters, limit: PAGE_SIZE, offset }, signal),
    [filters, offset, token],
  )
  const resource = useResource<PageResult<AdminRun>>(load, onForbidden)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setRunId(null)
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
        {resource.data && <><RunTable runs={resource.data.items} onSelect={(run) => setRunId(run.id)} /><Pagination total={resource.data.total} offset={offset} onChange={(next) => { setRunId(null); setOffset(next) }} /></>}
      </LoadState>
      {runId !== null && <RunDetailView key={runId} token={token} runId={runId} onForbidden={onForbidden} />}
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

function AdminConsole({ token, logout, onForbidden }: {
  token: string
  logout: () => Promise<void>
  onForbidden: () => void
}) {
  const [tab, setTab] = useState<Tab>('overview')
  const tabs: Array<[Tab, string]> = [
    ['overview', '概览'], ['analytics', '分析'], ['projects', '作品'], ['tasks', '任务'],
    ['runs', '全部运行'], ['logs', '访问日志'], ['invites', '邀请码'],
  ]
  return (
    <div className={styles.wrap}>
      <ProjectRail projects={[]} onLogout={logout} />
      <main className={styles.main}>
        <header className={styles.header}>
          <div><h1>管理员控制台</h1></div>
        </header>
        <nav className={styles.tabs} aria-label="管理视图">
          {tabs.map(([id, label]) => <button
            key={id}
            type="button"
            className={tab === id ? styles.activeTab : ''}
            aria-pressed={tab === id}
            onClick={() => setTab(id)}
          >{label}</button>)}
        </nav>
        {tab === 'overview' && <OverviewView token={token} onForbidden={onForbidden} />}
        {tab === 'analytics' && <Analytics token={token} onForbidden={onForbidden} />}
        {tab === 'projects' && <ProjectsView token={token} onForbidden={onForbidden} />}
        {tab === 'tasks' && <TasksView token={token} onForbidden={onForbidden} />}
        {tab === 'runs' && <RunsView token={token} onForbidden={onForbidden} />}
        {tab === 'logs' && <LogsView token={token} onForbidden={onForbidden} />}
        {tab === 'invites' && <InvitesView token={token} onForbidden={onForbidden} />}
      </main>
    </div>
  )
}

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
    <AdminConsole
      key={identity}
      token={session.token}
      logout={logout}
      onForbidden={onForbidden}
    />
  )
}
