// 当前章节的独立审核报告。完整展示每轮结论；流程耗时和费用留在章节流转面板。
import { useEffect, useRef, useState } from 'react'
import { verdictLabel, verdictTone } from '../lib/labels'
import { groupFlowAttempts } from '../lib/taskFlow'
import type { AgentRun, AuditVerdict } from '../types'
import { FindingsList } from './FindingsList'
import { StatusBadge } from './StatusBadge'
import styles from './AuditPanel.module.css'

interface Props {
  runs: AgentRun[]
  onNavigateChapter: (seq: number) => void
}

export function AuditPanel({ runs, onNavigateChapter }: Props) {
  const attempts = groupFlowAttempts(runs)
  const reports = attempts.flatMap((attemptRuns, attemptIndex) => {
    let roundIndex = 0
    return attemptRuns.flatMap((run) => {
      const verdict = run.node === 'audit' ? run.detail?.audit_verdict : null
      if (!verdict) return []
      const report = { verdict, attemptIndex, roundIndex }
      roundIndex += 1
      return [report]
    })
  })
  const latest = reports.at(-1)?.verdict ?? null
  const latestVerdict = latest?.verdict
  const [open, setOpen] = useState(reports.length > 0)
  const hasShownReport = useRef(reports.length > 0)

  useEffect(() => {
    // 页面刚进入时 runs 异步恢复；首次拿到审核记录自动展开，之后尊重用户折叠操作。
    if (latestVerdict && !hasShownReport.current) {
      hasShownReport.current = true
      setOpen(true)
    }
  }, [latestVerdict])

  return (
    <section className={`panel ${styles.panel}`} aria-label="章节审核报告">
      <header className={styles.head}>
        <button type="button" className={styles.toggle} onClick={() => setOpen((value) => !value)} aria-expanded={open}>
          <span className={styles.title}>{latest && latest.verdict !== 'pass' ? '未通过报告' : '审核报告'}</span>
          <span className={styles.headerMeta}>
            {latest && <StatusBadge tone={verdictTone(latest.verdict)}>{verdictLabel(latest.verdict)}</StatusBadge>}
            {latest && latest.findings.length > 0 && <span className={styles.count}>{latest.findings.length} 项</span>}
            {attempts.length > 1 && <span className={styles.rounds}>{attempts.length} 次</span>}
            {reports.length > 0 && <span className={styles.rounds}>{reports.length} 份</span>}
            <span className={styles.caret}>{open ? '▾' : '▸'}</span>
          </span>
        </button>
      </header>

      {open && (
        <div className={styles.body}>
          {reports.length > 0 ? (
            <div className={styles.reportList}>
              {reports.map((report, index) => {
                const reportLabel = attempts.length > 1
                  ? `第 ${report.attemptIndex + 1} 次生成 · 第 ${report.roundIndex + 1} 轮审核`
                  : `第 ${report.roundIndex + 1} 轮审核`
                return (
                <section key={`${report.attemptIndex}-${report.roundIndex}`} className={styles.round} aria-label={reportLabel}>
                  <div className={styles.roundHead}>
                    <span>{reportLabel}</span>
                    <small>{index === reports.length - 1 ? '最新' : '历史'}</small>
                  </div>
                  <VerdictReport verdict={report.verdict} onNavigateChapter={onNavigateChapter} />
                </section>
                )
              })}
            </div>
          ) : <p className="empty">本章还没有审核报告。</p>}
        </div>
      )}
    </section>
  )
}

function VerdictReport({ verdict, onNavigateChapter }: { verdict: AuditVerdict; onNavigateChapter: (seq: number) => void }) {
  return (
    <div className={styles.report}>
      <div className={styles.summary}>
        <div>
          <span className={styles.eyebrow}>最终结论</span>
          <strong>{verdictLabel(verdict.verdict)}</strong>
        </div>
        <span className={styles.confidence}>置信 {Math.round(verdict.confidence * 100)}%</span>
      </div>
      {verdict.replan_target && <p className={styles.target}>重规划范围：{verdict.replan_target === 'chapter' ? '本章' : '当前批次'}</p>}
      {verdict.reasons.length > 0 && (
        <div className={styles.reasonBlock}>
          <span className={styles.eyebrow}>{verdict.verdict === 'pass' ? '通过依据' : '未通过原因'}</span>
          <ul className={styles.reasons}>
            {verdict.reasons.map((reason, index) => <li key={index}>{reason}</li>)}
          </ul>
        </div>
      )}
      <FindingsList findings={verdict.findings} onNavigateChapter={onNavigateChapter} />
    </div>
  )
}
