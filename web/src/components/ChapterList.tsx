// 次级导航：章节序/标题/状态，点选加载编辑器。
import { chapterStatusLabel, chapterStatusTone } from '../lib/labels'
import type { ChapterMeta } from '../types'
import { StatusBadge } from './StatusBadge'
import styles from './ChapterList.module.css'

interface Props {
  chapters: ChapterMeta[]
  selectedCid: string | null
  onSelect: (cid: string) => void
  /** 章序 → 待确认候选数（候选池面板联动：点进有候选的章先处理再续跑） */
  pendingByChapter?: Map<number, number>
}

export function ChapterList({ chapters, selectedCid, onSelect, pendingByChapter }: Props) {
  if (chapters.length === 0) {
    return <div className="empty">还没有章节。在右侧发起首次生成。</div>
  }
  return (
    <div className={styles.list}>
      {chapters.map((c) => {
        const pending = pendingByChapter?.get(c.chapter_seq) ?? 0
        return (
          <button
            key={c.id}
            type="button"
            className={
              selectedCid === c.id ? `${styles.item} ${styles.active}` : styles.item
            }
            onClick={() => onSelect(c.id)}
          >
            <span className={styles.seq}>第 {c.chapter_seq} 章</span>
            {c.title && <span className={styles.title}>{c.title}</span>}
            {c.word_count != null && (
              <span className={styles.words} title="正文字符数（含标点）">
                {c.word_count.toLocaleString()} 字
              </span>
            )}
            {pending > 0 && (
              <span className={`badge badge-warning ${styles.pending}`} title="有待确认候选">
                {pending} 待确认
              </span>
            )}
            <StatusBadge tone={chapterStatusTone(c.status)}>
              {chapterStatusLabel(c.status)}
            </StatusBadge>
          </button>
        )
      })}
    </div>
  )
}
