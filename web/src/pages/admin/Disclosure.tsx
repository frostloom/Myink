import { useState, type ReactNode } from 'react'
import styles from './ExecutionDetail.module.css'

export function Disclosure({ title, children, defaultOpen = false }: { title: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return <details open={open} className={styles.disclosure} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{title}</summary>{open && children}
  </details>
}
