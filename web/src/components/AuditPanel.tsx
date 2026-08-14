// 校验报告侧栏：从快照 runs 的 audit 行取 detail.audit_verdict → verdict + findings（severity 分级 + evidence 跳章）。
import { severityLabel, severityTone, verdictLabel, verdictTone } from '../lib/labels'
import type { AgentRun, AuditVerdict, FindingSeverity } from '../types'
import { StatusBadge } from './StatusBadge'
import styles from './AuditPanel.module.css'

const SEVERITY_ORDER: FindingSeverity[] = ['critical', 'major', 'minor', 'hint']

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
  const findings = [...verdict.findings].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
  )

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

      {findings.length === 0 ? (
        <p className="empty">未发现冲突。</p>
      ) : (
        <ul className={styles.findings}>
          {findings.map((f) => (
            <li key={f.conflict_key} className={styles.finding}>
              <div className={styles.findingHead}>
                <StatusBadge tone={severityTone(f.severity)}>
                  {severityLabel(f.severity)}
                </StatusBadge>
                <span className={styles.findingType}>{f.conflict_type}</span>
              </div>
              <p className={styles.findingSrc}>{f.source}</p>
              {f.evidence.map((ev, i) => (
                <blockquote key={i} className={styles.evidence}>
                  <button
                    type="button"
                    className={styles.chapter}
                    onClick={() => onNavigateChapter(ev.chapter)}
                  >
                    第 {ev.chapter} 章 →
                  </button>
                  <span className={styles.quote}>{ev.quote}</span>
                </blockquote>
              ))}
              {f.suggestion && <p className={styles.suggestion}>建议：{f.suggestion}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
