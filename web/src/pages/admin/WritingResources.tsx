import { platformApi, type PromptRoleTemplates } from '../../lib/platformApi'
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
import { useEffect, useRef, useState } from 'react'
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
  const [promptCatalog, setPromptCatalog] = useState<PromptRoleTemplates[]>([])
  const [promptError, setPromptError] = useState('')
  const [promptRetry, setPromptRetry] = useState(0)
  const [selectedPromptId, setSelectedPromptId] = useState<string | null>(null)
  const [selected, setSelected] = useState<WritingResource | null>(null)
  const [history, setHistory] = useState<ResourceRevision[]>([])
  const [historyStatus, setHistoryStatus] = useState<'loading' | 'ready' | 'error'>('ready')
  const historyRequest = useRef(0)
  const [previewReady, setPreviewReady] = useState(false)
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
  // Cards are the single display/count/search unit, including expanded role stages.
  const cards: Array<{item:WritingResource; prompt?:{id:string;title:string;when?:string}}> = []
  for (const item of available) {
    if (!allowedKinds.includes(item.kind)) continue
    if (item.kind !== 'role_prompt') {
      cards.push({item})
      continue
    }
    if (!('role' in item.body)) continue
    const role = item.body.role
    cards.push({item,prompt:{id:'__supplement__',title:`${writingRoles[role]?.name ?? '角色'}共用补充`,when:'仅在需要所有相关环节共用同一要求时编辑'}})
    for (const template of promptCatalog.find(group => group.role === role)?.templates ?? []) {
      cards.push({item,prompt:template})
    }
  }
  const matchedCards = cards.filter(({item,prompt}) => {
    const content = prompt && 'templates' in item.body
      ? (prompt.id === '__supplement__' ? item.body.supplement ?? '' : item.body.templates[prompt.id] ?? '')
      : item.kind === 'reference' ? referencePurpose(item) : resourceSummary(item.body).slice(0,200)
    return `${prompt?.title ?? ''} ${prompt?.when ?? ''} ${resourceTitle(item)} ${item.name} ${content}`.toLowerCase().includes(search.trim().toLowerCase())
  })
  const visible = matchedCards.filter(({item}) => filter === 'all' || item.kind === filter)
  const visiblePrompts = visible.filter(({item}) => item.kind === 'role_prompt').sort((a,b) => {
    const order = Object.keys(writingRoles)
    return order.indexOf('role' in a.item.body ? a.item.body.role : '') - order.indexOf('role' in b.item.body ? b.item.body.role : '')
  })
  const commonCount = visiblePrompts.filter(({prompt}) => prompt?.id === '__supplement__').length
  const hasPromptResources = allowedKinds.includes('role_prompt') && available.some(item => item.kind === 'role_prompt')
  const promptsLoading = hasPromptResources && !promptCatalog.length && !promptError
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
  useEffect(() => {
    if (!hasPromptResources || promptCatalog.length) return
    let live = true
    platformApi.getPromptTemplates().then(catalog => {
      if (!catalog.length) throw new Error('empty prompt catalog')
      if (live) { setPromptCatalog(catalog); setPromptError('') }
    })
      .catch(() => { if (live) setPromptError('创作环节列表加载失败，请重新加载。') })
    return () => { live = false }
  }, [hasPromptResources, items, promptRetry, promptCatalog.length])
  const selectedPromptTitle = selected?.kind !== 'role_prompt' ? undefined : selectedPromptId === '__supplement__'
    ? `${selected && 'role' in selected.body ? writingRoles[selected.body.role]?.name ?? '角色' : '角色'}共用补充`
    : promptCatalog.flatMap(group => group.templates).find(template => template.id === selectedPromptId)?.title
  async function edit(item: WritingResource, promptId: string | null = null) {
    const request = ++historyRequest.current
    setSelectedPromptId(promptId)
    setSelected(item)
    setArchiving(false)
    setName(item.name)
    setSource(item.source)
    setBody(JSON.stringify(item.body, null, 2))
    setPreview(null)
    setError('')
    setHistory([])
    setHistoryStatus('loading')
    setNote('')
    try {
      const revisions = await api.revisions(item.id)
      if (request !== historyRequest.current) return
      setHistory(revisions.items)
      setHistoryStatus('ready')
    } catch (e) {
      if (request !== historyRequest.current) return
      setHistoryStatus('error')
      failure(e)
    }
  }
  function closeEditor() {
    historyRequest.current += 1
    setSelected(null)
    setSelectedPromptId(null)
    setPreview(null)
    setError('')
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
    if (!selected || !preview || (selected.kind === 'role_prompt' && !previewReady)) return
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
      closeEditor()
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
      closeEditor()
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
  function resourceCard(i: WritingResource, prompt?: {id:string;title:string;when?:string}) {
    const cardTitle = prompt?.title ?? resourceTitle(i)
    return (
          <button
            key={`${i.id}:${prompt?.id ?? 'resource'}`}
            className={`${styles.card} ${styles.resourceCard}`}
            aria-label={`编辑 ${cardTitle}`}
            onClick={() => void edit(i, prompt?.id ?? null)}
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
            <strong className={styles.cardTitle}>{cardTitle}</strong>
            <span className={styles.preview}>
              {prompt && 'templates' in i.body
                ? (prompt.id === '__supplement__' ? i.body.supplement || '适用于此分工各环节的共用要求' : i.body.templates[prompt.id] || prompt.when || '点击编辑此环节的创作要求').slice(0,200)
                : i.kind === 'role_prompt' && 'role' in i.body ? writingRoles[i.body.role]?.purpose ?? resourceSummary(i.body).slice(0, 200)
                : i.kind === 'reference' ? referencePurpose(i) : resourceSummary(i.body).slice(0, 200)}
            </span>
            <span className={styles.tags}><span>{resourceUsage(i).activation}</span></span>
            <span className={styles.usage}>{prompt?.when ?? resourceUsage(i).when}</span>
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
            historyRequest.current += 1
            setSelectedPromptId(null)
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
            setHistoryStatus('ready')
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
          placeholder="搜索创作环节、题材、文风或规则…"
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
                matchedCards.filter(({item}) => key === 'all' || item.kind === key).length
              }
            </span>
          </button>
        ))}
      </div>
      <p className={styles.hint} role="status">
        {loading || promptsLoading ? '正在加载资源与创作环节…' : `共 ${visible.length} 张卡片`}
      </p>
      {hasPromptResources && promptError && <p role="alert">{promptError}部分环节尚未加载，搜索结果可能不完整。<button className="btn" onClick={() => setPromptRetry(value => value + 1)}>重新加载创作环节</button></p>}
      {!loading && !promptsLoading && !promptError && visible.length === 0 && (
        <div className={styles.empty}>
          {search || filter !== 'all'
            ? '没有匹配的资源，请调整搜索或筛选条件。'
            : '暂无资源，点击“新建资源”开始添加。'}
        </div>
      )}
      {visiblePrompts.length > 0 && <section aria-labelledby="automatic-prompts-heading">
        <h2 id="automatic-prompts-heading">角色提示词 · 自动生效</h2><p className={styles.hint}>{visiblePrompts.length - commonCount} 个环节提示词 · {commonCount} 项共用补充，共 {visiblePrompts.length} 张卡片</p>
        <p>每张卡片对应一个具体环节，点击后只编辑该环节。共用补充单独列出；进入相应环节时自动使用已发布内容。</p>
        {Object.entries(writingRoles).map(([role, description]) => {
          const group = visiblePrompts.filter(({item}) => 'role' in item.body && item.body.role === role)
          if (!group.length) return null
          return <section key={role} className={styles.promptGroup} aria-label={`${description.name}环节提示词`}>
            <div className={styles.promptGroupHead}><h3>{description.name}</h3><span>{group.length} 张卡片</span></div>
            <p className={styles.hint}>{description.purpose}</p>
            <div className={`${styles.grid} ${styles.resourceGrid}`}>{group.map(({item,prompt}) => resourceCard(item,prompt))}</div>
          </section>
        })}
      </section>}
      {visible.some(({item}) => item.kind === 'reference') && <section aria-labelledby="reference-library-heading" style={{marginTop:32}}>
        <h2 id="reference-library-heading">写作知识库 · AI按需查阅</h2>
        <p>这些是写作方法与示例，无需作者选择。人物设计与关系写法不是本书的人物名单或关系设定；本书实际人物与关系会随创作上下文使用。</p>
        <div className={`${styles.grid} ${styles.resourceGrid}`}>
          {visible.filter(({item}) => item.kind === 'reference').map(({item}) => resourceCard(item))}
        </div>
      </section>}
      <section aria-labelledby="selectable-resources-heading" style={{marginTop:32}}>
        <h2 id="selectable-resources-heading">可选写作资源</h2>
        <p>作者为作品选用后生效，作品保留选定版本，平台更新由作者确认后采用。未配置资源的旧作品沿用原有默认规则。</p>
        <div className={`${styles.grid} ${styles.resourceGrid}`}>
          {visible.filter(({item}) => item.kind !== 'role_prompt' && item.kind !== 'reference').map(({item}) => resourceCard(item))}
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
          title={archiving ? '下架资源' : preview ? '发布预览' : `编辑${selectedPromptTitle ?? (resourceTitle(selected) || '新资源')}`}
          busy={busy}
          onClose={closeEditor}
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
              {selected.kind === 'role_prompt' && <p className="banner banner-warning">本次{preview === 'publish' ? '发布' : '回退'}会更新整个 AI 分工，下列全部环节和共用补充一起生效。请逐项核对后确认。</p>}
              <h3>
                {selected.kind === 'role_prompt' ? `${resourceTitle(selected)}：全部环节与共用补充` : (preview === 'publish' ? resourceTitle(selected) : preview.name)}
              </h3>
              {selected.kind === 'role_prompt' && 'templates' in (preview === 'publish' ? selected.body : preview.body)
                ? <RolePromptFields value={(preview === 'publish' ? selected.body : preview.body) as Extract<ResourceBody, {role:string}>} onReadyChange={setPreviewReady} readOnly />
                : <ResourceContent body={preview === 'publish' ? selected.body : preview.body} />}
              {selected.kind === 'role_prompt' && !previewReady && <p role="status">全部发布内容读取完成后，才可确认发布或回退。</p>}
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
                disabled={busy || (selected.kind === 'role_prompt' && !previewReady)}
                onClick={() => void release()}
              >
                {preview === 'publish' ? '确认发布' : '确认回退'}
              </button>
            </>
          ) : (
            <>
              {selected.kind === 'role_prompt' && <p>当前只编辑“{selectedPromptTitle}”。发布和回退仍按所属 AI 分工统一管理；发布前请核对该分工草稿中的其他修改。</p>}
              <fieldset disabled={busy} className={styles.resourceFields}>
                {selected.kind !== 'role_prompt' && <label>
                  资源名称
                  <input
                    className="input"
                    value={['role_prompt', 'reference'].includes(selected.kind) ? resourceTitle({name, kind:selected.kind}) : name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>}
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
                  ? <RolePromptFields value={JSON.parse(body) as Extract<ResourceBody, {role:string}>} templateId={selectedPromptId ?? undefined} onChange={(value) => setBody(JSON.stringify(value, null, 2))} />
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
                  onClick={closeEditor}
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
                  onClick={() => { setPreviewReady(false); setPreview('publish') }}
                >
                  预览发布
                </button>
              </footer>
              <h3>版本历史</h3>
              {historyStatus === 'loading' && <p role="status">正在读取发布历史…</p>}
              {historyStatus === 'error' && <p className={styles.hint}>发布历史未能加载，请关闭后重新打开此资源重试。</p>}
              {historyStatus === 'ready' && !history.length && (
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
                    onClick={() => { setPreviewReady(false); setPreview(h) }}
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
