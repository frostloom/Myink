import { formatDate } from './shared'
import { ResourceContent } from './ResourceContent'
import { RolePromptFields } from './RolePromptFields'
import {
  isSourceNotice,
  isSupportingReference,
  isLegacyRoleSupplement,
  resourceUsage,
  writingRoles,
  resourceSummary,
  referencePurpose,
  resourceTitle,
} from '../../lib/resourceDisplay'
import { emptyFields } from '../../lib/genrePacks'
import { ResourceBodyFields } from '../../components/ResourceBodyFields'
import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import {
  writingResources as api,
  resourceKinds,
  resourceError,
  emptyResourceStyleProfile,
  type WritingResource,
  type ResourceRevision,
  type ResourceBody,
  type ResourceKind,
} from '../../lib/writingResources'
import type { AdminOutletContext } from './shared'
import { AdminDialog } from './AdminDialog'
import styles from './AdminResources.module.css'
export default function WritingResources({
  scope = 'all',
}: {
  scope?: 'all' | 'prompts' | 'genres'
}) {
  const { onForbidden } = useOutletContext<AdminOutletContext>()
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [showArchived, setShowArchived] = useState(false)
  const [archiving, setArchiving] = useState(false)
  const allowedKinds = (Object.keys(resourceKinds) as ResourceKind[]).filter(
    (k) =>
      scope === 'all' ||
      (scope === 'genres'
        ? ['genre', 'genre_rule'].includes(k)
        : ['role_prompt', 'writing_rule', 'expression_rule', 'genre_rule'].includes(k)),
  )
  const title =
    scope === 'prompts' ? '提示词' : scope === 'genres' ? '题材包' : '写作资源'
  const [items, setItems] = useState<WritingResource[]>([])
  const [selected, setSelected] = useState<WritingResource | null>(null)
  const [history, setHistory] = useState<ResourceRevision[]>([])
  const [name, setName] = useState(''),
    [source, setSource] = useState(''),
    [body, setBody] = useState('')
  const [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [search, setSearch] = useState('')
  const [preview, setPreview] = useState<'publish' | ResourceRevision | null>(
      null,
    ),
    [note, setNote] = useState('')
  const [kind, setKind] = useState<ResourceKind>('reference')
  const selectableKinds: ResourceKind[] = allowedKinds.filter((k) => k !== 'role_prompt')
  const available = items.filter((item) => !isSupportingReference(item) && !isLegacyRoleSupplement(item) && (showArchived || item.status !== 'archived'))
  const visible = available
    .filter(
      (i) =>
        allowedKinds.includes(i.kind) &&
        (filter === 'all' || i.kind === filter) &&
        `${resourceTitle(i)} ${i.name} ${i.kind === 'role_prompt' && 'role' in i.body
                ? writingRoles[i.body.role]?.purpose ?? resourceSummary(i.body).slice(0, 200)
                : i.kind === 'reference' ? referencePurpose(i) : resourceSummary(i.body).slice(0, 200)}`
          .toLowerCase()
          .includes(search.trim().toLowerCase()),
    )
    .sort((a, b) => Number(isSourceNotice(a)) - Number(isSourceNotice(b)))
  function failure(e: unknown) {
    if ((e as { status?: number }).status === 403) onForbidden()
    setError(resourceError(e))
  }
  async function load() {
    setLoading(true)
    try {
      setItems((await api.adminList()).items)
      setError('')
    } catch (e) {
      failure(e)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    let live = true
    api
      .adminList()
      .then((r) => {
        if (live) setItems(r.items)
      })
      .catch((e) => {
        if (live) {
          setError(resourceError(e))
        }
      })
      .finally(() => {
        if (live) setLoading(false)
      })
    return () => {
      live = false
    }
  }, [])
  async function edit(item: WritingResource) {
    setSelected(item)
    setArchiving(false)
    setName(item.name)
    setSource(item.source)
    setBody(JSON.stringify(item.body, null, 2))
    setPreview(null)
    setError('')
    setHistory([])
    setNote('')
    try {
      setHistory((await api.revisions(item.id)).items)
    } catch (e) {
      failure(e)
    }
  }
  async function save() {
    if (!selected) return
    setBusy(true)
    try {
      const parsed = JSON.parse(body) as ResourceBody
      const saved = selected.id
        ? await api.save(selected.id, {
            name,
            source,
            body: parsed,
            expected_generation: selected.generation,
          })
        : await api.create({ name, kind, source, body: parsed })
      setSelected(saved)
      setItems((old) => [...old.filter((i) => i.id !== saved.id), saved])
      setError('')
    } catch (e) {
      failure(e)
    } finally {
      setBusy(false)
    }
  }
  async function release() {
    if (!selected || !preview) return
    setBusy(true)
    try {
      const saved =
        preview === 'publish'
          ? await api.publish(selected.id, selected.generation, note)
          : await api.rollback(
              selected.id,
              selected.generation,
              preview.version,
              note,
            )
      setSelected(null)
      setPreview(null)
      setItems((old) => old.map((i) => (i.id === saved.id ? saved : i)))
      setError('')
    } catch (e) {
      failure(e)
    } finally {
      setBusy(false)
    }
  }
  async function archive() {
    if (!selected) return
    setBusy(true)
    try {
      const saved = await api.save(selected.id, {
        expected_generation: selected.generation,
        name: selected.name,
        source: selected.source,
        body: selected.body,
        status: 'archived',
      })
      setItems((old) => old.map((item) => item.id === saved.id ? saved : item))
      setSelected(null)
      setArchiving(false)
      setError('')
    } catch (error) {
      failure(error)
    } finally {
      setBusy(false)
    }
  }
  const clean =
    !!selected &&
    selected.name === name &&
    selected.source === source &&
    JSON.stringify(selected.body, null, 2) === body
  function resourceCard(i: WritingResource) {
    return (
          <button
            key={i.id}
            className={`${styles.card} ${styles.resourceCard}`}
            aria-label={`编辑 ${resourceTitle(i)}`}
            onClick={() => void edit(i)}
          >
            <span className={styles.resourceBadges}>
              <span>{resourceKinds[i.kind]}</span>
              <span>
                {
                  { draft: '草稿', published: '已发布', archived: '已下架' }[
                    i.status
                  ]
                }
              </span>
            </span>
            <strong className={styles.cardTitle}>{resourceTitle(i)}</strong>
            <span className={styles.preview}>
              {i.kind === 'role_prompt' && 'role' in i.body
                ? writingRoles[i.body.role]?.purpose ?? resourceSummary(i.body).slice(0, 200)
                : i.kind === 'reference' ? referencePurpose(i) : resourceSummary(i.body).slice(0, 200)}
            </span>
            <span className={styles.tags}><span>{resourceUsage(i).activation}</span></span>
            <span className={styles.usage}>{resourceUsage(i).when}</span>
            <span className={styles.resourceMeta}>
              {i.current_version ? `已发布 v${i.current_version}` : '尚未发布'}

            </span>
            <span className={styles.editHint}>查看与编辑</span>
          </button>
    )
  }
  return (
    <div className={styles.page}>
      <header className={styles.pageHead}>
        <div>
          <h1>{title}</h1>
          <p>管理自动生效的角色提示词、AI按需查阅的写作知识库，以及作者可选用的题材与文风。</p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => {
            setSelected({
              id: '',
              name: '',
              kind: selectableKinds[0],
              source: '',
              body: initialBody(selectableKinds[0]),
              generation: 0,
              current_version: null,
              status: 'draft',
            })
            setArchiving(false)
            setName('')
            setSource('')
            setBody(JSON.stringify(initialBody(selectableKinds[0])))
            setKind(selectableKinds[0])
            setHistory([])
            setError('')
            setPreview(null)
          }}
        >
          新建资源
        </button>
      </header>
      {!selected && error && <p role="alert">{error}</p>}
      <div className={styles.toolbar}>
        <input
          className="input"
          aria-label="搜索写作资源"
          placeholder="搜索题材、文风、写作要求…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} /> 显示已下架资源</label>
        <button className="btn" onClick={() => void load()}>
          重新加载
        </button>
      </div>
      <div
        className={styles.resourceTabs}
        role="group"
        aria-label="资源类型筛选"
      >
        {[
          ['all', '全部'],
          ...allowedKinds.map((k) => [k, resourceKinds[k]]),
        ].map(([key, label]) => (
          <button
            key={key}
            className="btn btn-quiet"
            aria-pressed={filter === key}
            onClick={() => setFilter(key)}
          >
            {label}
            <span>
              {
                available.filter(
                  (i) =>
                    allowedKinds.includes(i.kind) &&
                    (key === 'all' || i.kind === key),
                ).length
              }
            </span>
          </button>
        ))}
      </div>
      <p className={styles.hint} role="status">
        {loading ? '正在加载资源…' : `共 ${visible.length} 项资源`}
      </p>
      {!loading && visible.length === 0 && (
        <div className={styles.empty}>
          {search || filter !== 'all'
            ? '没有匹配的资源，请调整搜索或筛选条件。'
            : '暂无资源，点击“新建资源”开始添加。'}
        </div>
      )}
      {visible.some((item) => item.kind === 'role_prompt') && <section aria-labelledby="automatic-prompts-heading">
        <h2 id="automatic-prompts-heading">角色提示词 · 自动生效</h2>
        <p>这里的角色指写作、规划、审核等AI分工，不是小说人物。进入对应环节时自动使用；草稿不会生效，发布后用于新发起的创作。</p>
        <div className={`${styles.grid} ${styles.resourceGrid}`}>
          {visible.filter((item) => item.kind === 'role_prompt').sort((a, b) => {
            const order = Object.keys(writingRoles)
            return order.indexOf('role' in a.body ? a.body.role : '') - order.indexOf('role' in b.body ? b.body.role : '')
          }).map(resourceCard)}
        </div>
      </section>}
      {visible.some((item) => item.kind === 'reference') && <section aria-labelledby="reference-library-heading" style={{marginTop:32}}>
        <h2 id="reference-library-heading">写作知识库 · AI按需查阅</h2>
        <p>这些是写作方法与示例，无需作者选择。人物设计与关系写法不是本书的人物名单或关系设定；本书实际人物与关系会随创作上下文使用。</p>
        <div className={`${styles.grid} ${styles.resourceGrid}`}>
          {visible.filter((item) => item.kind === 'reference').map(resourceCard)}
        </div>
      </section>}
      <section aria-labelledby="selectable-resources-heading" style={{marginTop:32}}>
        <h2 id="selectable-resources-heading">可选写作资源</h2>
        <p>作者为作品选用后生效，作品保留选定版本，平台更新由作者确认后采用。未配置资源的旧作品沿用原有默认规则。</p>
        <div className={`${styles.grid} ${styles.resourceGrid}`}>
          {visible.filter((item) => item.kind !== 'role_prompt' && item.kind !== 'reference' && !isSupportingReference(item)).map(resourceCard)}
        </div>
      </section>
      <section style={{marginTop:32}} aria-labelledby="private-writing-context-heading">
        <h2 id="private-writing-context-heading">作品自行维护的内容</h2>
        <p>作者文风与样本、人物状态、世界观、历史正文、大纲与章节计划、作品复盘经验，随创作过程使用；由各作品自行维护，不会同步为平台资源。</p>
      </section>
      {items.some(isSupportingReference) && <details style={{marginTop:32}}>
        <summary>资料来源与使用说明</summary>
        <p>部分参考素材来自 webnovel-writer，原始来源与许可随资料保留；这里只作为说明资料，不列入可选创作素材。</p>
        {items.filter(isSourceNotice).map((item) => <details key={item.id}><summary>{resourceTitle(item)}</summary><ResourceContent body={item.body} /></details>)}
      </details>}

      {selected && (
        <AdminDialog
          title={archiving ? '下架资源' : preview ? '发布预览' : `编辑${resourceTitle(selected) || '新资源'}`}
          busy={busy}
          onClose={() => {
            setSelected(null)
            setPreview(null)
            setError('')
          }}
        >
          {archiving ? (
            <>
              <p>确认下架“{resourceTitle(selected)}”？{selected.kind === 'reference' ? '下架后新任务不再查阅此资料，已受理任务仍保留原版本。' : '下架后用户不能再新选此资源，已选用的作品仍保留原有快照。'}</p>
              <p>版本历史保留，可在“显示已下架资源”中重新编辑并发布。本次不会保存未提交的编辑内容。</p>
              <button className="btn" disabled={busy} onClick={() => setArchiving(false)}>取消下架</button>
              <button className="btn btn-primary" disabled={busy} onClick={() => void archive()}>确认下架</button>
            </>
          ) : preview ? (
            <>
              <p>
                {preview === 'publish'
                  ? '发布当前已保存草稿'
                  : '回退至历史版本 v' + preview.version}
                。{['role_prompt', 'reference'].includes(selected.kind) ? '新发起的创作使用发布版本，已受理任务保留原版本。' : '历史版本保持不变，已有作品需主动采用更新。'}
              </p>
              <h3>
                {preview === 'publish' ? resourceTitle(selected) : preview.name}
              </h3>
              {selected.kind === 'role_prompt' && 'templates' in (preview === 'publish' ? selected.body : preview.body)
                ? <RolePromptFields value={(preview === 'publish' ? selected.body : preview.body) as Extract<ResourceBody, {role:string}>} readOnly />
                : <ResourceContent body={preview === 'publish' ? selected.body : preview.body} />}
              <label>
                发布说明
                <input
                  className="input"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </label>
              <button
                className="btn"
                disabled={busy}
                onClick={() => setPreview(null)}
              >
                返回编辑
              </button>
              <button
                className="btn btn-primary"
                disabled={busy}
                onClick={() => void release()}
              >
                {preview === 'publish' ? '确认发布' : '确认回退'}
              </button>
            </>
          ) : (
            <>
              <fieldset disabled={busy} className={styles.resourceFields}>
                <label>
                  资源名称
                  <input
                    className="input"
                    value={['role_prompt', 'reference'].includes(selected.kind) ? resourceTitle({name, kind:selected.kind}) : name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                {!selected.id && (
                  <label>
                    资源类型
                    <select
                      value={kind}
                      onChange={(e) => {
                        const next = e.target.value as ResourceKind
                        setKind(next)
                        setBody(
                          JSON.stringify(
                            next === 'reference'
                              ? { files: [] }
                              : next === 'style'
                                ? { profile: emptyResourceStyleProfile() }
                                : next === 'genre'
                                  ? { catalog_id: crypto.randomUUID(), fields: emptyFields() }
                                  : next === 'genre_rule'
                                    ? {
                                        genre_ids: [],
                                        roles: {
                                          writer: '',
                                          planner: '',
                                          audit: '',
                                        },
                                      }
                                    : {
                                        roles: {
                                          writer: '',
                                          planner: '',
                                          audit: '',
                                        },
                                      },
                          ),
                        )
                      }}
                    >
                      {Object.entries(resourceKinds)
                        .filter(([k]) =>
                          selectableKinds.includes(k as ResourceKind),
                        )
                        .map(([k, v]) => (
                          <option key={k} value={k}>
                            {v}
                          </option>
                        ))}
                    </select>
                  </label>
                )}
                {selected.kind === 'role_prompt' && 'templates' in JSON.parse(body)
                  ? <RolePromptFields value={JSON.parse(body) as Extract<ResourceBody, {role:string}>} onChange={(value) => setBody(JSON.stringify(value, null, 2))} />
                  : <ResourceBodyFields
                      kind={selected.id ? selected.kind : kind}
                      value={JSON.parse(body) as ResourceBody}
                      genres={items.filter((item) => item.kind === 'genre' && 'catalog_id' in item.body).map((item) => ({id: (item.body as {catalog_id:string}).catalog_id, name:item.name}))}
                      onChange={(value) => setBody(JSON.stringify(value, null, 2))} />}

              </fieldset>
              <footer className={styles.actions}>
                {selected.id && selected.kind !== 'role_prompt' && selected.status !== 'archived' && <button className="btn btn-quiet" disabled={busy} onClick={() => {setError('');setArchiving(true)}}>下架资源</button>}
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() => setSelected(null)}
                >
                  取消
                </button>
                <button
                  className="btn"
                  disabled={busy || !name.trim()}
                  onClick={() => void save()}
                >
                  保存草稿
                </button>
                <button
                  className="btn btn-primary"
                  disabled={busy || !clean || !selected.id}
                  onClick={() => setPreview('publish')}
                >
                  预览发布
                </button>
              </footer>
              <h3>版本历史</h3>
              {!history.length && (
                <p className={styles.hint}>
                  尚无发布记录，发布后可在这里查看和回退。
                </p>
              )}
              {history.map((h) => (
                <details key={h.version}>
                  <summary>
                    v{h.version} · {resourceTitle({name:h.name, kind:selected.kind})} · {formatDate(h.created_at)}
                  </summary>
                  <p>{h.note}</p>
                  {selected.kind === 'role_prompt' && 'templates' in h.body ? <RolePromptFields value={h.body} readOnly /> : <ResourceContent body={h.body} />}
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() => setPreview(h)}
                  >
                    预览回退至 v{h.version}
                  </button>
                </details>
              ))}
            </>
          )}
          {error && <p role="alert">{error}</p>}
        </AdminDialog>
      )}
    </div>
  )
}

function initialBody(kind: ResourceKind): ResourceBody {
  if (kind === 'reference') return { files: [] }
  if (kind === 'genre') return { catalog_id: crypto.randomUUID(), fields: emptyFields() }
  if (kind === 'style') return { profile: emptyResourceStyleProfile() }
  return {
    ...(kind === 'genre_rule' ? { genre_ids: [] } : {}),
    roles: { writer: '', planner: '', audit: '' },
  }
}
