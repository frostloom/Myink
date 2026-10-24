import { ResourceBodyFields } from './ResourceBodyFields'
import { isSupportingReference, isLegacyRoleSupplement } from '../lib/resourceDisplay'
import { useEffect, useState } from 'react'
import {
  writingResources as api,
  resourceKinds,
  resourceError,
  type WritingResource,
  type ResourceSnapshot,
  type SelectionInput,
  type ResourceBody,
} from '../lib/writingResources'
import { AdminDialog } from '../pages/admin/AdminDialog'
import { ResourceUpdates } from './ResourceUpdates'
export function WritingResourcePicker({ projectId }: { projectId: string }) {
  const [catalog, setCatalog] = useState<WritingResource[]>([]),
    [personal, setPersonal] = useState<WritingResource[]>([])
  const [snapshot, setSnapshot] = useState<ResourceSnapshot | null>(null),
    [chosen, setChosen] = useState<SelectionInput[]>([])
  const [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('')
  const [editing, setEditing] = useState<{
      item: WritingResource
      own: boolean
      projectOrigin?: 'platform' | 'personal'
    } | null>(null),
    [name, setName] = useState(''),
    [body, setBody] = useState('')
  useEffect(() => {
    let live = true
    Promise.all([api.catalog(), api.personal(), api.snapshot(projectId)])
      .then(([c, p, s]) => {
        if (!live) return
        setCatalog(c.items.filter((item) => item.kind !== 'role_prompt' && item.kind !== 'reference' && !isSupportingReference(item) && !isLegacyRoleSupplement(item)))
        setPersonal(p.items.filter((item) => item.kind !== 'role_prompt'))
        setSnapshot(s)
        setChosen(
          s.selections.map((i) => ({
            origin: i.origin,
            resource_id: i.resource_id,
            personal_override: i.personal_override,
            ...(i.personal_override ? { body: i.body } : {}),
          })),
        )
      })
      .catch((e) => {
        if (live) setError(resourceError(e))
      })
    return () => {
      live = false
    }
  }, [projectId])
  function chosenMetadata(entry: SelectionInput) {
    return (
      snapshot?.selections.find(
        (item) =>
          item.origin === entry.origin &&
          item.resource_id === entry.resource_id,
      ) ??
      (entry.origin === 'platform' ? catalog : personal).find(
        (item) => item.id === entry.resource_id,
      )
    )
  }
  const chosenGenres = chosen.filter(
    (entry) => chosenMetadata(entry)?.kind === 'genre',
  )
  function makePrimary(entry: SelectionInput) {
    setChosen((previous) => {
      const firstGenre = previous.findIndex(
        (item) => chosenMetadata(item)?.kind === 'genre',
      )
      const remaining = previous.filter(
        (item) =>
          !(
            item.origin === entry.origin &&
            item.resource_id === entry.resource_id
          ),
      )
      remaining.splice(Math.max(0, firstGenre), 0, entry)
      return remaining
    })
  }
  async function saveSelection() {
    if (!snapshot) return
    setBusy(true)
    try {
      const s = await api.select(projectId, snapshot.revision, chosen)
      setSnapshot(s)
      setNotice('资源快照已保存，后续生成使用此版本。')
      setError('')
    } catch (e) {
      setError(resourceError(e))
    } finally {
      setBusy(false)
    }
  }
  async function savePrivate() {
    if (!editing) return
    setBusy(true)
    try {
      const input = {
        name,
        source: editing.item.source,
        body: JSON.parse(body) as ResourceBody,
      }
      if (editing.projectOrigin && snapshot) {
        const next = chosen.map((entry) =>
          entry.origin === editing.projectOrigin &&
          entry.resource_id === editing.item.id
            ? { ...entry, personal_override: true, body: input.body }
            : entry,
        )
        const savedSnapshot = await api.select(
          projectId,
          snapshot.revision,
          next,
        )
        setSnapshot(savedSnapshot)
        setChosen(next)
        setEditing(null)
        setNotice('已保存本书个人覆盖，平台更新不会替换此内容。')
        setError('')
        return
      }
      const saved = editing.own
        ? await api.savePersonal(editing.item.id, {
            ...input,
            expected_generation: editing.item.generation,
          })
        : await api.createPersonal({ ...input, kind: editing.item.kind })
      setPersonal((old) => [...old.filter((i) => i.id !== saved.id), saved])
      setEditing(null)
      setNotice('已保存到个人资源库，请勾选并保存本书选择。')
      setError('')
    } catch (e) {
      setError(resourceError(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section
      className="panel"
      style={{ padding: '1.5rem', marginBottom: '1rem' }}
    >
      <h2>本书写作资源</h2>
      <p>选择题材、文风等平台资源或个人资源。角色提示词自动生效，写作知识库由AI按需查阅，无需勾选。个人修改仅保存在个人库或本书快照。</p>
      {snapshot && !snapshot.configured && (
        <p>
          尚未配置：继续使用建书时的原有题材和文风。首次保存选择后启用资源快照。
        </p>
      )}
      {error && !editing && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {chosenGenres.length > 0 && (
        <section aria-label="待保存题材顺序">
          <h3>题材优先级（保存后生效）</h3>
          <p>主题材主导，辅题材补充；组合遵循主辅 7:3 的优先级。</p>
          {chosenGenres.map((entry, index) => (
            <p key={`${entry.origin}:${entry.resource_id}`}>
              {chosenMetadata(entry)?.name} ·{' '}
              {index === 0 ? '主题材' : '辅题材'}
              <button
                className="btn btn-quiet"
                disabled={busy || index === 0}
                onClick={() => makePrimary(entry)}
              >
                设为主题材 {chosenMetadata(entry)?.name}
              </button>
            </p>
          ))}
        </section>
      )}
      {snapshot?.selections.map((s) => (
        <p key={`${s.origin}:${s.resource_id}`}>
          {s.name} · {s.origin === 'platform' ? '平台' : '个人'} · v{s.version}{' '}
          · 发布标识 {s.generation}
          {s.kind === 'genre' &&
            ` · 已保存${snapshot.selections.filter((entry) => entry.kind === 'genre')[0] === s ? '主题材' : '辅题材'}`}
          {s.personal_override ? ' · 个人覆盖（更新不会替换）' : ''}
          <button
            className="btn btn-quiet"
            disabled={
              busy ||
              !chosen.some(
                (entry) =>
                  entry.origin === s.origin &&
                  entry.resource_id === s.resource_id,
              )
            }
            onClick={() =>
              setChosen((old) =>
                old.filter(
                  (entry) =>
                    !(
                      entry.origin === s.origin &&
                      entry.resource_id === s.resource_id
                    ),
                ),
              )
            }
          >
            移除本书选择 {s.name}
          </button>
          <button
            className="btn btn-quiet"
            disabled={
              busy ||
              !chosen.some(
                (entry) =>
                  entry.origin === s.origin &&
                  entry.resource_id === s.resource_id,
              )
            }
            onClick={() => {
              setEditing({
                item: {
                  id: s.resource_id,
                  name: s.name,
                  kind: s.kind,
                  source: s.origin,
                  status: 'published',
                  generation: s.generation,
                  current_version: s.version,
                  body: s.body,
                },
                own: false,
                projectOrigin: s.origin,
              })
              setName(s.name)
              setBody(JSON.stringify(s.body, null, 2))
              setError('')
            }}
          >
            自定义本书 {s.name}
          </button>
        </p>
      ))}
      {(['platform', 'personal'] as const).map((origin) => (
        <section key={origin}>
          <h3>{origin === 'platform' ? '平台资源' : '我的资源'}</h3>
          {(origin === 'platform' ? catalog : personal).map((item) => (
            <div
              key={item.id}
              style={{
                borderBottom: '1px solid var(--line)',
                padding: '.75rem 0',
              }}
            >
              <label>
                <input
                  type="checkbox"
                  disabled={busy}
                  checked={chosen.some(
                    (s) => s.origin === origin && s.resource_id === item.id,
                  )}
                  onChange={(e) =>
                    setChosen((old) =>
                      e.target.checked
                        ? [...old, { origin, resource_id: item.id }]
                        : old.filter(
                            (s) =>
                              !(
                                s.origin === origin && s.resource_id === item.id
                              ),
                          ),
                    )
                  }
                />{' '}
                {item.name} · {resourceKinds[item.kind]} · v
                {item.current_version}
              </label>
              <button
                className="btn btn-quiet"
                disabled={busy}
                onClick={() => {
                  setEditing({ item, own: origin === 'personal' })
                  setName(item.name)
                  setBody(JSON.stringify(item.body, null, 2))
                  setError('')
                }}
              >
                {origin === 'platform' ? '复制到个人资源' : '编辑个人资源'}{' '}
                {item.name}
              </button>
            </div>
          ))}
        </section>
      ))}
      <button
        className="btn btn-primary"
        disabled={busy || !snapshot}
        onClick={() => void saveSelection()}
      >
        保存本书资源选择
      </button>
      <ResourceUpdates
        key={snapshot?.revision}
        projectId={projectId}
        autoOpen={false}
        onAdopt={(s) => {
          setSnapshot(s)
          setChosen(
            s.selections.map((i) => ({
              origin: i.origin,
              resource_id: i.resource_id,
              personal_override: i.personal_override,
              ...(i.personal_override ? { body: i.body } : {}),
            })),
          )
        }}
      />
      {editing && (
        <AdminDialog
          title={editing.projectOrigin ? '本书个人覆盖' : '个人资源副本'}
          busy={busy}
          onClose={() => setEditing(null)}
        >
          <p>不会修改平台发布内容或其他用户的资源。</p>
          <fieldset disabled={busy}>
            <label>
              个人资源名称
              <input
                className="input"
                value={name}
                disabled={!!editing.projectOrigin}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <ResourceBodyFields
              kind={editing.item.kind}
              genres={[...catalog, ...personal].filter((item) => item.kind === 'genre' && 'catalog_id' in item.body).map((item) => ({id:(item.body as {catalog_id:string}).catalog_id, name:item.name}))}
              value={JSON.parse(body) as ResourceBody}
              onChange={(value) => setBody(JSON.stringify(value, null, 2))}
            />
          </fieldset>
          {error && <p role="alert">{error}</p>}
          <button
            className="btn"
            disabled={busy}
            onClick={() => setEditing(null)}
          >
            取消
          </button>
          <button
            className="btn btn-primary"
            disabled={busy || !name.trim()}
            onClick={() => void savePrivate()}
          >
            {editing.projectOrigin ? '保存本书个人覆盖' : '保存个人资源'}
          </button>
        </AdminDialog>
      )}
    </section>
  )
}
