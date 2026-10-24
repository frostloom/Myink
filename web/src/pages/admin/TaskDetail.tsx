/** 任务详情：任务本身的元数据与载荷，加上它下面的有序节点流。 */
import { useCallback, useState } from 'react'
import { useOutletContext, useParams } from 'react-router-dom'
import { adminApi, type AdminPage as PageResult, type AdminRun, type AdminTaskDetail } from '../../lib/adminApi'
import { nodeLabel, taskChapterLabel, taskStatusLabel, taskTypeLabel } from '../../lib/labels'
import { RunDetailView } from './RunDetail'
import {asRecord} from '../../lib/snapshotView'
import {Disclosure,ExecutionError} from './ExecutionContent'
import layout from './ExecutionDetail.module.css'
import {
  type AdminOutletContext,
  CapturedView,
  DetailPage,
  formatDate,
  formatCost,
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
  const value=detail.data
  const payload=asRecord(value?.payload.data)
  const snapshot=asRecord(payload?.writing_resources)
  const library=Array.isArray(snapshot?.reference_library)?snapshot.reference_library:[]
  const roles=asRecord(snapshot?.role_prompts)
  const groups=new Map<string,AdminRun[]>()
  for(const run of runs.data?.items??[]) groups.set(run.node,[...(groups.get(run.node)??[]),run])
  return (
    <div className={styles.drilldown}>
      <section className={`panel ${styles.detail}`}>
        <LoadState {...detail} empty={!value}>{value&&<div className={layout.summary}>
          <div className={layout.summaryHead}><div><h2>{value.project_title}</h2><p className={layout.meta}><span>{taskTypeLabel(value.task_type)}</span><span>{value.username}</span><span className="badge">{taskStatusLabel(value.status)}</span></p></div><RefreshButton onClick={()=>{detail.retry();runs.retry()}}/></div>
          <dl className={layout.readings}>
            <div><dt>任务跨度</dt><dd>{formatDuration(value.elapsed_ms)}</dd></div>
            <div><dt>模型调用</dt><dd>{value.metrics.run_count} 次</dd></div>
            <div><dt>预估成本</dt><dd>{formatCost(value.metrics.cost_est)}</dd></div>
            <div><dt>目标篇幅</dt><dd>{typeof payload?.chapter_count==='number'?`${payload.chapter_count} 章`:taskChapterLabel(value)}{typeof payload?.chars_per_chapter==='number'?` · 每章 ${payload.chars_per_chapter} 字`:''}</dd></div>
          </dl>
          <p className={layout.muted}>创建于 {formatDate(value.created_at)} · 更新于 {formatDate(value.updated_at)}</p>
          {Boolean(value.error.data)&&<ExecutionError value={value.error} label="任务错误"/>}
        </div>}</LoadState>
      </section>
      <section className={`panel ${styles.detail}`} aria-label="执行记录">
        <div className={styles.detailHead}><div><h3>执行记录</h3><p>按创作环节分组；展开一次模型调用，查看输出和实际资料查阅。</p></div></div>
        <LoadState {...runs} empty={runs.data?.items.length===0}>
          {Array.from(groups,([node,items])=><section key={node} className={layout.group}>
            <div className={layout.groupHead}><h4>{nodeLabel(node)}</h4><span>本页 {items.length} 次调用</span></div>
            <div className={layout.calls}>{items.sort((a,b)=>Date.parse(a.created_at)-Date.parse(b.created_at)||a.id-b.id).map(run=><div key={run.id}>
              <button type="button" className={layout.call} aria-label={`查看节点 ${run.node} #${run.id}`} aria-expanded={runId===run.id} onClick={()=>setRunId(runId===run.id?null:run.id)}>
                <span className={layout.callMain}><strong>{run.model_id??'未记录模型'}</strong><span className={layout.callMeta}><span>记录 #{run.id}</span><span>{formatDate(run.created_at)}</span>{run.degraded&&<span>使用备用模型</span>}{run.retry_count>0&&<span>重试 {run.retry_count} 次</span>}</span></span>
                <span className={layout.callMeta}><span>{formatDuration(run.duration_ms)}</span><span>预估 {formatCost(run.cost_est)}</span><span>{runId===run.id?'收起':'查看详情'}</span></span>
              </button>
              {runId===run.id&&<RunDetailView token={token} runId={run.id} onForbidden={onForbidden}/>}
            </div>)}</div>
          </section>)}
          {runs.data&&runs.data.total>PAGE_SIZE&&<Pagination total={runs.data.total} offset={offset} onChange={next=>{setRunId(null);setOffset(next)}}/>}
        </LoadState>
      </section>
      {value&&<section className={`panel ${styles.detail}`}><h3>本任务的资源版本</h3><p className={layout.muted}>{roles||Array.isArray(snapshot?.reference_library)?<>已冻结 {roles?Object.keys(roles).length:0} 类角色提示词、{library.length} 项可查阅资料。{value.payload.truncated&&'快照已截断，数量仅表示留存的条目。'}可用资料数量不代表实际查阅次数，请以执行记录中的查阅结果为准。</>:'这条旧任务未保存资源版本，无法还原当时的可用资料；实际使用情况请查看执行记录。'}</p>
        <Disclosure title="技术诊断"><dl className={styles.summaryList}><div><dt>任务编号</dt><dd>{value.id}</dd></div><div><dt>批次编号</dt><dd>{value.batch_task_id??'无'}</dd></div><div><dt>任务重试</dt><dd>{value.retry_count}</dd></div></dl><CapturedView value={value.payload} raw label="原始任务快照"/>{Boolean(value.error.data)&&<CapturedView value={value.error} raw label="原始错误记录"/>}</Disclosure>
      </section>}
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
