/** 短篇建书：与助手聊清楚 → 右边那张卡可以随手改 → 「确认，开写」。
 *
 * 与长篇向导的分工：长篇要先填设定、再确认大纲，两步都不能省；短篇这里聊完那一刻
 * 方案卡就是设定，后端在确认时一次把逐章方案落库（生成需要它）。
 */
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { formatApiError } from '../lib/apiError'
import { shortCreationApi, type ShortCreationCard, type ShortCreationPayload }
  from '../lib/shortCreationApi'
import { styleLibraryApi, type StyleLibraryItem } from '../lib/styleLibraryApi'
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

function isReady(card: Partial<ShortCreationCard>): boolean {
  return REQUIRED_TEXT.every((field) => String(card[field] ?? '').trim() !== '')
}

export default function ShortCreationPage() {
  const { session } = useAuth()
  const token = session?.token ?? ''
  const navigate = useNavigate()
  const [data, setData] = useState<ShortCreationPayload | null>(null)
  const [card, setCard] = useState<Partial<ShortCreationCard>>({})
  const [styleItemId, setStyleItemId] = useState('')
  const [styleItems, setStyleItems] = useState<StyleLibraryItem[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
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
  useEffect(() => {
    if (stream.current) stream.current.scrollTop = stream.current.scrollHeight
  }, [data])

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

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const content = draft.trim()
    if (!content || busy) return
    void run(async () => {
      apply(await shortCreationApi.send(token, content, card as Record<string, unknown>))
      setDraft('')
    }, '这句话没发出去，请重试')
  }

  const confirm = () => void run(async () => {
    const out = await shortCreationApi.commit(token, card as Record<string, unknown>, styleItemId || null)
    // commit 只落书不出稿：进工作台点「开始写全篇」才入队
    navigate(`/projects/${out.project_id}`, {
      state: { beginShortWriting: true, planWarning: out.plan_warning },
    })
  }, '确认失败，请重试')

  const restart = () => void run(async () => {
    await shortCreationApi.reset(token)
    await reload()
  }, '重置失败，请重试')

  if (!data) return <div className="empty">{error ?? '正在打开建书对话…'}</div>
  const ready = isReady(card)

  return (
    <div className={styles.wrap}>
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
        </div>
        {error && <div className="banner banner-error" role="alert"><span>{error}</span></div>}
        <form className={styles.composer} onSubmit={submit}>
          <label>
            <textarea aria-label="对助手说" className="input" value={draft} maxLength={4000}
                      placeholder="说说你想写的故事，或者说「就这样，开写吧」"
                      onChange={(event) => setDraft(event.target.value)} />
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy || draft.trim() === ''}>发送</button>
        </form>
      </section>

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
        <small>文风在确认时定下来，之后没有换的入口；想导入自己的文章，去「账号」页的文风库。</small>
        <button type="button" className="btn btn-primary" disabled={!ready || busy} onClick={confirm}>
          确认，开写
        </button>
        {!ready && <small>还差几个必填项——也可以直接告诉助手，它会补上。</small>}
      </aside>
    </div>
  )
}
