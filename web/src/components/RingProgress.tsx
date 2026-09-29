/** 环形进度：给「一次跑几分钟、中途只有字数在长」的长调用用（短篇成稿/改稿）。

 * 单值驱动（0–1）。环里是百分比 + 阶段名——光有百分比，用户仍会问「它到底在干嘛」。
 * `indeterminate` 用在没有实时数字的阶段（审稿、补写）：环不再表示刻度，只用转动的短弧
 * 说明「还活着」，比停在一个假百分比上更诚实。
 */
import styles from './RingProgress.module.css'

const STROKE = 10

interface Props {
  /** 0–1，超出范围会被夹住。 */
  value: number
  /** 读屏用的名字；屏幕上看不见它。 */
  ariaLabel: string
  /** 环内的阶段名，跟在百分比下面。 */
  label: string
  /** 没有实时刻度：只转圈不给百分比。 */
  indeterminate?: boolean
  size?: number
}

export function RingProgress({ value, ariaLabel, label, indeterminate = false, size = 148 }: Props) {
  const clamped = Math.min(Math.max(value, 0), 1)
  const radius = (size - STROKE) / 2
  const circumference = 2 * Math.PI * radius
  const percent = Math.round(clamped * 100)

  return (
    <div className={styles.ring} style={{ width: size, height: size }}
         role="progressbar" aria-label={ariaLabel}
         aria-valuemin={indeterminate ? undefined : 0}
         aria-valuemax={indeterminate ? undefined : 100}
         aria-valuenow={indeterminate ? undefined : percent}>
      <svg className={styles.svg} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle className={styles.track} cx={size / 2} cy={size / 2} r={radius}
                strokeWidth={STROKE} fill="none" />
        <circle className={[styles.fill, indeterminate ? styles.pulse : ''].join(' ')}
                cx={size / 2} cy={size / 2} r={radius} strokeWidth={STROKE} fill="none"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={indeterminate ? circumference * 0.75
                  : circumference * (1 - clamped)} />
      </svg>
      <div className={styles.center} aria-hidden="true">
        <strong>{indeterminate ? '···' : `${percent}%`}</strong>
        <span>{label}</span>
      </div>
    </div>
  )
}
