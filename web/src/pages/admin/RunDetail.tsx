/** 运行详情与运行表。运行表被「全部运行」与任务详情的节点流共用。 */
import { useCallback } from 'react'
import { useOutletContext, useParams } from 'react-router-dom'
import { adminApi, type AdminRun, type AdminRunDetail } from '../../lib/adminApi'
import { nodeLabel } from '../../lib/labels'
import {
  type AdminOutletContext,
  CapturedView,
  DetailPage,
  formatCost,
  formatDate,
  formatDuration,
  LoadState,
  RefreshButton,
  useResource,
} from './shared'
import styles from '../AdminPage.module.css'

export function RunTable({ runs, onSelect }: { runs: AdminRun[]; onSelect: (run: AdminRun) => void }) {
  return (
    <div className={styles.tableWrap}><table><thead><tr>
      <th>运行</th><th>节点</th><th>作品</th><th>模型</th><th>输入 token</th><th>输出 token</th>
      <th>预估成本</th><th>耗时</th><th>降级</th><th>重试</th><th>时间</th><th>操作</th>
    </tr></thead>
      <tbody>{runs.map((run) => <tr key={run.id}>
        <td>#{run.id}</td>
        <td><strong>{nodeLabel(run.node)}</strong></td>
        <td>{run.project_title ?? '—'}</td>
        <td>{run.model_id ?? '—'}</td>
        <td>{run.input_tokens.toLocaleString()}</td>
        <td>{run.output_tokens.toLocaleString()}</td>
        <td>{formatCost(run.cost_est)}</td>
        <td>{formatDuration(run.duration_ms)}</td>
        <td>{run.degraded ? '是' : '否'}</td>
        <td>{run.retry_count}</td>
        <td>{formatDate(run.created_at)}</td>
        <td><button type="button" className="btn btn-quiet" aria-label={`查看节点 ${run.node} #${run.id}`} onClick={() => onSelect(run)}>详情</button></td>
      </tr>)}</tbody></table></div>
  )
}

export function RunDetailView({ token, runId, onForbidden }: {
  token: string
  runId: number
  onForbidden: () => void
}) {
  const load = useCallback(
    (signal: AbortSignal) => adminApi.getRun(token, runId, signal),
    [runId, token],
  )
  const resource = useResource<AdminRunDetail>(load, onForbidden)
  const value = resource.data
  return (
    <LoadState {...resource} empty={!value}>
      {value && <article className={`panel ${styles.detail}`}>
        <div className={styles.detailHead}>
          <div><h3>节点 {nodeLabel(value.node)} #{value.id}</h3><p>{value.model_id ?? '未记录模型'} · {formatDuration(value.duration_ms)}</p></div>
          <RefreshButton onClick={resource.retry} />
        </div>
        {value.detail_missing && <p className="banner banner-warning">旧记录未保存详情，无法重建。</p>}
        {value.prompt_missing && <p className="banner banner-warning">旧记录未保存提示词，无法重建。</p>}
        <CapturedView value={value.detail} label="调试详情" />
        <CapturedView value={value.error} label="错误详情" />
      </article>}
    </LoadState>
  )
}

export function RunDetailPage() {
  const { token, onForbidden } = useOutletContext<AdminOutletContext>()
  const { runId = '' } = useParams()
  return (
    <DetailPage heading="运行详情" backTab="runs">
      <RunDetailView token={token} runId={Number(runId)} onForbidden={onForbidden} />
    </DetailPage>
  )
}
