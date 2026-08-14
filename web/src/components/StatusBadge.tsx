// 状态/severity 徽标：文字 + 色 + 边框三通道（DESIGN §Review——不单靠颜色传达结果）。
import type { ReactNode } from 'react'

export type BadgeTone =
  | 'critical'
  | 'major'
  | 'minor'
  | 'hint'
  | 'success'
  | 'warning'
  | 'error'
  | 'accent'

export function StatusBadge({ tone, children }: { tone: BadgeTone; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}
