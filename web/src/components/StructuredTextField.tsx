import { useEffect, useRef, useState } from 'react'

interface Props<T> {
  value: T
  format: (value: T) => string
  parse: (text: string) => T
  onChange: (value: T) => void
  singleLine?: boolean
  className?: string
  rows?: number
  placeholder?: string
  'aria-label'?: string
}

/** Keep the editable text intact while its consumer receives structured data. */
export function StructuredTextField<T>({
  value, format, parse, onChange, singleLine = false, rows, ...props
}: Props<T>) {
  const formatted = format(value)
  const [text, setText] = useState(formatted)
  const lastEmitted = useRef(value)
  useEffect(() => {
    // Consumers retain the emitted structured value. A different object is an
    // external replacement, even when its formatted content is unchanged.
    if (value !== lastEmitted.current) {
      lastEmitted.current = value
      setText(formatted)
    }
  }, [formatted, value])

  function edit(nextText: string) {
    const next = parse(nextText)
    lastEmitted.current = next
    setText(nextText)
    onChange(next)
  }

  return singleLine
    ? <input {...props} value={text} onChange={event => edit(event.target.value)} />
    : <textarea {...props} rows={rows} value={text} onChange={event => edit(event.target.value)} />
}
