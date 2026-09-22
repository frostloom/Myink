import { useLayoutEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import styles from './ConnectionNotices.module.css'

export type ConnectionNotice = {
  id: string
  tone: 'error' | 'ok'
  text: string
  returnFocus: HTMLElement | null
}

export function ConnectionNotices({ items, onDismiss }: {
  items: ConnectionNotice[]
  onDismiss: (id: string) => void
}) {
  const regionRef = useRef<HTMLElement>(null)
  const newest = items[0]
  useLayoutEffect(() => {
    // 新结果始终位于列表顶端；浏览器的滚动锚定不能把它留在裁切区外。
    if (regionRef.current) regionRef.current.scrollTop = 0
  }, [newest])

  return createPortal(
    <section ref={regionRef} className={styles.region} aria-label="模型连接通知">
      {items.map((item) => (
        <div className={styles.notice} key={item.id} data-tone={item.tone}
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return
            event.stopPropagation()
            onDismiss(item.id)
            if (item.returnFocus?.isConnected) item.returnFocus.focus()
          }}>
          <div role={item.tone === 'error' ? 'alert' : 'status'} aria-atomic="true">{item.text}</div>
          <button type="button" className="btn btn-quiet" aria-label="关闭通知"
            onClick={() => {
              onDismiss(item.id)
              if (item.returnFocus?.isConnected) item.returnFocus.focus()
            }}>关闭</button>
        </div>
      ))}
    </section>, document.body,
  )
}
