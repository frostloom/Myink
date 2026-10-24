export function parseContent(value: unknown): unknown {
  if (typeof value !== 'string') return value
  const source = value.trim().replace(/^```(?:json)?\s*\n?([\s\S]*?)\n?```$/i, '$1')
  if (!/^[{[]/.test(source)) return value
  try { return JSON.parse(source) } catch { return value }
}
