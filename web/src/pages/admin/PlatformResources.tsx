import { CreationInput, Disclosure } from './ExecutionContent'
import { useCallback, useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api } from '../../lib/api'
import {
  platformApi,
  type PlatformConfigurationData,
  type PlatformConfigurationInput,
  type PromptRoleTemplates,
} from '../../lib/platformApi'
import { formatApiError } from '../../lib/apiError'
import { composeFields, type GenreCatalogItem, type GenreFields } from '../../lib/genrePacks'
import { GenrePackFields } from '../../components/GenrePackFields'
import { AdminDialog } from './AdminDialog'
import type { AdminOutletContext } from './shared'
import styles from './AdminResources.module.css'

const PROMPTS = [
  { id: 'writer', name: '写作', description: '章节正文、人物动作与叙事表达' },
  { id: 'planner', name: '规划', description: '故事设定、大纲与章节计划' },
  { id: 'validator_l2', name: '语义校验', description: '情节逻辑与设定一致性检查' },
  { id: 'extract', name: '抽取', description: '人物、事件与状态信息抽取' },
  { id: 'audit', name: '审核', description: '内容质量与写作要求审核' },
  { id: 'summarize', name: '摘要', description: '章节内容与长期记忆摘要' },
]
function genreValue(configuration: PlatformConfigurationData, item: GenreCatalogItem): GenreFields {
  const defaults = composeFields(item)
  const overrides = configuration.genre_packs[item.id] ?? {}
  return Object.fromEntries(
    Object.entries(defaults).map(([key, value]) => [key, overrides[key as keyof GenreFields] ?? value]),
  ) as unknown as GenreFields
}
export default function PlatformResources({ kind }: { kind: 'prompts' | 'genres' }) {
  const { onForbidden } = useOutletContext<AdminOutletContext>()
  const [configuration, setConfiguration] = useState<PlatformConfigurationData | null>(null)
  const [promptTemplates, setPromptTemplates] = useState<PromptRoleTemplates[]>([])
  const [catalog, setCatalog] = useState<GenreCatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [prompt, setPrompt] = useState('')
  const [genre, setGenre] = useState<GenreFields | null>(null)
  const [restore, setRestore] = useState(false)
  const isPrompt = kind === 'prompts'
  const title = isPrompt ? '提示词' : '题材包'
  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    setNotice('')
    try {
      const [config, items, templates] = await Promise.all([
        platformApi.getConfiguration(),
        kind === 'genres' ? api.listGenrePacks() : Promise.resolve([]),
        kind === 'prompts' ? platformApi.getPromptTemplates() : Promise.resolve([]),
      ])
      setConfiguration(config)
      setCatalog(items)
      setPromptTemplates(templates)
    } catch (err) {
      if ((err as { status?: number }).status === 403) onForbidden()
      setError(formatApiError(err, '配置加载失败，请重试'))
    } finally {
      setLoading(false)
    }
  }, [kind, onForbidden])
  useEffect(() => {
    void load()
  }, [load])
  function close() {
    setSelected(null)
    setError('')
  }
  function edit(id: string) {
    if (!configuration) return
    setSelected(id)
    setError('')
    setNotice('')
    setRestore(false)
    if (isPrompt) setPrompt(configuration.prompts[id] ?? '')
    else {
      const item = catalog.find((item) => item.id === id)
      if (item) setGenre(genreValue(configuration, item))
    }
  }
  async function save() {
    if (!configuration || !selected) return
    setBusy(true)
    setError('')
    const prompts = { ...configuration.prompts }
    const genrePacks = { ...configuration.genre_packs }
    if (isPrompt) {
      if (prompt.trim()) prompts[selected] = prompt
      else delete prompts[selected]
    } else if (restore) delete genrePacks[selected]
    else if (genre) genrePacks[selected] = genre
    try {
      const saved = await platformApi.updateConfiguration({
        ...configuration,
        prompts,
        genre_packs: genrePacks as PlatformConfigurationInput['genre_packs'],
        model_connections: configuration.model_connections.map((connection) => ({
          id: connection.id,
          name: connection.name,
          protocol: connection.protocol,
          base_url: connection.base_url,
          model: connection.model,
          enabled: connection.enabled,
          user_visible: connection.user_visible,
          input_price: connection.input_price,
          output_price: connection.output_price,
        })),
      })
      setConfiguration(saved)
      setSelected(null)
      setNotice(`${title}已保存`)
      if (!isPrompt) {
        // /genre-packs returns effective values, so refresh after removing overrides.
        // Never allow the old effective catalog to resurrect a removed override.
        setCatalog([])
        setLoading(true)
        try {
          setCatalog(await api.listGenrePacks())
        } catch (err) {
          if ((err as { status?: number }).status === 403) onForbidden()
          setError('题材包已保存，但列表刷新失败，请重新加载配置后继续编辑。')
        } finally {
          setLoading(false)
        }
      }
    } catch (err) {
      if ((err as { status?: number }).status === 403) onForbidden()
      setError(
        (err as { status?: number }).status === 409
          ? '配置已被其他管理员更新，草稿已保留。请取消后重新加载配置，再核对更改。'
          : formatApiError(err, '保存失败，请重试'),
      )
    } finally {
      setBusy(false)
    }
  }
  const cards = isPrompt
    ? PROMPTS.map((role) => ({
        id: role.id,
        name: `${role.name}提示词`,
        group: '平台提示词',
        summary:
          promptTemplates.find((item) => item.role === role.id)?.templates[0]?.content ?? '未读取到内置模板',
        custom: !!configuration?.prompts[role.id],
      }))
    : catalog.map((item) => ({
        id: item.id,
        name: `${item.name}题材包`,
        group: item.group,
        summary: configuration ? genreValue(configuration, item).selling_point : '',
        custom: !!configuration?.genre_packs[item.id],
      }))
  const filtered = cards.filter((card) =>
    `${card.name} ${card.group} ${card.summary}`.toLowerCase().includes(search.trim().toLowerCase()),
  )
  const selectedCard = cards.find((card) => card.id === selected)
  const selectedTemplates = promptTemplates.find((item) => item.role === selected)?.templates ?? []
  return (
    <div className={styles.page}>
      <header className={styles.pageHead}>
        <div>
          <h1>{title}</h1>
          <p>
            {isPrompt
              ? '查看实际内置提示词，管理各创作环节的追加指令。'
              : '管理题材的卖点、流派、节奏与世界设定。'}
          </p>
        </div>
      </header>
      {!selected && error && (
        <p role="alert" className="banner banner-error">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      <div className={styles.toolbar}>
        <input
          className="input"
          aria-label={`搜索${title}`}
          placeholder={`搜索${title}名称或内容`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span>
          {filtered.length} 个{title}
        </span>
        <button className="btn btn-quiet" disabled={loading || busy} onClick={() => void load()}>
          重新加载配置
        </button>
      </div>
      {loading ? (
        <p role="status">正在加载{title}…</p>
      ) : !configuration ? (
        <p className="empty">配置加载失败，请重新加载配置。</p>
      ) : filtered.length === 0 ? (
        <div className={styles.empty}>没有匹配的{title}，请尝试其他关键词。</div>
      ) : (
        <div className={styles.grid}>
          {filtered.map((card) => (
            <button
              type="button"
              key={card.id}
              className={`${styles.card} ${styles.resourceCard}`}
              aria-label={`编辑 ${card.name}`}
              onClick={() => edit(card.id)}
            >
              <span className={styles.cardHead}>
                <span className={styles.provider}>{card.group}</span>
                <span>{card.custom ? (isPrompt ? '内置 + 追加指令' : '已自定义') : '内置内容'}</span>
              </span>
              <strong className={styles.cardTitle}>{card.name}</strong>
              <span className={styles.preview}>{card.summary || '暂无内容，点击编辑'}</span>
              <span className={styles.editHint}>编辑 {isPrompt ? '提示词' : '题材包'} ↗</span>
            </button>
          ))}
        </div>
      )}
      {selectedCard && (
        <AdminDialog title={`编辑${selectedCard.name}`} onClose={close} busy={busy}>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void save()
            }}
          >
            <p className={styles.hint}>
              {isPrompt
                ? '附加指令会与内置提示词一起生效；留空保存可恢复内置提示词。'
                : '保存后用于新建作品，已有作品保留创建时的题材快照。'}
            </p>
            {isPrompt && (
              <section className={styles.templates} aria-label="内置提示词模板">
                <h3>实际内置模板 · {selectedTemplates.length} 个</h3>
                <p className={styles.hint}>
                  内置模板由程序维护，以下为当前工作流使用的真实内容。每次调用还会按任务拼接题材、文风和上下文；建书设定按题材能力使用对应版本。
                </p>
                {selectedTemplates.map((template, index) => (
                  <details key={template.id} open={index === 0}>
                    <summary>{template.title}</summary>
                    <CreationInput value={template.content} system />
                    <Disclosure title="技术诊断"><small>来源：{template.source}</small></Disclosure>
                  </details>
                ))}
              </section>
            )}
            <fieldset className={styles.resourceFields} disabled={busy}>
              {isPrompt ? (
                <label>
                  管理员追加指令
                  <textarea
                    className="textarea"
                    rows={12}
                    maxLength={20000}
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="输入该创作环节的附加要求"
                  />
                </label>
              ) : (
                genre && (
                  <>
                    {!restore && (
                      <GenrePackFields
                        value={genre}
                        onChange={(next) => {
                          setGenre(next)
                          setRestore(false)
                        }}
                      />
                    )}
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => {
                        setRestore((previous) => !previous)
                      }}
                    >
                      {restore ? '撤销恢复' : '恢复内置内容'}
                    </button>
                    {restore && (
                      <p role="status">保存后将移除自定义覆盖并重新加载内置内容，取消不会修改题材包。</p>
                    )}
                  </>
                )
              )}
            </fieldset>
            {error && (
              <p role="alert" className="banner banner-error">
                {error}
              </p>
            )}
            <footer className={styles.actions}>
              <button type="button" className="btn btn-secondary" disabled={busy} onClick={close}>
                取消
              </button>
              <button type="submit" className="btn btn-primary" disabled={busy}>
                {busy ? '保存中…' : `保存${title}`}
              </button>
            </footer>
          </form>
        </AdminDialog>
      )}
    </div>
  )
}
