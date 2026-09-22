// 冲突 finding 列表（校验报告侧栏 + 全局审计报告视图共用）：severity 分级 + evidence 引文 + 跳章。
import { conflictTypeLabel, findingSourceLabel, severityLabel, severityTone } from '../lib/labels'
import type { Finding, FindingSeverity } from '../types'
import { StatusBadge } from './StatusBadge'
import styles from './FindingsList.module.css'

const SEVERITY_ORDER: FindingSeverity[] = ['critical', 'major', 'minor', 'hint']

interface Props {
  findings: Finding[]
  /** 缺省时引文章号纯展示（无跳转目标场景） */
  onNavigateChapter?: (seq: number) => void
}

export function FindingsList({ findings, onNavigateChapter }: Props) {
  const sorted = [...findings].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
  )
  if (sorted.length === 0) {
    return <p className="empty">未发现冲突。</p>
  }
  return (
    <ul className={styles.findings}>
      {sorted.map((f) => (
        <li key={f.conflict_key} className={styles.finding}>
          <div className={styles.findingHead}>
            <StatusBadge tone={severityTone(f.severity)}>
              {severityLabel(f.severity)}
            </StatusBadge>
            <span className={styles.findingType}>{conflictTypeLabel(f.conflict_type)}</span>
            <span className={styles.findingType}>{f.scope === 'local' ? '局部' : f.scope === 'structural' ? '结构' : '范围未定'}</span>
          </div>
          <p className={styles.findingSrc}>{findingSourceLabel(f.source)}</p>
          {f.evidence.map((ev, i) => (
            <blockquote key={i} className={styles.evidence}>
              {onNavigateChapter ? (
                <button
                  type="button"
                  className={styles.chapter}
                  onClick={() => onNavigateChapter(ev.chapter)}
                >
                  第 {ev.chapter} 章 →
                </button>
              ) : (
                <span className={styles.chapterText}>第 {ev.chapter} 章</span>
              )}
              <span className={styles.quote}>{ev.quote}</span>
            </blockquote>
          ))}
          {f.suggestion && <p className={styles.suggestion}>建议：{f.suggestion}</p>}
        </li>
      ))}
    </ul>
  )
}
