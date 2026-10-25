import { useEffect, useLayoutEffect, useRef, type ReactNode } from 'react'
import { resizeTextarea } from '../../lib/resizeTextarea'
import styles from './AdminResources.module.css'

export function AdminDialog({
  title,
  children,
  onClose,
  busy,
}: {
  title: string
  children: ReactNode
  onClose: () => void
  busy: boolean
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useLayoutEffect(() => {
    ref.current?.querySelectorAll('textarea').forEach(resizeTextarea)
  })
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const dialog = ref.current
    if (typeof dialog?.showModal === 'function') dialog.showModal()
    else dialog?.setAttribute('open', '')
    const backgrounds: HTMLElement[] = [document.documentElement, document.body]
    for (let parent = dialog?.parentElement; parent; parent = parent.parentElement) {
      if (!backgrounds.includes(parent) && /auto|scroll/.test(getComputedStyle(parent).overflowY)) backgrounds.push(parent)
    }
    const previousOverflow = backgrounds.map((element) => element.style.overflowY)
    backgrounds.forEach((element) => { element.style.overflowY = 'hidden' })
    const resize = () => dialog?.querySelectorAll('textarea').forEach(resizeTextarea)
    resize()
    dialog?.addEventListener('input', resize)
    window.addEventListener('resize', resize)
    const observer = new MutationObserver(resize)
    if (dialog) observer.observe(dialog, { childList: true, subtree: true, characterData: true })
    return () => {
      observer.disconnect()
      dialog?.removeEventListener('input', resize)
      window.removeEventListener('resize', resize)
      backgrounds.forEach((element, index) => { element.style.overflowY = previousOverflow[index] })
      if (previous?.isConnected) previous.focus()
    }
  }, [])
  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault()
        if (!busy) onClose()
      }}
    >
      <header className={styles.dialogHead}>
        <h2>{title}</h2>
        <button type="button" className="btn btn-quiet" aria-label="关闭" disabled={busy} onClick={onClose}>
          ×
        </button>
      </header>
      {children}
    </dialog>
  )
}
