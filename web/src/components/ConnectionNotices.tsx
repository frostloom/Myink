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
  return createPortal(
    <section className={styles.region} aria-label="模型连接通知">
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
