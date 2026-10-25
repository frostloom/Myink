import { GenrePackFields } from './GenrePackFields'
import type { GenreFields } from '../lib/genrePacks'
import type { ResourceBody, ResourceKind } from '../lib/writingResources'
import { AutoTextarea } from './AutoTextarea'
import { internalResourceFields, resourceFieldLabels } from '../lib/resourceFieldLabels'
function Fields({
  value,
  onChange,
  path,
}: {
  value: unknown
  onChange: (v: unknown) => void
  path: string
}) {
  if (internalResourceFields.has(path)) return null
  if (Array.isArray(value))
    return (
      <fieldset>
        <legend>{resourceFieldLabels[path] ?? "创作内容"}</legend>
        {value.map((item, index) => (
          <div key={index}>
            <Fields
              value={item}
              path={
                typeof item === 'string'
                  ? `${resourceFieldLabels[path] ?? "条目"} ${index + 1}`
                  : `文件 ${index + 1}`
              }
              onChange={(next) =>
                onChange(value.map((old, i) => (i === index ? next : old)))
              }
            />
            <button
              className="btn btn-quiet"
              type="button"
              onClick={() => onChange(value.filter((_, i) => i !== index))}
            >
              移除第 {index + 1} 项
            </button>
          </div>
        ))}
        <button
          className="btn"
          type="button"
          onClick={() =>
            onChange([
              ...value,
              path === 'files' ? { path: `reference-${crypto.randomUUID()}.md`, content: '' } : '',
            ])
          }
        >
          添加{resourceFieldLabels[path] ?? "创作内容"}
        </button>
      </fieldset>
    )
  if (value && typeof value === 'object')
    return (
      <fieldset>
        <legend>{resourceFieldLabels[path] ?? "创作内容"}</legend>
        {Object.entries(value).map(([key, item]) => (
          <Fields
            key={key}
            path={key}
            value={item}
            onChange={(next) => onChange({ ...value, [key]: next })}
          />
        ))}
      </fieldset>
    )
  const label = resourceFieldLabels[path] ?? (/[a-z_]/i.test(path) ? '创作要求' : path)
  if (typeof value === 'boolean')
    return (
      <label style={{ display: 'block' }}>
        <input
          type="checkbox"
          checked={value}
          onChange={(e) => onChange(e.target.checked)}
        />
        {label}
      </label>
    )
  if (typeof value === 'number')
    return (
      <label style={{ display: 'block' }}>
        {label}
        <input
          className="input"
          type="number"
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </label>
    )
  return (
    <label style={{ display: 'block', marginBottom: '1rem' }}>
      {label}
      <AutoTextarea
        className="textarea"
        rows={path === 'content' ? 12 : 4}
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}
export function ResourceBodyFields({
  kind,
  value,
  onChange,
  genres = [],
}: {
  genres?: { id: string; name: string }[]
  kind: ResourceKind
  value: ResourceBody
  onChange: (v: ResourceBody) => void
}) {
  if (kind === 'genre' && 'fields' in value)
    return (
      <>
        <GenrePackFields
          value={value.fields as GenreFields}
          onChange={(fields) => onChange({ ...value, fields })}
        />
        {value.setup_caps && (
          <Fields
            path="setup_caps"
            value={value.setup_caps}
            onChange={(setup_caps) =>
              onChange({
                ...value,
                setup_caps: setup_caps as Record<string, unknown>,
              })
            }
          />
        )}
      </>
    )
  return (
    <>
    {kind === 'genre_rule' && 'roles' in value && (
      <fieldset><legend>适用题材</legend>
        <p>未选择时适用于所有题材。</p>
        {genres.map((genre) => <label key={genre.id}><input type="checkbox" checked={value.genre_ids?.includes(genre.id) ?? false} onChange={(e) => onChange({ ...value, genre_ids: e.target.checked ? [...(value.genre_ids ?? []), genre.id] : (value.genre_ids ?? []).filter((id) => id !== genre.id) })} />{genre.name}</label>)}
      </fieldset>
    )}
    <Fields
      path="资源内容"
      value={value}
      onChange={(next) => onChange(next as ResourceBody)}
    />
    </>
  )
}
