import { useLayoutEffect, useRef, type TextareaHTMLAttributes } from 'react'

import { resizeTextarea } from '../lib/resizeTextarea'

export function AutoTextarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    resizeTextarea(element)
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => resizeTextarea(element)) : null
    observer?.observe(element)
    return () => observer?.disconnect()
  }, [props.value])
  return <textarea {...props} ref={ref} onInput={(event) => { resizeTextarea(event.currentTarget); props.onInput?.(event) }} style={{ ...props.style, overflowY: 'hidden', resize: 'none' }} />
}
