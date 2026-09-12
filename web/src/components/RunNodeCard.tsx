// 执行节点卡：agent_runs 单行快照（node 中文标签 + 模型 + token + 缓存 + 耗时 + 估算成本 + 重试/降级/错误）。
import { nodeLabel, verdictLabel } from '../lib/labels'
import type { AgentRun } from '../types'
import styles from './RunNodeCard.module.css'

export function RunNodeCard({ run }: { run: AgentRun }) {
  return (
    <div className={styles.card}>
      <header className={styles.head}>
        <span className={styles.node}>{nodeLabel(run.node)}</span>
        {run.degraded && <span className={`badge badge-warning`}>降级</span>}
        {run.retry_count > 0 && (
          <span className={`badge badge-minor`}>重试 ×{run.retry_count}</span>
        )}
        <span className={styles.model}>{run.model_id ?? '—'}</span>
      </header>

      <dl className={styles.meta}>
        <div className={styles.metaItem}>
          <dt>入 token</dt>
          <dd>{run.input_tokens}</dd>
        </div>
        <div className={styles.metaItem}>
          <dt>出 token</dt>
          <dd>{run.output_tokens}</dd>
        </div>
        <div className={styles.metaItem}>
          <dt>缓存</dt>
          <dd>{run.cache_hit ? '命中' : '未命中'}</dd>
        </div>
        <div className={styles.metaItem}>
          <dt>耗时</dt>
          <dd>{run.duration_ms} ms</dd>
        </div>
        <div className={styles.metaItem}>
          <dt>估算成本</dt>
          <dd>¥{run.cost_est.toFixed(4)}</dd>
        </div>
      </dl>

      {run.detail?.audit_verdict && <div>
        <strong>{run.detail.audit_verdict.verdict} · {verdictLabel(run.detail.audit_verdict.verdict)}</strong>
        {run.detail.audit_verdict.reasons?.map((reason, i) => <p key={i}>{reason}</p>)}
      </div>}
      {run.detail?.route && <p>实际路由：{({persist: '进入落库检查', revise: '修订正文并复审', replan_chapter: '重新规划本章', replan_batch: '重新规划批次', needs_review: '暂停，等待人工评审', fail: '失败停止'} as Record<string,string>)[run.detail.route] ?? run.detail.route} · 修订 {run.detail.revision_count ?? 0} 次 · 重规划 {run.detail.replan_count ?? 0} 次</p>}
      {run.error && <p className={styles.error}>错误：{run.error}</p>}
    </div>
  )
}
