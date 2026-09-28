// 问题反馈挂件：页面右上角吊着一只灯，点它打开反馈面板（描述 + 图片/视频佐证）。
// 灯型和灯光跟着账号主题走（见主题页）；灯光默认开着，关掉之后就不再铺那摊暖光。
// 只挂在登录后的分支里（见 router.tsx 的 RequireAuth），游客看不到它。
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { useLocation } from 'react-router-dom'
import { useTheme } from '../context/ThemeContext'
import { api, fetchFeedbackAttachment } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import { autoGrow } from '../lib/autoGrow'
import {
  clampLampX,
  LAMP_HANG,
  lampFixturePx,
  readLampPlace,
  settleLampDrop,
  writeLampPlace,
  type LampPlace,
} from '../lib/theme'
import type { Feedback, FeedbackAttachment } from '../types'
import { PendantLamp } from './PendantLamp'
import styles from './FeedbackWidget.module.css'

const CATEGORIES: ReadonlyArray<{ id: string; label: string }> = [
  { id: 'bug', label: '问题故障' },
  { id: 'suggestion', label: '功能建议' },
  { id: 'other', label: '其他' },
]

const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  CATEGORIES.map((item) => [item.id, item.label]),
)

const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/gif'])
const VIDEO_TYPES = new Set(['video/mp4', 'video/webm', 'video/quicktime'])
const IMAGE_MAX_BYTES = 10 * 1024 * 1024
const VIDEO_MAX_BYTES = 100 * 1024 * 1024
const MAX_FILES = 4
const DESCRIPTION_MAX = 2000
const CONTACT_MAX = 200

/** 客户端先拦一道：限额与服务端一致，别让用户等上传完了才被拒。 */
function fileError(file: File): string | null {
  if (IMAGE_TYPES.has(file.type)) {
    if (file.size > IMAGE_MAX_BYTES) return '单张图片不要超过 10 MB'
    return null
  }
  if (VIDEO_TYPES.has(file.type)) {
    if (file.size > VIDEO_MAX_BYTES) return '单个视频不要超过 100 MB'
    return null
  }
  return '只支持 jpg / png / webp / gif 图片与 mp4 / webm / mov 视频'
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

function TypeIcon({ video }: { video: boolean }) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">
      {video
        ? <path d="M4 2.5h8a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5H4A1.5 1.5 0 0 1 2.5 12V4A1.5 1.5 0 0 1 4 2.5Z M6.6 5.8l4 2.2-4 2.2Z" fill="currentColor" />
        : <path d="M3 2.5h10a.5.5 0 0 1 .5.5v10a.5.5 0 0 1-.5.5H3a.5.5 0 0 1-.5-.5V3a.5.5 0 0 1 .5-.5Zm2 7.2 2-2.4 2 2 1.4-1.6 1.6 1.9v.4H5Z" fill="currentColor" />}
    </svg>
  )
}

/** 附件取件按钮：库表只存元数据，字节按 id + index 现取，取回后开一个新标签页。
 * 管理端也用这一颗——取件接口对 admin 放行，看现场用的就是同一份字节。 */
export function AttachmentChip({ feedbackId, attachment }: {
  feedbackId: string
  attachment: FeedbackAttachment
}) {
  const [state, setState] = useState<'idle' | 'busy' | 'error'>('idle')
  const video = attachment.mime.startsWith('video/')

  const open = async () => {
    if (state === 'busy') return
    // 先同步开新页再取字节：跨过 await 之后浏览器就不认这次用户激活了，
    // 大视频要拉很久，等回来再 window.open 会被弹窗拦截器静默丢掉。
    const tab = window.open('', '_blank')
    if (!tab) {
      setState('error')
      return
    }
    setState('busy')
    try {
      const blob = await fetchFeedbackAttachment(feedbackId, attachment.index)
      const url = URL.createObjectURL(blob)
      if (!tab.closed) {
        tab.opener = null
        tab.location.href = url
      }
      // 立刻撤销会让新开的那页白屏，等它把字节读走再回收
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
      setState('idle')
    } catch {
      tab.close()
      setState('error')
    }
  }

  return (
    <button type="button" className={styles.chip} onClick={() => void open()} disabled={state === 'busy'}>
      <span className={styles.chipIcon} data-video={video ? 'true' : undefined}><TypeIcon video={video} /></span>
      <span className={styles.chipName}>{attachment.name}</span>
      <span className={styles.chipMeta}>
        {state === 'error' ? '打开失败' : state === 'busy' ? '打开中…' : formatSize(attachment.bytes)}
      </span>
    </button>
  )
}

