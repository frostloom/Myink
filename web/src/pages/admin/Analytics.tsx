import { useCallback, useState, type FormEvent } from 'react'
import {
  adminApi,
  type AdminProject,
  type AdminTaskAverages,
  type AdminTaskChapter,
  type AdminUser,
  type AdminGenerationTask,
  type AdminPage as PageResult,
  type AdminSnapshotFinding,
} from '../../lib/adminApi'
import {
  conflictTypeLabel,
  creationStatusLabel,
  findingSourceLabel,
  nodeLabel,
  roleLabel,
  scopeLabel,
  severityLabel,
  taskStatusLabel,
  taskTypeLabel,
  tierLabel,
} from '../../lib/labels'
import { severityClass } from '../../lib/snapshotView'
import { SnapshotView } from './SnapshotView'
import {
  FieldRows,
  formatCost,
  formatDate,
  formatDuration,
  LoadState,
  PAGE_SIZE,
  Pagination,
  RefreshButton,
  useResource,
} from './shared'
import styles from './Analytics.module.css'

function formatAverageDuration(value: number | null): string {
  if (value === null) return '—'
  const rounded = Math.round(value)
  return rounded < 1000 ? `${rounded} ms` : `${(rounded / 1000).toFixed(2)} 秒`
}

/** 单次任务的均值：先按任务汇总再对任务取平均，不是对 run 行取平均。 */
function Averages({ value }: { value: AdminTaskAverages }) {
  if (value.avg_runs_per_task === null) return <span className={styles.muted}>无任务</span>
  return (
    <FieldRows rows={[
      ['预估成本', formatCost(value.avg_cost_per_task ?? 0)],
      ['耗时', formatAverageDuration(value.avg_duration_ms_per_task)],
      ['调用', `${value.avg_runs_per_task.toFixed(1)} 次/任务`],
    ]} />
  )
}

function FindingsPanel({ token, projectId, onForbidden }: {
  token: string
  projectId: string
  onForbidden: () => void
}) {
  const [draftSeverity, setDraftSeverity] = useState('')
  const [draftChapter, setDraftChapter] = useState('')
  const [filters, setFilters] = useState<{ severity: string; chapterSeq?: number }>({ severity: '' })
  const [offset, setOffset] = useState(0)
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listFindings(
      token, projectId, { ...filters, limit: PAGE_SIZE, offset }, signal,
    ),
    [filters, offset, projectId, token],
  )
  const resource = useResource<PageResult<AdminSnapshotFinding>>(load, onForbidden)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setOffset(0)
    const chapter = Number(draftChapter)
    setFilters({
      severity: draftSeverity.trim(),
      chapterSeq: draftChapter.trim() !== '' && Number.isFinite(chapter) ? chapter : undefined,
    })
  }
  return (
    <section className={`panel ${styles.panel}`}>
      <div className={styles.panelHead}>
        <div><h3>校验发现</h3></div>
        <RefreshButton onClick={resource.retry} />
      </div>
      <form className={styles.filters} aria-label="发现筛选" onSubmit={submit}>
        <label><span>严重度</span><input className="input" maxLength={16}
          value={draftSeverity} onChange={(event) => setDraftSeverity(event.target.value)} /></label>
        <label><span>章号</span><input className="input" type="number" min={1}
          value={draftChapter} onChange={(event) => setDraftChapter(event.target.value)} /></label>
        <button className="btn btn-primary" type="submit">筛选</button>
      </form>
      <LoadState {...resource} empty={resource.data?.items.length === 0}>
        {resource.data && <>
          <div className={styles.tableWrap}><table>
            <thead><tr>
              <th>章</th><th>第几次</th><th>严重度</th><th>类型</th><th>范围</th><th>来源</th><th>建议</th><th>证据</th>
            </tr></thead>
            <tbody>{resource.data.items.map((finding, index) => <tr key={`${finding.snapshot_id}-${index}`}>
              <td>第 {finding.chapter_seq ?? '—'} 章</td>
              <td>第 {finding.attempt} 次</td>
              <td><span className={severityClass(finding.severity)}>{finding.severity ? severityLabel(finding.severity) : '未标'}</span></td>
              <td>{finding.conflict_type ? conflictTypeLabel(finding.conflict_type) : '—'}</td>
              <td>{finding.scope ? scopeLabel(finding.scope) : '—'}</td>
              <td>{finding.source ? findingSourceLabel(finding.source) : '—'}</td>
              <td>{finding.suggestion ?? '—'}</td>
              <td>{finding.evidence.map((item) => `第 ${item.chapter} 章：${item.quote}`).join('；') || '—'}</td>
            </tr>)}</tbody>
          </table></div>
          <Pagination total={resource.data.total} offset={offset} onChange={setOffset} />
        </>}
      </LoadState>
    </section>
  )
}

