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
  const lastEmitted = useRef(formatted)
  useEffect(() => {
    // External replacements reset the draft. Echoes of our own parsed value
    // must preserve unfinished keys, separators and trailing empty lines.
    if (formatted !== lastEmitted.current) {
      lastEmitted.current = formatted
      setText(formatted)
    }
  }, [formatted])

  function edit(nextText: string) {
    const next = parse(nextText)
    lastEmitted.current = format(next)
    setText(nextText)
    onChange(next)
  }

  return singleLine
    ? <input {...props} value={text} onChange={event => edit(event.target.value)} />
    : <textarea {...props} rows={rows} value={text} onChange={event => edit(event.target.value)} />
}
