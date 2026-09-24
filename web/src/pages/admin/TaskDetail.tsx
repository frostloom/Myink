/** 任务详情：任务本身的元数据与载荷，加上它下面的有序节点流。 */
import { useCallback, useState } from 'react'
import { useOutletContext, useParams } from 'react-router-dom'
import { adminApi, type AdminPage as PageResult, type AdminRun, type AdminTaskDetail } from '../../lib/adminApi'
import { taskChapterLabel, taskStatusLabel, taskTypeLabel } from '../../lib/labels'
import { RunDetailView, RunTable } from './RunDetail'
import {
  type AdminOutletContext,
  CapturedView,
  DetailPage,
  formatDate,
  formatDuration,
  LoadState,
  PAGE_SIZE,
  Pagination,
  RefreshButton,
  useResource,
} from './shared'
import styles from '../AdminPage.module.css'

export function TaskDetailView({ token, taskId, onForbidden }: {
  token: string
  taskId: string
  onForbidden: () => void
}) {
  const [offset, setOffset] = useState(0)
  const [runId, setRunId] = useState<number | null>(null)
  const loadTask = useCallback(
    (signal: AbortSignal) => adminApi.getTask(token, taskId, signal),
    [taskId, token],
  )
  const loadRuns = useCallback(
    (signal: AbortSignal) => adminApi.listTaskRuns(token, taskId, { limit: PAGE_SIZE, offset }, signal),
    [offset, taskId, token],
  )
  const detail = useResource<AdminTaskDetail>(loadTask, onForbidden)
  const runs = useResource<PageResult<AdminRun>>(loadRuns, onForbidden)
  return (
    <div className={styles.drilldown}>
      <section className={`panel ${styles.detail}`}>
        <LoadState {...detail} empty={!detail.data}>{detail.data && <>
          <div className={styles.detailHead}>
            <div>
              <h3>{detail.data.project_title} · {taskTypeLabel(detail.data.task_type)}</h3>
              <p>
                {detail.data.username} · {taskChapterLabel(detail.data)}
                {' · '}{taskStatusLabel(detail.data.status)}
              </p>
            </div>
            <RefreshButton onClick={detail.retry} />
          </div>
          <dl className={styles.summaryList}>
            <div><dt>任务 id</dt><dd>{detail.data.id}</dd></div>
            <div><dt>创建</dt><dd>{formatDate(detail.data.created_at)}</dd></div>
            <div><dt>更新</dt><dd>{formatDate(detail.data.updated_at)}</dd></div>
            <div><dt>任务跨度</dt><dd>{formatDuration(detail.data.elapsed_ms)}</dd></div>
            <div><dt>目标章节</dt><dd>{taskChapterLabel(detail.data)}</dd></div>
            <div><dt>批次任务</dt><dd>{detail.data.batch_task_id ?? '—'}</dd></div>
            <div><dt>重试</dt><dd>{detail.data.retry_count}</dd></div>
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

export function TaskDetailPage() {
  const { token, onForbidden } = useOutletContext<AdminOutletContext>()
  const { taskId = '' } = useParams()
  return (
    <DetailPage heading="任务详情" backTab="tasks">
      <TaskDetailView token={token} taskId={taskId} onForbidden={onForbidden} />
    </DetailPage>
  )
}
