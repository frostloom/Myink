// 校验报告侧栏：从快照 runs 的 audit 行取 detail.audit_verdict → verdict + findings。
// finding 明细渲染复用 FindingsList（与全局审计报告视图同构，§8.6）。
import { verdictLabel, verdictTone } from '../lib/labels'
import type { AgentRun, AuditVerdict } from '../types'
import { FindingsList } from './FindingsList'
import { StatusBadge } from './StatusBadge'
import styles from './AuditPanel.module.css'

interface Props {
  runs: AgentRun[]
  onNavigateChapter: (seq: number) => void
}

export function AuditPanel({ runs, onNavigateChapter }: Props) {
  const verdicts = runs
    .filter((r) => r.node === 'audit' && r.detail?.audit_verdict)
    .map((r) => r.detail!.audit_verdict!)

  if (verdicts.length === 0) {
    return (
      <div className={styles.panel}>
        <h3 className={styles.heading}>校验报告</h3>
        <p className="empty">暂无校验报告。</p>
      </div>
    )
  }

  return (
    <div className={styles.panel}>
      <h3 className={styles.heading}>校验报告</h3>

      {verdicts.map((v, i) => (
        <VerdictCard key={i} verdict={v} onNavigateChapter={onNavigateChapter} />
      ))}
    </div>
  )
}

function VerdictCard({
  verdict,
  onNavigateChapter,
}: {
  verdict: AuditVerdict
  onNavigateChapter: (seq: number) => void
}) {
  return (
    <div className={styles.verdict}>
      <header className={styles.verdictHead}>
        <StatusBadge tone={verdictTone(verdict.verdict)}>
          {verdictLabel(verdict.verdict)}
        </StatusBadge>
        {verdict.replan_target && (
          <span className={styles.replan}>重规划目标：{verdict.replan_target}</span>
        )}
        <span className={styles.confidence}>置信 {Math.round(verdict.confidence * 100)}%</span>
      </header>

      {verdict.reasons.length > 0 && (
        <ul className={styles.reasons}>
          {verdict.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}

      <FindingsList findings={verdict.findings} onNavigateChapter={onNavigateChapter} />
    </div>
  )
}
