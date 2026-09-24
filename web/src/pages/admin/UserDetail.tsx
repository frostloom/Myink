/** 用户详情：这个人的总花费，以及构成它的每一次调用（含没有任何作品的那些）。 */
import { useCallback, useState } from 'react'
import { useOutletContext, useParams } from 'react-router-dom'
import { ApiError } from '../../lib/api'
import { adminApi } from '../../lib/adminApi'
import {
  type AdminOutletContext,
  DetailPage,
  formatCost,
  LoadState,
  Metrics,
  PAGE_SIZE,
  useResource,
} from './shared'
import { RunDetailView, RunTable } from './RunDetail'
import styles from '../AdminPage.module.css'

export function UserDetailPage() {
  const { token, onForbidden } = useOutletContext<AdminOutletContext>()
  const { userId = '' } = useParams()
  const loadUser = useCallback(async (signal: AbortSignal) => {
    try {
      return await adminApi.getUser(token, userId, signal)
    } catch (reason) {
      // 未知 id 要说人话：404 的英文码透传给用户看没有意义。
      if (reason instanceof ApiError && reason.status === 404) {
        throw new ApiError(404, '用户不存在', reason.body)
      }
      throw reason
    }
  }, [token, userId])
  const loadRuns = useCallback(
    (signal: AbortSignal) => adminApi.listRuns(token, { userId, limit: PAGE_SIZE, offset: 0 }, signal),
    [token, userId],
  )
  const user = useResource(loadUser, onForbidden)
  const runs = useResource(loadRuns, onForbidden)
  const value = user.data
  const [selected, setSelected] = useState<number | null>(null)

  return (
    <DetailPage heading={value ? `${value.username} · 账号详情` : '账号详情'} backTab="users">
      <LoadState {...user} empty={!value}>
        {value && <div className={`panel ${styles.panel}`}>
          <h3>总花费 {formatCost(value.metrics.cost_est)}</h3>
          <p>{value.tier} · {value.role} · 作品 {value.project_count} 本</p>
          <Metrics value={value.metrics} />
        </div>}
      </LoadState>
      <section className={`panel ${styles.panel}`}>
        <h3>调用明细</h3>
        <LoadState {...runs} empty={runs.data?.items.length === 0}>
          {runs.data && <RunTable runs={runs.data.items} onSelect={(run) => setSelected(run.id)} />}
        </LoadState>
      </section>
      {selected !== null && <RunDetailView token={token} runId={selected} onForbidden={onForbidden} />}
    </DetailPage>
  )
}
