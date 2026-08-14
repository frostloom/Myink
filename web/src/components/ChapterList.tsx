// 次级导航：章节序/标题/状态，点选加载编辑器。
import { chapterStatusLabel, chapterStatusTone } from '../lib/labels'
import type { ChapterMeta } from '../types'
import { StatusBadge } from './StatusBadge'
import styles from './ChapterList.module.css'

interface Props {
  chapters: ChapterMeta[]
  selectedCid: string | null
  onSelect: (cid: string) => void
}

export function ChapterList({ chapters, selectedCid, onSelect }: Props) {
  if (chapters.length === 0) {
    return <div className="empty">还没有章节。在右侧发起首次生成。</div>
  }
  return (
    <div className={styles.list}>
      {chapters.map((c) => (
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
          <StatusBadge tone={chapterStatusTone(c.status)}>
            {chapterStatusLabel(c.status)}
          </StatusBadge>
        </button>
      ))}
    </div>
  )
}
