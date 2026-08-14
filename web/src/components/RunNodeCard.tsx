// 执行节点卡：agent_runs 单行快照（node 中文标签 + 模型 + token + 缓存 + 耗时 + 估算成本 + 重试/降级/错误）。
import { nodeLabel } from '../lib/labels'
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

      {run.error && <p className={styles.error}>错误：{run.error}</p>}
    </div>
  )
}
