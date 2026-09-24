/** 作品详情：章节元数据、受限上下文快照，以及章内下钻的全文。
 *
 * 样式取自 AdminPage.module.css，理由同 shared.tsx 的头顶注释。
 */
import { useCallback, useMemo, useState } from 'react'
import { useOutletContext, useParams } from 'react-router-dom'
import { adminApi, type AdminChapterDetail, type AdminContext, type AdminContextCollection, type AdminProject } from '../../lib/adminApi'
import { chapterStatusLabel, creationStatusLabel } from '../../lib/labels'
import { asRecord } from '../../lib/snapshotView'
import {
  type AdminOutletContext,
  CapturedView,
  DetailPage,
  formatDate,
  LoadState,
  PAGE_SIZE,
  Pagination,
  RecordFields,
  RefreshButton,
  useResource,
  ValueText,
} from './shared'
import styles from '../AdminPage.module.css'

function ChapterDetailView({ token, projectId, chapterId, onForbidden }: {
  token: string
  projectId: string
  chapterId: string
  onForbidden: () => void
}) {
  const load = useCallback(
    (signal: AbortSignal) => adminApi.getChapter(token, projectId, chapterId, signal),
    [chapterId, projectId, token],
  )
  const resource = useResource<AdminChapterDetail>(load, onForbidden)
  const value = resource.data
  return (
    <LoadState {...resource} empty={!value}>
      {value && <article className={`panel ${styles.detail}`}>
        <h3>{value.title ?? `第 ${value.chapter_seq} 章`} · v{value.version}</h3>
        <h4>摘要</h4>
        {typeof value.summary === 'string' && value.summary !== ''
          ? <p className={styles.text}>{value.summary}</p>
          : <RecordFields value={value.summary} />}
        <h4>全文</h4>
        {value.content
          ? <p className={styles.text}>{value.content}</p>
          : <p className={styles.muted}>无正文</p>}
      </article>}
    </LoadState>
  )
}

/** 台账条目：键名翻中文，参与人物从 id 换成人名，嵌套结构再降一级。 */
function ContextEntries({ collection, nameOf }: {
  collection: AdminContextCollection
  nameOf: (id: string) => string
}) {
  if (collection.items.length === 0) return <p className={styles.muted}>暂无记录</p>
  return (
    <ul className={styles.plainList}>{collection.items.map((item, index) => {
      const record = asRecord(item.data)
      if (!record) return <li key={index}><ValueText value={item.data} /></li>
      const resolved: Record<string, unknown> = { ...record }
      if (Array.isArray(resolved.participants)) {
        resolved.participants = resolved.participants
          .map((entry) => (typeof entry === 'string' ? nameOf(entry) : entry))
      }
      return <li key={index}><RecordFields value={resolved} skip={['id']} /></li>
    })}</ul>
  )
}

function ContextView({ value }: { value: AdminContext }) {
  const nameOf = useMemo(() => {
    const names = new Map<string, string>()
    for (const item of value.characters.items) {
      const record = asRecord(item.data)
      if (record && typeof record.id === 'string' && typeof record.name === 'string') {
        names.set(record.id, record.name)
      }
    }
    return (id: string) => names.get(id) ?? `${id.slice(0, 8)}…`
  }, [value])
  const collections: Array<[string, AdminContextCollection]> = [
    ['大纲', value.outlines], ['事件', value.events], ['事实', value.facts],
    ['人物', value.characters], ['伏笔', value.foreshadows], ['故事线', value.threads],
  ]
  return (
    <div className={styles.context}>
      <CapturedView value={value.settings} label="作品设置" />
      {collections.map(([label, collection]) => <section className={styles.capture} key={label}>
        <h4>{label}（显示 {collection.items.length} / 共 {collection.total}）</h4>
        {collection.truncated && <div className={styles.flags}>
          <span className="badge badge-warning">集合已截断</span>
        </div>}
        <ContextEntries collection={collection} nameOf={nameOf} />
      </section>)}
    </div>
  )
}

export function ProjectDetailView({ token, project, onForbidden }: {
  token: string
  project: AdminProject
  onForbidden: () => void
}) {
  const [offset, setOffset] = useState(0)
  const [chapterId, setChapterId] = useState<string | null>(null)
  const loadChapters = useCallback(
    (signal: AbortSignal) => adminApi.listChapters(
      token, project.id, { limit: PAGE_SIZE, offset }, signal,
    ),
    [offset, project.id, token],
  )
  const loadContext = useCallback(
    (signal: AbortSignal) => adminApi.getProjectContext(token, project.id, PAGE_SIZE, signal),
    [project.id, token],
  )
  const chapters = useResource(loadChapters, onForbidden)
  const context = useResource(loadContext, onForbidden)
  return (
    <div className={styles.drilldown}>
      <div className={styles.detailHead}>
        <div><h3>《{project.title}》</h3><p>{project.username} · {project.genre} · {creationStatusLabel(project.creation_status)}</p></div>
        <div><RefreshButton onClick={chapters.retry} /> <button type="button" className="btn btn-secondary" onClick={context.retry}>刷新设定</button></div>
      </div>
      <div className={styles.split}>
        <section className={`panel ${styles.detail}`}>
          <h3>章节元数据</h3>
          <LoadState {...chapters} empty={chapters.data?.items.length === 0}>
            {chapters.data && <>
              <ul className={styles.list}>{chapters.data.items.map((chapter) => <li key={chapter.id}>
                <div><strong>{chapter.title ?? `第 ${chapter.chapter_seq} 章`}</strong><small>{chapterStatusLabel(chapter.status)} · {chapter.word_count.toLocaleString()} 字 · {formatDate(chapter.updated_at)}</small></div>
                <button type="button" className="btn btn-quiet" aria-label={`查看${chapter.title ?? `第 ${chapter.chapter_seq} 章`}全文`} onClick={() => setChapterId(chapter.id)}>全文</button>
              </li>)}</ul>
              <Pagination total={chapters.data.total} offset={offset} onChange={(next) => { setChapterId(null); setOffset(next) }} />
            </>}
          </LoadState>
        </section>
        <section className={`panel ${styles.detail}`}>
          <h3>受限上下文快照</h3>
          <LoadState {...context} empty={!context.data}>{context.data && <ContextView value={context.data} />}</LoadState>
        </section>
      </div>
      {chapterId && <ChapterDetailView key={chapterId} token={token} projectId={project.id} chapterId={chapterId} onForbidden={onForbidden} />}
    </div>
  )
}

export function ProjectDetailPage() {
  const { token, onForbidden } = useOutletContext<AdminOutletContext>()
  const { projectId = '' } = useParams()
  const load = useCallback(
    (signal: AbortSignal) => adminApi.getProject(token, projectId, signal),
    [projectId, token],
  )
  const resource = useResource<AdminProject>(load, onForbidden)
  return (
    <DetailPage heading="作品详情" backTab="projects">
      <LoadState {...resource} empty={!resource.data}>
        {resource.data && <ProjectDetailView token={token} project={resource.data} onForbidden={onForbidden} />}
      </LoadState>
    </DetailPage>
  )
}