function ChapterSnapshots({ chapter, onSelect }: {
  chapter: AdminTaskChapter
  onSelect: (snapshotId: number | null) => void
}) {
  if (chapter.snapshots.length === 0) return <p className={styles.muted}>这一章没有落盘快照</p>
  return (
    <div className={styles.tableWrap}><table>
      <thead><tr>
        <th>阶段</th><th>第几次</th><th>时间</th><th>模型</th>
        <th>预估成本</th><th>耗时</th><th>降级</th><th>操作</th>
      </tr></thead>
      <tbody>{chapter.snapshots.map((ref) => <tr key={ref.id}>
        <td>{nodeLabel(ref.stage)}</td>
        <td>第 {ref.attempt} 次</td>
        <td>{formatDate(ref.created_at)}</td>
        <td>{ref.model_id ?? '未记录'}</td>
        <td>{formatCost(ref.cost_est)}</td>
        <td>{formatDuration(ref.duration_ms)}</td>
        <td>{ref.degraded ? '是' : '否'}</td>
        <td><button type="button" className="btn btn-quiet"
          aria-label={`查看第 ${chapter.chapter_seq} 章 ${ref.stage} 快照`}
          onClick={() => onSelect(ref.id)}>查看</button></td>
      </tr>)}</tbody>
    </table></div>
  )
}

function TaskChapters({ token, task, onForbidden }: {
  token: string
  task: AdminGenerationTask
  onForbidden: () => void
}) {
  const [offset, setOffset] = useState(0)
  const [chapter, setChapter] = useState<AdminTaskChapter | null>(null)
  const [snapshotId, setSnapshotId] = useState<number | null>(null)
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listTaskChapters(
      token, task.id, { limit: PAGE_SIZE, offset }, signal,
    ),
    [offset, task.id, token],
  )
  const resource = useResource<PageResult<AdminTaskChapter>>(load, onForbidden)
  return (
    <section className={`panel ${styles.panel}`}>
      <div className={styles.panelHead}>
        <div><h3>{taskTypeLabel(task.task_type)} · 每章分解
          {task.chapter_seq === null ? '（整批）' : `（目标第 ${task.chapter_seq} 章）`}</h3></div>
        <RefreshButton onClick={resource.retry} />
      </div>
      <LoadState {...resource} empty={resource.data?.items.length === 0}>
        {resource.data && <>
          <div className={styles.tableWrap}><table>
            <thead><tr>
              <th>章</th><th>跑过的节点</th><th>运行</th><th>token 合计</th>
              <th>预估成本</th><th>耗时</th><th>快照</th><th>操作</th>
            </tr></thead>
            <tbody>{resource.data.items.map((row) => <tr key={String(row.chapter_seq)}>
              <td>第 {row.chapter_seq ?? '—'} 章</td>
              <td>{row.stages.map(nodeLabel).join('、') || '无'}</td>
              <td>{row.metrics.run_count}</td>
              <td>{(row.metrics.input_tokens + row.metrics.output_tokens).toLocaleString()}</td>
              <td>{formatCost(row.metrics.cost_est)}</td>
              <td>{formatDuration(row.metrics.duration_ms)}</td>
              <td>{row.snapshots.length}</td>
              <td><button type="button" className="btn btn-quiet"
                aria-label={`查看第 ${row.chapter_seq} 章的快照`}
                onClick={() => { setSnapshotId(null); setChapter(row) }}>快照</button></td>
            </tr>)}</tbody>
          </table></div>
          <Pagination total={resource.data.total} offset={offset}
            onChange={(next) => { setChapter(null); setSnapshotId(null); setOffset(next) }} />
        </>}
      </LoadState>
      {chapter && <div className={styles.drilldown}>
        <div className={styles.panelHead}>
          <div><h4>第 {chapter.chapter_seq ?? '—'} 章的快照</h4></div>
          <button type="button" className="btn btn-quiet" onClick={() => { setChapter(null); setSnapshotId(null) }}>收起</button>
        </div>
        <ChapterSnapshots chapter={chapter} onSelect={setSnapshotId} />
      </div>}
      {snapshotId !== null && <SnapshotView key={snapshotId} token={token} snapshotId={snapshotId} onForbidden={onForbidden} />}
    </section>
  )
}

