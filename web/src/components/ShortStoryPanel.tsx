// 短篇审稿报告。短篇没有全局审计也没有单章审核，审稿是整篇唯一的出口，
// 所以这里只读那条 short_review 的运行记录：结论、审稿意见、降级说明、空章、字数观测。
import type { ReactNode } from 'react'
import { severityLabel, severityTone } from '../lib/labels'
import type { AgentRun, Finding, ShortReview } from '../types'
import { StatusBadge } from './StatusBadge'
import styles from './ShortStoryPanel.module.css'

interface Props {
  /** 短篇任务的全部流转记录（右栏不按章过滤——整篇任务不属于任何一章） */
  runs: AgentRun[]
}

interface ShortReport {
  review: ShortReview
  /** 补写之后仍为空的章号（正常为 []，非空就是这一篇缺了正文） */
  emptyChapters: number[]
  lengthFindings: Finding[]
  /** 审稿要求改稿且改稿真的落下来了 */
  revised: boolean
}

export function ShortStoryPanel({ runs }: Props) {
  const report = latestReport(runs)

  return (
    <section className={`panel ${styles.panel}`} aria-label="短篇审稿报告">
      <header className={styles.head}>
        <span className={styles.title}>短篇审稿</span>
        {report && (
          <span className={styles.headerMeta}>
            <StatusBadge tone={report.review.verdict === 'pass' ? 'success' : 'warning'}>
              {verdictText(report)}
            </StatusBadge>
            {report.lengthFindings.length > 0 && (
              <span className={styles.count}>{report.lengthFindings.length} 章字数偏离</span>
            )}
          </span>
        )}
      </header>

      <div className={styles.body}>
        {report === null ? <p className="empty">本篇还没有审稿记录。</p> : (
          <>
            {report.review.warning && (
              <p className={styles.warning} role="status">{report.review.warning}</p>
            )}
            <Section title="审稿意见">
              {report.review.issues.length > 0 ? (
                <ul className={styles.list}>
                  {report.review.issues.map((issue, index) => <li key={index}>{issue}</li>)}
                </ul>
              ) : <p className="empty">未发现需要改稿的问题。</p>}
            </Section>
            {report.review.suggestions.length > 0 && (
              <Section title="修改建议">
                <ul className={styles.list}>
                  {report.review.suggestions.map((suggestion, index) => <li key={index}>{suggestion}</li>)}
                </ul>
              </Section>
            )}
            {report.emptyChapters.length > 0 && (
              <p className={styles.warning}>第 {report.emptyChapters.join('、')} 章没有正文</p>
            )}
            {report.lengthFindings.length > 0 && (
              <Section title="字数观测（仅供参考，不拦稿）">
                <ul className={styles.list}>
                  {report.lengthFindings.map((finding) => (
                    <li key={finding.conflict_key} className={styles.lengthRow}>
                      <StatusBadge tone={severityTone(finding.severity)}>
                        {severityLabel(finding.severity)}
                      </StatusBadge>
                      <span>{finding.evidence.map((item) => item.quote).join('；')}</span>
                    </li>
                  ))}
                </ul>
              </Section>
            )}
          </>
        )}
      </div>
    </section>
  )
}

/** 最新一条审稿记录（重跑同一任务时以最后一条为准）。 */
function latestReport(runs: AgentRun[]): ShortReport | null {
  for (let i = runs.length - 1; i >= 0; i -= 1) {
    const detail = runs[i].node === 'short_review' ? runs[i].detail : null
    const review = detail?.short_review
    if (!review) continue
    return {
      review,
      emptyChapters: detail?.empty_chapters ?? [],
      lengthFindings: detail?.length_findings ?? [],
      revised: detail?.revised === true,
    }
  }
  return null
}

function verdictText(report: ShortReport): string {
  if (report.review.verdict === 'pass') return '通过'
  return report.revised ? '已改稿' : '审稿要求改稿'
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.section}>
      <span className={styles.eyebrow}>{title}</span>
      {children}
    </section>
  )
}