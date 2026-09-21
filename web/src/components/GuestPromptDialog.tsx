// 游客点中任何控件时的唯一出口：说清当前是只读浏览，并把注册/登录这两个动作递出去。
import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import styles from './GuestPromptDialog.module.css'

export function GuestPromptDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    closeRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null
  const go = (path: string) => {
    onClose()
    void navigate(path)
  }
  return createPortal(
    <div
      className={styles.backdrop}
      data-guest-exempt
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="guest-prompt-title">
        <header className={styles.head}>
          <h2 id="guest-prompt-title">当前是未登录的浏览模式</h2>
          <button ref={closeRef} type="button" className={styles.close} aria-label="关闭" onClick={onClose}>×</button>
        </header>
        <div className={styles.body}>
          <p>这里只能查看。注册或登录后，作品、环境配置与主题都可以修改。</p>
          <div className={styles.actions}>
            <button type="button" className="btn btn-primary" onClick={() => go('/login?mode=register')}>注册</button>
            <button type="button" className="btn btn-secondary" onClick={() => go('/login')}>登录</button>
          </div>
        </div>
      </section>
    </div>,
    document.body,
  )
}