function BookTasks({ token, project, onForbidden }: {
  token: string
  project: AdminProject
  onForbidden: () => void
}) {
  const [offset, setOffset] = useState(0)
  const [task, setTask] = useState<AdminGenerationTask | null>(null)
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listGenerationTasks(
      token, project.id, { limit: PAGE_SIZE, offset }, signal,
    ),
    [offset, project.id, token],
  )
  const resource = useResource<PageResult<AdminGenerationTask>>(load, onForbidden)
  return (
    <div className={styles.drilldown}>
      <section className={`panel ${styles.panel}`}>
        <div className={styles.panelHead}>
          <div><h3>《{project.title}》的任务</h3></div>
          <RefreshButton onClick={resource.retry} />
        </div>
        <LoadState {...resource} empty={resource.data?.items.length === 0}>
          {resource.data && <>
            <div className={styles.tableWrap}><table>
              <thead><tr>
                <th>任务</th><th>状态</th><th>目标章节</th><th>章数</th><th>快照</th><th>运行</th>
                <th>token 合计</th><th>预估成本</th><th>耗时</th><th>重试</th><th>创建时间</th><th>操作</th>
              </tr></thead>
              <tbody>{resource.data.items.map((row) => <tr key={row.id}>
                <td>{taskTypeLabel(row.task_type)}</td>
                <td>{taskStatusLabel(row.status)}</td>
                <td>{row.chapter_seq === null ? '整批' : `第 ${row.chapter_seq} 章`}</td>
                <td>{row.chapter_count}</td>
                <td>{row.snapshot_count}</td>
                <td>{row.metrics.run_count}</td>
                <td>{(row.metrics.input_tokens + row.metrics.output_tokens).toLocaleString()}</td>
                <td>{formatCost(row.metrics.cost_est)}</td>
                <td>{formatDuration(row.metrics.duration_ms)}</td>
                <td>{row.retry_count}</td>
                <td>{formatDate(row.created_at)}</td>
                <td><button type="button" className="btn btn-quiet" aria-label={`查看任务 ${row.id} 的每章分解`}
                  onClick={() => setTask(row)}>每章</button></td>
              </tr>)}</tbody>
            </table></div>
            <Pagination total={resource.data.total} offset={offset}
              onChange={(next) => { setTask(null); setOffset(next) }} />
          </>}
        </LoadState>
      </section>
      {task && <TaskChapters key={task.id} token={token} task={task} onForbidden={onForbidden} />}
      <FindingsPanel token={token} projectId={project.id} onForbidden={onForbidden} />
    </div>
  )
}

