import { useState, type ReactNode } from 'react'
import styles from './ExecutionDetail.module.css'

export function Disclosure({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return <details className={styles.disclosure} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{title}</summary>{open && children}
  </details>
}
