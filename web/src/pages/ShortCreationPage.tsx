/** 短篇建书：与助手聊清楚 → 方案卡弹出来随手改 → 「确认，开写」。
 *
 * 与长篇向导的分工：长篇要先填设定、再确认大纲，两步都不能省；短篇这里聊完那一刻
 * 方案卡就是设定，后端在确认时一次把逐章方案落库（生成需要它）。
 *
 * 版式：一列聊天，输入条钉在底部。方案卡是**悬浮模态**——它是「确认了就照这个写」的
 * 一次性决定，不是右栏那种随时能瞟一眼的常驻面板；同款弹窗见 components/GuestPromptDialog。
 */
import { useCallback, useEffect, useRef, useState,
         type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { api } from '../lib/api'
import { autoGrow } from '../lib/autoGrow'
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

/** 输入框自增长的上限（px）：再高就把聊天区挤没了。 */
const COMPOSER_MAX_HEIGHT = 200

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
  const [operation, setOperation] = useState<'talk' | 'plan' | 'reset' | null>(null)
  const busy = operation !== null
  const operationRef = useRef(false)
  const [error, setError] = useState<string | null>(null)
  const [cardOpen, setCardOpen] = useState(false)
  const stream = useRef<HTMLDivElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)
  const cardBody = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLElement>(null)
  const openerRef = useRef<HTMLButtonElement>(null)

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
  // 输入框随内容长高，到上限才内部滚动——不然写长句子只能在一个小格子里挪。
  useEffect(() => {
    if (composer.current) autoGrow(composer.current, COMPOSER_MAX_HEIGHT)
  }, [draft])

  // 卡里的字段同样随内容长高：整个弹窗只留 .dialogBody 那一条滚动条。
  // 字段框自己再滚，就成了「能滚的块里嵌一个能滚的框」。
  useEffect(() => {
    if (!cardBody.current) return
    for (const el of cardBody.current.querySelectorAll('textarea')) autoGrow(el)
  }, [cardOpen, card])

  // 焦点留在方案卡内，关闭后回到原入口，键盘用户可以接着聊。
  useEffect(() => {
    if (!cardOpen) return
    const opener = openerRef.current
    closeRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        setCardOpen(false)
      }
      if (event.key === 'Tab') {
        const controls = dialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled)',
        )
        if (!controls?.length) return
        const first = controls[0]
        const last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      opener?.focus()
    }
  }, [cardOpen])

  const run = async (kind: 'talk' | 'plan' | 'reset', action: () => Promise<void>, fallback: string) => {
    if (operationRef.current) return
    operationRef.current = true
    setError(null)
    setOperation(kind)
    try {
      await action()
    } catch (reason) {
      setError(formatApiError(reason, fallback))
    } finally {
      operationRef.current = false
      setOperation(null)
    }
  }

  const sendDraft = () => {
    const content = draft.trim()
    if (!content || busy || data?.session.status !== 'active') return
    void run('talk', async () => {
      apply(await shortCreationApi.send(token, content, card as Record<string, unknown>))
      setDraft((current) => current.trim() === content ? '' : current)
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
    void run('plan', async () => {
      const out = await shortCreationApi.commit(token, card as Record<string, unknown>, styleItemId || null)
      // commit 只落书，入队归工作台：那边有状态带，入队失败就地给重试入口。
      navigate(`/projects/${out.project_id}`, {
        state: { beginShortWriting: true, planWarning: out.plan_warning },
      })
    }, '确认失败，请重试')
  }

  const restart = () => void run('reset', async () => {
    await shortCreationApi.reset(token)
    setDraft('')
    await reload()
  }, '重置失败，请重试')

  if (!data) {
    return (
      <div className={styles.page}>
        <ProjectRail projects={projects} onLogout={logout} />
        <div className={styles.thread}><div className="empty">{error ?? '正在打开建书对话…'}</div></div>
      </div>
    )
  }
  const cardReady = !committed && isReady(card)
  const lengths = resolveShortLengths(card.chapter_count ?? 5, card.chars_per_chapter ?? 4000)
  // 错误只有一处可见：卡开着时进卡里（弹窗盖住了下面的 banner），否则留在对话上。
  const errorBanner = error !== null && <div className="banner banner-error" role="alert">{error}</div>

  return (
    <div className={styles.page}>
      <div className={styles.background} inert={cardOpen}>
      <ProjectRail projects={projects} onLogout={logout} />
      <main className={styles.main}>
        <div className={styles.thread}>
          <header className={styles.head}>
            <div>
              <h1>新建短篇</h1>
              <p className={styles.sub} aria-live="polite">
                {operation === 'plan' ? '正在规划章节…' : operation === 'reset' ? '正在准备新的对话…'
                  : committed ? '已开写' : data.ready ? '方案已备好 · 等你确认' : '构思中 · 先聊聊故事'}
              </p>
            </div>
            <button type="button" className="btn btn-quiet" onClick={restart} disabled={busy}>
              {operation === 'reset' ? '正在重置…' : '重新开始'}
            </button>
          </header>

          <div className={styles.stream} ref={stream} aria-label="建书对话">
            {data.messages.map((message) => (
              <div key={message.id}
                   className={[styles.turn, message.role === 'user' ? styles.mine : styles.theirs,
                               message.error ? styles.failed : ''].join(' ')}>
                <p>{message.content}</p>
                {message.error && <small role="alert">这一轮没成功：{message.error}</small>}
              </div>
            ))}
            {/* 三段式：先只聊；服务端说聊齐备了，才冒出这条路；点开才弹方案卡。
                卡开着时收起来——它被模态盖在底下，再点一次也做不了什么（Modal 里的东西
                就不该还能按）。关掉卡就回来。 */}
            {data.ready && !committed && (
              <section className={styles.proposal} hidden={cardOpen} aria-label="待确认方案">
                <div>
                  <small>待确认方案</small>
                  <h2>{card.working_title || '你的短篇'}</h2>
                  <p>{card.genre || '题材待定'} · {card.chapter_count ?? 5} 章 · 每章约 {lengths.chars} 字</p>
                </div>
                <button ref={openerRef} type="button" className={`btn btn-primary ${styles.option}`}
                        disabled={busy} onClick={() => { setError(null); setCardOpen(true) }}>
                  开始建书
                </button>
              </section>
            )}
          </div>

          {!cardOpen && errorBanner}
          {committed && (
            <div className="banner banner-warning" role="status">
              已开写。新故事请点「重新开始」。
              {data.session.book_id && (
                <>{' '}刚开写的那本在<Link to={`/projects/${data.session.book_id}`}>这里</Link>。</>
              )}
            </div>
          )}

          <form className={styles.composer} onSubmit={submit}>
            <label>
              <textarea ref={composer} rows={3} aria-label="对助手说" className="input" value={draft}
                        disabled={committed || operation === 'plan' || operation === 'reset'}
                        maxLength={4000} onChange={(event) => setDraft(event.target.value)}
                        onKeyDown={onKeyDown}
                        placeholder={committed ? '本次建书对话已结束' : '说说你想写的故事…'} />
            </label>
            <div className={styles.composerFoot}>
              <small className={styles.hint}>回车发送，Shift + 回车换行</small>
              <button type="submit" className="btn btn-primary" disabled={committed || busy || draft.trim() === ''}>
                {committed ? '已开写' : operation === 'talk' ? '正在回复…' : '发送'}
              </button>
            </div>
          </form>
        </div>
      </main>
      </div>

      {cardOpen && !committed && createPortal(
        <div className={styles.backdrop}
             onMouseDown={(event) => { if (event.target === event.currentTarget) setCardOpen(false) }}>
          <section ref={dialogRef} className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="plan-card-title" aria-busy={operation === 'plan'}>
            <header className={styles.dialogHead}>
              <div>
                <h2 id="plan-card-title">方案</h2>
                <p>确认了就照这个写。哪一项不对，直接改。</p>
              </div>
              <button ref={closeRef} type="button" className={styles.close} aria-label="关闭方案卡"
                      onClick={() => setCardOpen(false)}>×</button>
            </header>

            <div className={styles.dialogBody} ref={cardBody}>
              {FIELDS.map(([key, label]) => (
                <label key={key}>
                  <span>{label}{REQUIRED_TEXT.includes(key) ? '（必填）' : ''}</span>
                  <textarea className="input" rows={key === 'plot_sketch' ? 3 : 2}
                            disabled={busy}
                            aria-label={label} value={String(card[key] ?? '')} maxLength={4000}
                            onChange={(event) => setCard({ ...card, [key]: event.target.value })} />
                </label>
              ))}
              <div className={styles.pair}>
                <label>
                  <span>章数（1–10）</span>
                  <input className="input" type="number" min={1} max={10} aria-label="章数"
                         disabled={busy}
                         value={card.chapter_count ?? 5}
                         onChange={(event) => setCard({ ...card, chapter_count: Number(event.target.value) })} />
                </label>
                <label>
                  <span>每章字数（1000–8000）</span>
                  <input className="input" type="number" min={1000} max={8000} aria-label="每章字数"
                         disabled={busy}
                         value={card.chars_per_chapter ?? 4000}
                         onChange={(event) => setCard({ ...card, chars_per_chapter: Number(event.target.value) })} />
                </label>
              </div>
              {lengths.compressed && (
                <div className="banner banner-warning">
                  每章字数已按全篇 {SHORT_TOTAL_MAX} 字上限归一为每章 {lengths.chars} 字，生成时按这个数走。
                </div>
              )}
              <label>
                <span>文风（开写后不可改）</span>
                <select className="input" aria-label="文风" value={styleItemId}
                        disabled={busy}
                        onChange={(event) => setStyleItemId(event.target.value)}>
                  <option value="">不指定</option>
                  {styleItems.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}{item.builtin ? '（内置）' : '（我的）'}
                    </option>
                  ))}
                </select>
              </label>
              {errorBanner}
              {!cardReady && <small className={styles.hint}>还差几个必填项——也可以关掉这张卡，直接告诉助手，它会补上。</small>}
            </div>

            <footer className={styles.dialogFoot}>
              <Link to="/styles">去文风库添加</Link>
              <button type="button" className="btn btn-quiet" onClick={() => setCardOpen(false)}>再聊聊</button>
              <button type="button" className="btn btn-primary" disabled={!cardReady || busy} onClick={confirm}>
                {operation === 'plan' ? '正在规划…' : '确认，开写'}
              </button>
            </footer>
          </section>
        </div>,
        document.body,
      )}
    </div>
  )
}
