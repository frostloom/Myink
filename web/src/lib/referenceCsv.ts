/** Decode CSV cells, including escaped quotes, embedded commas, CRLF and multiline examples. */
export function referenceCsv(content: string): Record<string, string>[] | null {
  const rows: string[][] = []
  let row: string[] = [], cell = '', quoted = false
  const source = content.replace(/^\uFEFF/, '')
  for (let i = 0; i < source.length; i++) {
    const ch = source[i]
    if (quoted) {
      if (ch === '"' && source[i + 1] === '"') { cell += '"'; i++ }
      else if (ch === '"') quoted = false
      else cell += ch
    } else if (ch === '"' && cell === '') quoted = true
    else if (ch === ',') { row.push(cell); cell = '' }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && source[i + 1] === '\n') i++
      row.push(cell); if (row.some(Boolean)) rows.push(row)
      row = []; cell = ''
    } else cell += ch
  }
  if (quoted) return null
  row.push(cell); if (row.some(Boolean)) rows.push(row)
  const headers = rows.shift()?.map(value => value.trim())
  if (!headers || headers.length < 2 || headers.some(header => !header) || new Set(headers).size !== headers.length) return null
  if (rows.some(values => values.length !== headers.length)) return null
  const skillNames: Record<string, string> = { write: '写作时参考', plan: '规划时参考', review: '审核时参考', audit: '审核时参考', init: '建书时参考' }
  return rows.map(values => Object.fromEntries(headers.map((header, index) => [header,
    header === '适用技能' ? values[index].split(/[|、]/).map(value => skillNames[value.trim()] ?? value).join('、') : values[index],
  ])))
}