function FeedbackCard({ item }: { item: Feedback }) {
  return (
    <li className={styles.card}>
      <div className={styles.cardHead}>
        <span className="badge">{CATEGORY_LABELS[item.category] ?? '其他'}</span>
        {item.status === 'resolved'
          ? <span className="badge badge-success">已解决</span>
          : <span className="badge badge-warning">待处理</span>}
        <span className={styles.cardTime}>{formatTime(item.created_at)}</span>
      </div>
      <p className={styles.cardText}>{item.description}</p>
      {item.attachments.length > 0 && (
        <div className={styles.chipRow}>
          {item.attachments.map((attachment) => (
            <AttachmentChip key={attachment.index} feedbackId={item.id} attachment={attachment} />
          ))}
        </div>
      )}
    </li>
  )
}

export function FeedbackWidget() {
  const route = useLocation()
  const { style, lampPreview } = useTheme()
  const lamp = lampPreview?.lamp ?? style.lamp
  const light = lampPreview?.light ?? style.lampLight
  const [place, setPlace] = useState<LampPlace>(() => readLampPlace(
    window.innerWidth,
    window.innerHeight,
    lampFixturePx(lamp),
  ))
  const placeRef = useRef(place)
  const drag = useRef<{
    pointerId: number
    startX: number
    startY: number
    originX: number
    originY: number
    moved: boolean
  } | null>(null)
  const skipClick = useRef(false)
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'submit' | 'mine'>('submit')

  const [category, setCategory] = useState('bug')
  const [description, setDescription] = useState('')
  const [contact, setContact] = useState('')
  const [picked, setPicked] = useState<Array<{ file: File; url: string }>>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const [mine, setMine] = useState<Feedback[] | null>(null)
  const [mineLoading, setMineLoading] = useState(false)
  const [mineError, setMineError] = useState<string | null>(null)

  const bulbRef = useRef<HTMLButtonElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLElement>(null)
  const descRef = useRef<HTMLTextAreaElement>(null)
  const wasOpen = useRef(false)
  const pickedRef = useRef(picked)
  pickedRef.current = picked

  // 打开时焦点落到关闭按钮，Esc 收起，Tab 在面板内循环；关掉后把焦点还给灯泡，键盘用户不会掉队。
  // 同时锁住背后的页面，避免面板开着时正文还在滚。
  useEffect(() => {
    if (open) {
      wasOpen.current = true
      const previousOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      closeRef.current?.focus()
      const onKey = (event: KeyboardEvent) => {
        if (event.key === 'Escape') {
          event.stopPropagation()
          setOpen(false)
          return
        }
        if (event.key !== 'Tab') return
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
      document.addEventListener('keydown', onKey)
      return () => {
        document.body.style.overflow = previousOverflow
        document.removeEventListener('keydown', onKey)
      }
    }
    if (wasOpen.current) {
      wasOpen.current = false
      bulbRef.current?.focus()
    }
  }, [open])

  // 面板里的草稿图是本地 File 的 object URL，卸载时统一还回去。
  // 只认卸载：跟着 picked 变会连刚加进去的那几张一起撤销。
  useEffect(() => () => {
    pickedRef.current.forEach((item) => URL.revokeObjectURL(item.url))
  }, [])

  useEffect(() => {
    if (!open || tab !== 'mine' || mine !== null) return
    const controller = new AbortController()
    setMineLoading(true)
    setMineError(null)
    api.listFeedback(controller.signal)
      .then((result) => { if (!controller.signal.aborted) setMine(result.items) })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setMineError(formatApiError(reason, '加载失败，请稍后重试'))
      })
      .finally(() => { if (!controller.signal.aborted) setMineLoading(false) })
    return () => controller.abort()
  }, [open, tab, mine])

  function addFiles(event: ChangeEvent<HTMLInputElement>) {
    const chosen = Array.from(event.target.files ?? [])
    event.target.value = ''
    if (chosen.length === 0) return
    const room = MAX_FILES - picked.length
    if (room <= 0) {
      setFormError(`最多 ${MAX_FILES} 个附件`)
      return
    }
    const accepted: Array<{ file: File; url: string }> = []
    let error: string | null = null
    for (const file of chosen.slice(0, room)) {
      const problem = fileError(file)
      if (problem) {
        error = problem
        continue
      }
      accepted.push({ file, url: URL.createObjectURL(file) })
    }
    if (accepted.length > 0) setPicked((current) => [...current, ...accepted])
    setFormError(error ?? (chosen.length > room ? `最多 ${MAX_FILES} 个附件` : null))
  }

  function removeFile(url: string) {
    URL.revokeObjectURL(url)
    setPicked((current) => current.filter((item) => item.url !== url))
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    const text = description.trim()
    if (!text) {
      setFormError('请先写下问题描述')
      return
    }
    const form = new FormData()
    form.append('description', text)
    form.append('category', category)
    form.append('contact', contact.trim())
    form.append('page_url', `${route.pathname}${route.search}`)
    for (const item of picked) form.append('files', item.file)

    setBusy(true)
    setFormError(null)
    setNotice(null)
    api.submitFeedback(form)
      .then(() => {
        picked.forEach((item) => URL.revokeObjectURL(item.url))
        setPicked([])
        setDescription('')
        if (descRef.current) descRef.current.style.height = ''
        setContact('')
        setCategory('bug')
        setMine(null) // 下次进「我的反馈」重新拉，刚提交的这条才会在
        setNotice('已提交，我们会在「我的反馈」里同步处理进度。')
        setTab('mine')
      })
      .catch((reason: unknown) => setFormError(formatApiError(reason, '提交失败，请稍后重试')))
      .finally(() => setBusy(false))
  }

  function moveLamp(next: LampPlace) {
    placeRef.current = next
    setPlace(next)
  }

  function onPointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return
    const current = placeRef.current
    drag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: current.x,
      originY: current.hidden ? 0 : current.y,
      moved: false,
    }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }

  function onPointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
    const state = drag.current
    if (!state || state.pointerId !== event.pointerId) return
    const dx = event.clientX - state.startX
    const dy = event.clientY - state.startY
    if (Math.abs(dx) <= 4 && Math.abs(dy) <= 4) return
    state.moved = true
    const width = window.innerWidth || 1
    const height = window.innerHeight || 1
    const dropped = settleLampDrop(state.originY + dy / height, height, lampFixturePx(lamp))
    moveLamp({
      x: clampLampX(state.originX + dx / width, width),
      y: dropped.y,
      hidden: dropped.hidden,
    })
  }

  function onPointerUp(event: ReactPointerEvent<HTMLButtonElement>) {
    const state = drag.current
    if (!state || state.pointerId !== event.pointerId) return
    drag.current = null
    if (!state.moved) return
    skipClick.current = true
    const width = window.innerWidth || 1
    const height = window.innerHeight || 1
    const dropped = settleLampDrop(
      state.originY + (event.clientY - state.startY) / height,
      height,
      lampFixturePx(lamp),
    )
    const next: LampPlace = {
      x: clampLampX(state.originX + (event.clientX - state.startX) / width, width),
      y: dropped.y,
      hidden: dropped.hidden,
    }
    moveLamp(next)
    writeLampPlace(next, width, height, lampFixturePx(lamp))
  }

  const hang = LAMP_HANG[lamp]
  const cordPx = place.hidden ? 0 : place.y * (typeof window === 'undefined' ? 800 : window.innerHeight)

  return (
    <>
      <div
        className={styles.dock}
        style={{
          left: `${place.x * 100}%`,
          ['--cord' as string]: hang.cord,
          ['--beam' as string]: hang.beam,
          ['--span' as string]: String(300 - hang.top),
        }}
      >
        {!place.hidden && (
          <>
            <span className={styles.cord} style={{ height: cordPx }} />
            <span className={styles.hang} style={{ top: cordPx }}>
              <span className={open ? `${styles.sway} ${styles.swaying}` : styles.sway}>
                {light && <span className={styles.glow} />}
                <PendantLamp id={lamp} lit={light} hanging className={styles.fixture} />
              </span>
            </span>
          </>
        )}
        <button
          ref={bulbRef}
          type="button"
          className={place.hidden ? styles.tip : styles.hit}
          style={place.hidden ? undefined : { top: cordPx + lampFixturePx(lamp) - 46 }}
          data-lamp={lamp}
          data-light={light && !place.hidden ? 'on' : 'off'}
          data-hidden={place.hidden ? 'true' : 'false'}
          aria-label="问题反馈"
          aria-expanded={open}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onClick={() => {
            if (skipClick.current || placeRef.current.hidden) {
              skipClick.current = false
              return
            }
            setOpen(true)
          }}
        />
      </div>

      {open && createPortal(
        <div
          className={styles.backdrop}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setOpen(false)
          }}
        >
          <section
            ref={dialogRef}
            className={styles.dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="feedback-title"
          >
            <header className={styles.head}>
              <div>
                <h2 id="feedback-title">问题反馈</h2>
                <p className={styles.headHint}>遇到的问题、想要的功能都可以写在这里，附上截图或录屏更好定位。</p>
              </div>
              <button ref={closeRef} type="button" className={styles.close} aria-label="关闭" onClick={() => setOpen(false)}>×</button>
            </header>

            <nav className={styles.tabs} aria-label="反馈视图">
              <button type="button" aria-pressed={tab === 'submit'} onClick={() => setTab('submit')}>提交反馈</button>
              <button type="button" aria-pressed={tab === 'mine'} onClick={() => setTab('mine')}>我的反馈</button>
            </nav>

            <div className={styles.body}>
              {tab === 'submit' ? (
                <form className={styles.form} onSubmit={onSubmit}>
                  <div className={styles.field}>
                    <span className={styles.fieldLabel}>类型</span>
                    <div className={styles.segRow}>
                      {CATEGORIES.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          className={item.id === category ? `${styles.seg} ${styles.segActive}` : styles.seg}
                          aria-pressed={item.id === category}
                          onClick={() => setCategory(item.id)}
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <label className={styles.field}>
                    <span className={styles.fieldLabel}>问题描述</span>
                    <textarea
                      ref={descRef}
                      className="textarea"
                      aria-label="问题描述"
                      required
                      maxLength={DESCRIPTION_MAX}
                      placeholder="越具体越好：在哪个页面、点了什么、期望怎样、实际怎样"
                      value={description}
                      onChange={(event) => {
                        setDescription(event.target.value)
                        autoGrow(event.target, 280)
                      }}
                      onFocus={(event) => autoGrow(event.target, 280)}
                    />
                    <span className={styles.counter}>{description.length} / {DESCRIPTION_MAX}</span>
                  </label>

                  <label className={styles.field}>
                    <span className={styles.fieldLabel}>联系方式（可选）</span>
                    <input
                      className="input"
                      aria-label="联系方式"
                      maxLength={CONTACT_MAX}
                      placeholder="邮箱或其它能联系到你的方式"
                      value={contact}
                      onChange={(event) => setContact(event.target.value)}
                    />
                  </label>

                  <div className={styles.field}>
                    <span className={styles.fieldLabel}>图片 / 视频</span>
                    <div className={styles.pickRow}>
                      <label className={`btn btn-secondary ${styles.pickLabel}`}>
                        {picked.length > 0 ? '继续添加' : '选择文件'}
                        <input
                          className={styles.pickInput}
                          type="file"
                          multiple
                          accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime"
                          aria-label="上传图片或视频"
                          onChange={addFiles}
                        />
                      </label>
                      <span className={styles.pickHint}>
                        最多 {MAX_FILES} 个 · 图片 ≤ 10 MB · 视频 ≤ 100 MB
                      </span>
                    </div>

                    {picked.length > 0 && (
                      <ul className={styles.pickedList}>
                        {picked.map((item) => (
                          <li key={item.url} className={styles.pickedItem}>
                            <span className={styles.pickedThumb}>
                              {item.file.type.startsWith('video/')
                                ? <video src={item.url} muted playsInline preload="metadata" />
                                : <img src={item.url} alt="" />}
                            </span>
                            <span className={styles.pickedMeta}>
                              <span className={styles.pickedName}>{item.file.name}</span>
                              <span className={styles.pickedSize}>{formatSize(item.file.size)}</span>
                            </span>
                            <button
                              type="button"
                              className="btn btn-quiet"
                              aria-label={`移除 ${item.file.name}`}
                              onClick={() => removeFile(item.url)}
                            >
                              移除
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  {(formError || notice) && (
                    <div className={formError ? 'banner banner-error' : 'banner'} role={formError ? 'alert' : 'status'}>
                      {formError ?? notice}
                    </div>
                  )}

                  <div className={styles.actions}>
                    <button type="button" className="btn btn-quiet" onClick={() => setOpen(false)}>先不写了</button>
                    <button type="submit" className="btn btn-primary" disabled={busy}>
                      {busy ? '提交中…' : '提交'}
                    </button>
                  </div>
                </form>
              ) : (
                <div className={styles.mine}>
                  <div className={styles.mineHead}>
                    <span className={styles.fieldLabel}>我提交过的反馈</span>
                    <button type="button" className="btn btn-quiet" onClick={() => setMine(null)} disabled={mineLoading}>
                      刷新
                    </button>
                  </div>
                  {notice && <div className="banner" role="status">{notice}</div>}
                  {mineLoading && <div className="empty" role="status">正在加载…</div>}
                  {mineError && <div className="banner banner-error" role="alert">{mineError}</div>}
                  {!mineLoading && !mineError && mine?.length === 0 && (
                    <div className="empty">还没有提交过反馈。</div>
                  )}
                  {mine && mine.length > 0 && (
                    <ul className={styles.cardList}>
                      {mine.map((item) => <FeedbackCard key={item.id} item={item} />)}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </section>
        </div>,
        document.body,
      )}
    </>
  )
}