function UserBooks({ token, user, onForbidden }: {
  token: string
  user: AdminUser
  onForbidden: () => void
}) {
  const [offset, setOffset] = useState(0)
  const [project, setProject] = useState<AdminProject | null>(null)
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listProjects(
      token, { userId: user.id, limit: PAGE_SIZE, offset }, signal,
    ),
    [offset, token, user.id],
  )
  const resource = useResource<PageResult<AdminProject>>(load, onForbidden)
  return (
    <div className={styles.drilldown}>
      <section className={`panel ${styles.panel}`}>
        <div className={styles.panelHead}>
          <div><h3>{user.username} 的作品</h3></div>
          <RefreshButton onClick={resource.retry} />
        </div>
        <LoadState {...resource} empty={resource.data?.items.length === 0}>
          {resource.data && <>
            <div className={styles.tableWrap}><table>
              <thead><tr>
                <th>作品</th><th>题材</th><th>状态</th><th>章节</th><th>字数</th>
                <th>任务</th><th>运行</th><th>单次任务均值</th><th>操作</th>
              </tr></thead>
              <tbody>{resource.data.items.map((row) => <tr key={row.id}>
                <td>{row.title}</td>
                <td>{row.genre || '—'}</td>
                <td>{creationStatusLabel(row.creation_status)}</td>
                <td>{row.chapter_count}</td>
                <td>{row.word_count.toLocaleString()}</td>
                <td>{row.task_count}</td>
                <td>{row.metrics.run_count}</td>
                <td><Averages value={row.task_averages} /></td>
                <td><button type="button" className="btn btn-quiet" aria-label={`查看《${row.title}》的分析`}
                  onClick={() => setProject(row)}>下钻</button></td>
              </tr>)}</tbody>
            </table></div>
            <Pagination total={resource.data.total} offset={offset}
              onChange={(next) => { setProject(null); setOffset(next) }} />
          </>}
        </LoadState>
      </section>
      {project && <BookTasks key={project.id} token={token} project={project} onForbidden={onForbidden} />}
    </div>
  )
}

export function Analytics({ token, onForbidden }: { token: string; onForbidden: () => void }) {
  const [draft, setDraft] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const [user, setUser] = useState<AdminUser | null>(null)
  const load = useCallback(
    (signal: AbortSignal) => adminApi.listUsers(token, { q, limit: PAGE_SIZE, offset }, signal),
    [offset, q, token],
  )
  const resource = useResource<PageResult<AdminUser>>(load, onForbidden)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setUser(null)
    setOffset(0)
    setQ(draft.trim())
  }
  return (
    <section className={styles.view} aria-labelledby="analytics-heading">
      <div className={styles.viewHead}>
        <div><h2 id="analytics-heading">分析</h2></div>
        <RefreshButton onClick={resource.retry} />
      </div>
      <form className={styles.filters} role="search" aria-label="用户筛选" onSubmit={submit}>
        <label><span>搜索用户</span><input className="input" maxLength={128}
          value={draft} onChange={(event) => setDraft(event.target.value)} /></label>
        <button className="btn btn-primary" type="submit">搜索</button>
      </form>
      <LoadState {...resource} empty={resource.data?.items.length === 0}>
        {resource.data && <>
          <div className={styles.tableWrap}><table>
            <thead><tr>
              <th>用户</th><th>角色</th><th>等级</th><th>作品</th><th>章节</th>
              <th>字数</th><th>任务</th><th>运行</th><th>单次任务均值</th><th>操作</th>
            </tr></thead>
            <tbody>{resource.data.items.map((row) => <tr key={row.id}>
              <td>{row.username}</td>
              <td>{roleLabel(row.role)}</td>
              <td>{tierLabel(row.tier)}</td>
              <td>{row.project_count}</td>
              <td>{row.chapter_count}</td>
              <td>{row.word_count.toLocaleString()}</td>
              <td>{row.task_count}</td>
              <td>{row.metrics.run_count}</td>
              <td><Averages value={row.task_averages} /></td>
              <td><button type="button" className="btn btn-quiet" aria-label={`分析 ${row.username}`}
                onClick={() => setUser(row)}>下钻</button></td>
            </tr>)}</tbody>
          </table></div>
          <Pagination total={resource.data.total} offset={offset}
            onChange={(next) => { setUser(null); setOffset(next) }} />
        </>}
      </LoadState>
      {user && <UserBooks key={user.id} token={token} user={user} onForbidden={onForbidden} />}
    </section>
  )
}
