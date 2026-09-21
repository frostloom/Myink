import { useEffect, useRef, useState } from 'react'
import type { ArtifactState } from '../hooks/useTaskEvents'
import styles from './StreamingChapterView.module.css'

interface Props {
  chapterSeq: number
  artifact: ArtifactState | null
  summary?: string | null
}

function cleanDraft(text: string): string {
  const leading = text.trimStart()
  const marker = '=== CONTENT ==='
  if (leading.length < marker.length && marker.startsWith(leading.toUpperCase())) return ''
  return text.replace(/^\s*===\s*CONTENT\s*===\s*/i, '')
}

export function StreamingChapterView({ chapterSeq, artifact, summary }: Props) {
  const source = cleanDraft(artifact?.content ?? '')
  const waiting = artifact === null
  const label = waiting ? '连接 Writer' : artifact?.failed ? '生成重试中' : artifact.complete ? '写作完成' : '实时写作'
  const paperRef = useRef<HTMLDivElement>(null)
  const shouldFollowRef = useRef(true)
  const [following, setFollowing] = useState(true)

  useEffect(() => {
    shouldFollowRef.current = true
    setFollowing(true)
  }, [chapterSeq, artifact?.artifactId])

  useEffect(() => {
    const paper = paperRef.current
    if (paper && shouldFollowRef.current) paper.scrollTop = paper.scrollHeight
  }, [source])

  function handleScroll() {
    const paper = paperRef.current
    if (!paper) return
    const isNearBottom = paper.scrollHeight - paper.scrollTop - paper.clientHeight <= 80
    shouldFollowRef.current = isNearBottom
    setFollowing(isNearBottom)
  }

  function followLatest() {
    const paper = paperRef.current
    shouldFollowRef.current = true
    setFollowing(true)
    if (paper) paper.scrollTop = paper.scrollHeight
  }

  return (
    <section className={styles.wrap} aria-label={`第 ${chapterSeq} 章生成正文`}>
      <header className={styles.head}>
        <div>
          <h2>第 {chapterSeq} 章</h2>
          <p>{summary?.trim() || (waiting
            ? 'Plan 已确认，正在连接 Writer。'
            : '正文生成中；本章摘要将在内容检查后显示。')}</p>
        </div>
        <span className={styles.status}>{label}<i aria-hidden="true" /></span>
      </header>
      <div
        ref={paperRef}
        className={styles.paper}
        role="region"
        aria-label="正文实时预览"
        aria-live="polite"
        onScroll={handleScroll}
      >
        {source ? <pre>{source}{!artifact?.complete && <span className={styles.cursor} aria-hidden="true" />}</pre> : (
          <div className={styles.waiting}>{waiting ? 'Writer 正在连接模型…' : '模型已开始响应，正在等待第一段正文…'}</div>
        )}
        {!following && !artifact?.complete && (
          <button type="button" className={styles.followButton} onClick={followLatest}>
            回到最新
          </button>
        )}
      </div>
      <footer>{Array.from(source).length.toLocaleString()} 字</footer>
    </section>
  )
}
