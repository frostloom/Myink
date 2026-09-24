/** 短篇建书：与助手聊清楚 → 右边那张卡可以随手改 → 「确认，开写」。
 *
 * 与长篇向导的分工：长篇要先填设定、再确认大纲，两步都不能省；短篇这里聊完那一刻
 * 方案卡就是设定，后端在确认时一次把逐章方案落库（生成需要它）。
 */
import { useCallback, useEffect, useRef, useState,
         type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import { shortCreationApi, type ShortCreationCard, type ShortCreationPayload }
  from '../lib/shortCreationApi'
import { styleLibraryApi, type StyleLibraryItem } from '../lib/styleLibraryApi'
import type { Project } from '../types'
import styles from './ShortCreationPage.module.css'

const FIELDS: Array<[keyof ShortCreationCard, string]> = [
  ['working_title', '暂定名'],
  ['genre', '题材'],
  ['direction', '方向'],
  ['protagonist_pressure', '主角压力'],
  ['conflict_core', '核心冲突'],
  ['emotional_payoff', '情绪回报'],
  ['plot_sketch', '大致情节'],
]

const REQUIRED_TEXT: Array<keyof ShortCreationCard> = [
  'working_title', 'genre', 'direction', 'protagonist_pressure',
  'conflict_core', 'emotional_payoff', 'plot_sketch',
]

// 短篇形态参数（docs/SHORT-FORM.md §5）：与后端 src/myink/short/form.py 的
// resolve_short_lengths 同规——先各自夹进声明区间，再看全篇总量把每章字数压下来。
const SHORT_CHAPTER_MIN = 1
const SHORT_CHAPTER_MAX = 10
const SHORT_CHARS_MIN = 1000
const SHORT_CHARS_MAX = 8000
const SHORT_TOTAL_MAX = 20000

/** 卡上算一遍后端会怎么归一（只在确认前提示，不代替后端）。先截断小数，再夹进区间，避免除零。 */
function resolveShortLengths(chapterCount: number, charsPerChapter: number): {
  chars: number
  compressed: boolean
} {
  // 卡片字段后端是 int() 截断（creation.py 的 _known），这里同规先截再夹。
  const chapters = Math.min(Math.max(Math.trunc(chapterCount), SHORT_CHAPTER_MIN), SHORT_CHAPTER_MAX)
  const chars = Math.min(Math.max(Math.trunc(charsPerChapter), SHORT_CHARS_MIN), SHORT_CHARS_MAX)
  if (chapters * chars > SHORT_TOTAL_MAX) {
    return {
      chars: Math.max(SHORT_CHARS_MIN, Math.floor(SHORT_TOTAL_MAX / chapters)),
      compressed: true,
    }
  }
  return { chars, compressed: false }
}

function isReady(card: Partial<ShortCreationCard>): boolean {
  return REQUIRED_TEXT.every((field) => String(card[field] ?? '').trim() !== '')
}

export default function ShortCreationPage() {
  const { session, logout } = useAuth()
  const guest = useGuest()
  const token = session?.token ?? ''
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [data, setData] = useState<ShortCreationPayload | null>(null)
  const [card, setCard] = useState<Partial<ShortCreationCard>>({})
  const [styleItemId, setStyleItemId] = useState('')
  const [styleItems, setStyleItems] = useState<StyleLibraryItem[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cardOpen, setCardOpen] = useState(false)
  const stream = useRef<HTMLDivElement>(null)

  const apply = useCallback((next: ShortCreationPayload) => {
    setData(next)
    setCard(next.session.card ?? {})
    setStyleItemId(next.session.style_item_id ?? '')
  }, [])

  const reload = useCallback(async () => {
    try {
      apply(await shortCreationApi.get(token))
    } catch (reason) {
      setError(formatApiError(reason, '打不开建书对话，请稍后重试'))
    }
  }, [apply, token])

  useEffect(() => { void reload() }, [reload])
  useEffect(() => {
    styleLibraryApi.list(token).then((out) => setStyleItems(out.items)).catch(() => setStyleItems([]))
  }, [token])
  // rail 的书目：与别的页面同一个来源，拿不到就当空列表（rail 的分区链接照样在）。
  useEffect(() => {
    if (guest) { setProjects([]); return }
    api.listProjects().then(setProjects).catch(() => setProjects([]))
  }, [guest])
  useEffect(() => {
    if (stream.current) stream.current.scrollTop = stream.current.scrollHeight
  }, [data])
  // 助手把卡聊回去（或「重新开始」清空）时，敞开着的卡要跟着收起来。
  useEffect(() => { if (!data?.ready) setCardOpen(false) }, [data?.ready])

  const run = async (action: () => Promise<void>, fallback: string) => {
    setError(null)
    setBusy(true)
    try {
      await action()
    } catch (reason) {
      setError(formatApiError(reason, fallback))
    } finally {
      setBusy(false)
    }
  }

  const sendDraft = () => {
    const content = draft.trim()
    if (!content || busy) return
    void run(async () => {
      apply(await shortCreationApi.send(token, content, card as Record<string, unknown>))
      setDraft('')
    }, '这句话没发出去，请重试')
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    sendDraft()
  }

  // 回车发送（Shift+回车换行）。输入法组合态里的回车是「选词上屏」，不能当发送。
  const onKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) return
    if (event.nativeEvent.isComposing) return
    event.preventDefault()
    sendDraft()
  }

  // 已确认过的会话不再是可写的（类型里 status 只有 active / committed 两种）。
  const committed = data !== null && data.session.status !== 'active'

  const confirm = () => {
    // 已确认过的会话只会在后端 409；卡填满了也不给这个按钮真的发出去。
    if (committed) return
    void run(async () => {
      const out = await shortCreationApi.commit(token, card as Record<string, unknown>, styleItemId || null)
      // commit 只落书。入队这一下失败也不能把刚建的书丢了——照样进工作台，
      // 由状态带上的重试入口接手（beginShortWriting 为假即不自动开写）。
      let enqueueFailed = false
      try {
        await api.generateShort(out.project_id)
      } catch {
        enqueueFailed = true
      }
      navigate(`/projects/${out.project_id}`, {
        state: { beginShortWriting: !enqueueFailed, planWarning: out.plan_warning },
      })
    }, '确认失败，请重试')
  }

  const restart = () => void run(async () => {
    await shortCreationApi.reset(token)
    await reload()
  }, '重置失败，请重试')

  if (!data) {
    return (
      <div className={styles.page}>
        <ProjectRail projects={projects} onLogout={logout} />
        <div className={styles.wrap}><div className="empty">{error ?? '正在打开建书对话…'}</div></div>
      </div>
    )
  }
  const cardReady = !committed && isReady(card)
  const lengths = resolveShortLengths(card.chapter_count ?? 5, card.chars_per_chapter ?? 4000)

  return (
    <div className={styles.page}>
      <ProjectRail projects={projects} onLogout={logout} />
      <div className={`${styles.wrap} ${cardOpen && !committed ? '' : styles.single}`}>
      <section className={styles.thread} aria-label="建书对话">
        <header className="row-between">
          <h2>新建短篇</h2>
          <button type="button" className="btn btn-quiet" onClick={restart} disabled={busy}>重新开始</button>
        </header>
        <div className={styles.stream} ref={stream}>
          {data.messages.map((message) => (
            <div key={message.id}
                 className={[styles.turn, message.role === 'user' ? styles.mine : styles.theirs,
                             message.error ? styles.failed : ''].join(' ')}>
              <p>{message.content}</p>
              {message.error && <small role="alert">这一轮没成功：{message.error}</small>}
            </div>
          ))}
          {/* 三段式：先只聊；服务端说聊齐备了，才冒出这条路；点开才见方案卡。 */}
          {data.ready && !committed && !cardOpen && (
            <button type="button" className={`btn btn-primary ${styles.option}`}
                    onClick={() => setCardOpen(true)}>
              开始建书
            </button>
          )}
        </div>
        {error && <div className="banner banner-error" role="alert"><span>{error}</span></div>}
        {committed && (
          <div className="banner banner-warning" role="status">
            这段建书对话已经开写过了，确认按钮不再生效；要写新的一篇，点右上角的「重新开始」。
            {data.session.book_id && (
              <>{' '}刚开写的那本在<Link to={`/projects/${data.session.book_id}`}>这里</Link>。</>
            )}
          </div>
        )}
        <form className={styles.composer} onSubmit={submit}>
          <label>
            <textarea aria-label="对助手说" className="input" value={draft} maxLength={4000}
                      placeholder="说说你想写的故事，或者说「就这样，开写吧」"
                      onChange={(event) => setDraft(event.target.value)} onKeyDown={onKeyDown} />
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy || draft.trim() === ''}>发送</button>
        </form>
      </section>

      {cardOpen && !committed && (
        <aside className={`panel ${styles.card}`} aria-label="方案卡">
          <h3>方案卡（随手改）</h3>
          {FIELDS.map(([key, label]) => (
            <label key={key}>
              <span>{label}{REQUIRED_TEXT.includes(key) ? '（必填）' : ''}</span>
              <textarea className="input" rows={key === 'plot_sketch' ? 4 : 2}
                        aria-label={label} value={String(card[key] ?? '')} maxLength={4000}
                        onChange={(event) => setCard({ ...card, [key]: event.target.value })} />
            </label>
          ))}
          <label>
            <span>章数（1–10）</span>
            <input className="input" type="number" min={1} max={10} aria-label="章数"
                   value={card.chapter_count ?? 5}
                   onChange={(event) => setCard({ ...card, chapter_count: Number(event.target.value) })} />
          </label>
          <label>
            <span>每章字数（1000–8000）</span>
            <input className="input" type="number" min={1000} max={8000} aria-label="每章字数"
                   value={card.chars_per_chapter ?? 4000}
                   onChange={(event) => setCard({ ...card, chars_per_chapter: Number(event.target.value) })} />
          </label>
          {lengths.compressed && (
            <div className="banner banner-warning">
              每章字数已按全篇 {SHORT_TOTAL_MAX} 字上限归一为每章 {lengths.chars} 字，生成时按这个数走。
            </div>
          )}
          <label>
            <span>文风（建书后不可改）</span>
            <select className="input" aria-label="文风" value={styleItemId}
                    onChange={(event) => setStyleItemId(event.target.value)}>
              <option value="">不指定</option>
              {styleItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}{item.builtin ? '（内置）' : '（我的）'}
                </option>
              ))}
            </select>
          </label>
          <small>文风在确认时定下来，之后没有换的入口。库里没有想要的？</small>
          <Link to="/styles">去文风库添加</Link>
          <button type="button" className="btn btn-primary" disabled={!cardReady || busy} onClick={confirm}>
            确认，开写
          </button>
          {!cardReady && <small>还差几个必填项——也可以直接告诉助手，它会补上。</small>}
        </aside>
      )}
      </div>
    </div>
  )
}
