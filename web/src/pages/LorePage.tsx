// 设定浏览页（§7.11）：人物卡片（静态基底 + 当前状态台账）+ 世界观（realm_order 阶段箭头）+
// 硬约束 + 势力/地点。数据 GET world + GET characters 并行；无设定 → 空态不报错。
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { api, ApiError } from '../lib/api'
import type { CharacterCard, Project, WorldView } from '../types'
import styles from './LorePage.module.css'

/** realm_order 渲染为阶段箭头列表（对齐 seed world_rules.realm_order 口径） */
function RealmOrder({ value }: { value: unknown }) {
  const list = Array.isArray(value) ? value.map((x) => String(x)).filter(Boolean) : []
  if (list.length === 0) return null
  return (
    <div className={styles.realmOrder}>
      {list.map((r, i) => (
        <span key={i} className={styles.realmStep}>
          <span className={styles.realmItem}>{r}</span>
          {i < list.length - 1 && <span className={styles.realmArrow}>→</span>}
        </span>
      ))}
    </div>
  )
}

/** 世界观键值（跳过 realm_order——已单独渲染） */
function WorldRules({ world_rules }: { world_rules: Record<string, unknown> }) {
  const entries = Object.entries(world_rules).filter(([k]) => k !== 'realm_order')
  if (entries.length === 0) return <div className="empty">暂无世界观规则。</div>
  return (
    <dl className={styles.ruleList}>
      {entries.map(([k, v]) => (
        <div key={k} className={styles.ruleRow}>
          <dt className={styles.ruleKey}>{k}</dt>
          <dd className={styles.ruleVal}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
        </div>
      ))}
    </dl>
  )
}

function CharacterCardBlock({
  card,
  expanded,
  onToggle,
}: {
  card: CharacterCard
  expanded: boolean
  onToggle: () => void
}) {
  const stateRows = Object.entries(card.state)
  return (
    <article className={`panel ${styles.card}`}>
      <button type="button" className={styles.cardHead} onClick={onToggle}>
        <span className={styles.cardName}>{card.name}</span>
        <span className="badge badge-accent">{card.realm_cap}</span>
        {card.race && <span className="badge">{card.race}</span>}
        <span className={styles.cardArrow}>{expanded ? '▾' : '▸'}</span>
      </button>
      {expanded && (
        <div className={styles.cardBody}>
          <dl className={styles.cardMeta}>
            {card.origin && (
              <>
                <dt>出身</dt>
                <dd>{card.origin}</dd>
              </>
            )}
            {card.personality && (
              <>
                <dt>性格</dt>
                <dd>{card.personality}</dd>
              </>
            )}
          </dl>
          {Object.keys(card.base_attrs).length > 0 && (
            <div className={styles.cardMeta}>
              <span className={styles.cardLabel}>基础属性</span>
              <code className={styles.readonly}>{JSON.stringify(card.base_attrs)}</code>
            </div>
          )}
          <span className={styles.cardLabel}>当前状态（§7.7 台账）</span>
          {stateRows.length === 0 ? (
            <div className="empty">暂无状态记录。</div>
          ) : (
            <dl className={styles.cardMeta}>
              {stateRows.map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}
    </article>
  )
}

export default function LorePage() {
  const { projectId = '' } = useParams()
  const { logout } = useAuth()

  const [projects, setProjects] = useState<Project[]>([])
  const [world, setWorld] = useState<WorldView | null>(null)
  const [characters, setCharacters] = useState<CharacterCard[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [banner, setBanner] = useState<string | null>(null)

  const load = useCallback(async () => {
    setBanner(null)
    try {
      const [proj, w, ch] = await Promise.all([
        api.listProjects(),
        api.getWorld(projectId),
        api.getCharacters(projectId),
      ])
      setProjects(proj)
      setWorld(w)
      setCharacters(ch)
    } catch (err) {
      setBanner(err instanceof ApiError ? err.code : '设定加载失败')
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <div className={styles.wrap}>
      <ProjectRail projects={projects} onLogout={logout} />
      <main className={styles.main}>
        <div className={styles.inner}>
          <header className={styles.header}>
            <div>
              <h1>设定</h1>
              <div className={styles.crumb}>
                <Link to={`/projects/${projectId}`}>返回工作台</Link>
              </div>
            </div>
          </header>

          {banner && <div className="banner banner-error">{banner}</div>}
          {!world && !banner && <div className="empty">加载中…</div>}

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>人物卡片</h2>
            {characters.length === 0 ? (
              <div className="empty">暂无人物。可在「新建作品」设定或后续章节抽取中建立。</div>
            ) : (
              <div className={styles.cardGrid}>
                {characters.map((c) => (
                  <CharacterCardBlock
                    key={c.id}
                    card={c}
                    expanded={expanded.has(c.id)}
                    onToggle={() => toggle(c.id)}
                  />
                ))}
              </div>
            )}
          </section>

          {world && (
            <>
              <section className={`panel ${styles.section}`}>
                <h2 className={styles.sectionTitle}>世界观</h2>
                <RealmOrder value={world.world_rules.realm_order} />
                <WorldRules world_rules={world.world_rules} />
              </section>

              <section className={`panel ${styles.section}`}>
                <h2 className={styles.sectionTitle}>硬约束</h2>
                {world.hard_constraints.length === 0 ? (
                  <div className="empty">暂无硬约束。</div>
                ) : (
                  <ul className={styles.constraintList}>
                    {world.hard_constraints.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                )}
              </section>

              <section className={`panel ${styles.section}`}>
                <h2 className={styles.sectionTitle}>势力与地点</h2>
                <div className={styles.twoCol}>
                  <div>
                    <h3 className={styles.subTitle}>势力</h3>
                    {world.factions.length === 0 ? (
                      <div className="empty">暂无势力。</div>
                    ) : (
                      <ul className={styles.factionList}>
                        {world.factions.map((f) => (
                          <li key={f.name}>
                            <span className={styles.factionName}>{f.name}</span>
                            {f.stance && <span className={styles.factionStance}>{f.stance}</span>}
                            {f.resources.length > 0 && (
                              <span className={styles.factionResources}>资源：{f.resources.join('、')}</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div>
                    <h3 className={styles.subTitle}>地点</h3>
                    {world.locations.length === 0 ? (
                      <div className="empty">暂无地点。</div>
                    ) : (
                      <ul className={styles.locationList}>
                        {world.locations.map((l) => (
                          <li key={l.name}>{l.name}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  )
}
