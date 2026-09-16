import type { GenreFields } from '../lib/genrePacks'

const LIST_KEYS = ['taboos', 'satisfaction', 'mechanics', 'world_hints'] as const
type ListKey = (typeof LIST_KEYS)[number]

function lines(items: string[]): string {
  return items.join('\n')
}

function fromLines(text: string): string[] {
  return text.split('\n').map((s) => s.trim()).filter(Boolean)
}

export function GenrePackFields({
  value,
  onChange,
}: {
  value: GenreFields
  onChange: (next: GenreFields) => void
}) {
  return (
    <div>
      <label className="field" style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12 }}>
        <span style={{ fontSize: '0.85rem', color: 'var(--ink-muted)' }}>核心卖点</span>
        <textarea
          className="textarea"
          rows={3}
          value={value.selling_point}
          onChange={(e) => onChange({ ...value, selling_point: e.target.value })}
        />
      </label>
      <label className="field" style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12 }}>
        <span style={{ fontSize: '0.85rem', color: 'var(--ink-muted)' }}>流派提示（每行「名称｜钩子」）</span>
        <textarea
          className="textarea"
          rows={Math.max(3, value.subgenres.length + 1)}
          value={value.subgenres.map((s) => (s.hook ? `${s.name}｜${s.hook}` : s.name)).join('\n')}
          onChange={(e) =>
            onChange({
              ...value,
              subgenres: fromLines(e.target.value).map((line) => {
                const i = line.indexOf('｜')
                const j = line.indexOf('|')
                const idx = i === -1 ? j : j === -1 ? i : Math.min(i, j)
                if (idx <= 0) return { name: line, hook: '' }
                return { name: line.slice(0, idx).trim(), hook: line.slice(idx + 1).trim() }
              }),
            })
          }
        />
      </label>
      <label className="field" style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12 }}>
        <span style={{ fontSize: '0.85rem', color: 'var(--ink-muted)' }}>节奏</span>
        <textarea
          className="textarea"
          rows={3}
          value={value.pacing}
          onChange={(e) => onChange({ ...value, pacing: e.target.value })}
        />
      </label>
      {LIST_KEYS.map((key) => (
        <label
          key={key}
          className="field"
          style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12 }}
        >
          <span style={{ fontSize: '0.85rem', color: 'var(--ink-muted)' }}>{listLabel(key)}</span>
          <textarea
            className="textarea"
            rows={Math.min(8, Math.max(3, value[key].length + 1))}
            value={lines(value[key])}
            onChange={(e) => onChange({ ...value, [key]: fromLines(e.target.value) })}
          />
        </label>
      ))}
    </div>
  )
}

function listLabel(key: ListKey): string {
  if (key === 'taboos') return '禁忌（每行一条）'
  if (key === 'satisfaction') return '爽点（每行一条）'
  if (key === 'mechanics') return '机制/数值（每行一条）'
  return '世界观法则（每行一条）'
}
