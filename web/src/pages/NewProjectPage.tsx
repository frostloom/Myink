// 建书向导（§7.11）：书名/题材 + 一句话梗概 → 创建作品 → Planner 生成设定骨架草稿 →
// 可编辑确认 → 落库跳工作台。agent 只提案、用户确认是唯一 canon（§7.11 ③）。
// 布局复用 SettingsPage 的 wrap→rail→main→inner；分区编辑控件对齐 KeyField 风格。
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { api, ApiError, GATE_CODES } from '../lib/api'
import {
  emptySection,
  isSectionEmpty,
  sectionToBody,
  splitDraft,
  type SetupSection,
} from '../lib/bookDraft'
import type { Project } from '../types'
import styles from './NewProjectPage.module.css'

// 题材预设（plan.md §7.11 建书向导；与 seed 4 本示例书对齐）
const GENRES = ['仙侠玄幻', '历史悬疑', '科幻', '都市']

/** 通用「每行一条」文本 ↔ 字符串数组（去空行） */
function linesToArray(text: string): string[] {
  return text
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
}

function arrayToLines(arr: string[]): string {
  return arr.join('\n')
}

/** world_rules 键值编辑器：每行「键：值」（全角/半角冒号首个分隔），值可含冒号 */
function worldRulesToText(wr: Record<string, string>): string {
  return Object.entries(wr)
    .map(([k, v]) => `${k}：${v}`)
    .join('\n')
}

function textToWorldRules(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of text.split('\n')) {
    const s = line.trim()
    if (!s) continue
    const i = s.indexOf('：')
    const j = s.indexOf(':')
    const idx = i === -1 ? j : j === -1 ? i : Math.min(i, j)
    if (idx <= 0) continue
    out[s.slice(0, idx).trim()] = s.slice(idx + 1).trim()
  }
  return out
}

function ApiMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.code) return GATE_CODES[err.code] ?? err.code
  return fallback
}

export default function NewProjectPage() {
  const { logout } = useAuth()
  const navigate = useNavigate()

  const [title, setTitle] = useState('')
  const [genre, setGenre] = useState(GENRES[0])
  const [premise, setPremise] = useState('')
  // 每章目标字数（§6.9 三层字数控制；500–20000，默认 3000）
  const [targetWords, setTargetWords] = useState('3000')
  const [projects, setProjects] = useState<Project[]>([])
  const [pid, setPid] = useState<string | null>(null)
  const [section, setSection] = useState<SetupSection | null>(null)
  const [draftError, setDraftError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  async function createAndDraft() {
    if (!title.trim()) {
      setBanner('请填写书名')
      return
    }
    if (!premise.trim()) {
      setBanner('请填写一句话梗概（创作设定的种子）')
      return
    }
    const words = Number(targetWords)
    if (!Number.isInteger(words) || words < 500 || words > 20000) {
      setBanner('目标字数需为 500–20000 的整数')
      return
    }
    setBusy('create')
    setBanner(null)
    setOk(null)
    try {
      const project = await api.createProject({ title: title.trim(), genre, target_words: words })
      setPid(project.id)
      setProjects(await api.listProjects())
      await regenerate(project.id)
      setOk('作品已创建，设定草稿已生成，可编辑后确认落库')
    } catch (err) {
      setBanner(ApiMessage(err, '创建作品失败，请重试'))
    } finally {
      setBusy(null)
    }
  }

  async function regenerate(forPid: string) {
    setBusy('draft')
    setBanner(null)
    setDraftError(null)
    try {
      const resp = await api.setupDraft(forPid, premise.trim())
      setSection(splitDraft(resp.draft))
      setDraftError(resp.error)
    } catch (err) {
      setBanner(ApiMessage(err, '生成设定草稿失败，请重试'))
    } finally {
      setBusy(null)
    }
  }

  async function confirm() {
    if (!pid || !section) return
    setBusy('confirm')
    setBanner(null)
    setOk(null)
    try {
      await api.confirmSetup(pid, sectionToBody(section))
      setOk('设定已确认落库，进入工作台')
      navigate(`/projects/${pid}`)
    } catch (err) {
      setBanner(ApiMessage(err, '确认落库失败，请重试'))
    } finally {
      setBusy(null)
    }
  }

  const updateSection = (patch: Partial<SetupSection>) =>
    setSection((s) => (s ? { ...s, ...patch } : s))

  const sec = section ?? emptySection()
  const emptyDraft = section !== null && isSectionEmpty(sec)

  return (
    <div className={styles.wrap}>
      <ProjectRail projects={projects} onLogout={logout} />
      <main className={styles.main}>
        <div className={styles.inner}>
          <header className={styles.header}>
            <div>
              <h1>新建作品</h1>
              <div className={styles.crumb}>一句话梗概启动，Planner 提案设定骨架，你确认后落库。</div>
            </div>
          </header>

          {banner && <div className="banner banner-error">{banner}</div>}
          {ok && <div className="banner banner-warning">{ok}</div>}

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>① 作品信息</h2>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>书名</span>
              <input
                className="input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="如《破晓录》"
                maxLength={60}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>题材</span>
              <select className="input" value={genre} onChange={(e) => setGenre(e.target.value)}>
                {GENRES.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
            </label>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>
                每章目标字数
                <span className={styles.hint}>（500–20000，驱动单章长度，默认 3000）</span>
              </span>
              <input
                className="input"
                type="number"
                min={500}
                max={20000}
                step={100}
                value={targetWords}
                onChange={(e) => setTargetWords(e.target.value)}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>一句话梗概</span>
              <textarea
                className="textarea"
                rows={3}
                value={premise}
                onChange={(e) => setPremise(e.target.value)}
                placeholder="如：叛出宗门的少年从北境崛起，追查玉佩背后的真相。"
              />
            </label>
            <div className={styles.saveRow}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy !== null}
                onClick={createAndDraft}
              >
                {busy === 'create' ? '创建中…' : '创建作品'}
              </button>
            </div>
          </section>

          {pid && (
            <section className={`panel ${styles.section}`}>
              <div className={styles.draftHead}>
                <h2 className={styles.sectionTitle}>② 设定骨架草稿</h2>
                <button
                  type="button"
                  className="btn btn-quiet"
                  disabled={busy !== null}
                  onClick={() => regenerate(pid)}
                >
                  {busy === 'draft' ? '重新生成中…' : '重新生成草稿'}
                </button>
              </div>
              <p className={styles.hint}>
                由 Planner 按你的梗概生成（境界体系 / 世界观 / 硬约束 / 势力 / 核心人物 / 关键地点）。
                草稿只是提案，可直接编辑，确认后落库生效。
              </p>
              {draftError && (
                <div className="banner banner-warning">LLM 生成降级：{draftError}（可手填后确认）</div>
              )}
              {section === null ? (
                <div className="empty">正在生成设定草稿…</div>
              ) : emptyDraft ? (
                <div className="empty">草稿为空（LLM 未产出），请手动填写以下分区。</div>
              ) : null}

              {section !== null && (
                <div>
                  <div className={styles.block}>
                    <span className={styles.fieldLabel}>境界体系（每行一阶）</span>
                    <textarea
                      className="textarea"
                      rows={Math.max(3, sec.realm_order.length)}
                      value={arrayToLines(sec.realm_order)}
                      onChange={(e) => updateSection({ realm_order: linesToArray(e.target.value) })}
                    />
                  </div>
                  <div className={styles.block}>
                    <span className={styles.fieldLabel}>世界观规则（每行「键：值」）</span>
                    <textarea
                      className="textarea"
                      rows={Math.max(3, Object.keys(sec.world_rules).length)}
                      value={worldRulesToText(sec.world_rules)}
                      onChange={(e) => updateSection({ world_rules: textToWorldRules(e.target.value) })}
                    />
                  </div>
                  <div className={styles.block}>
                    <span className={styles.fieldLabel}>硬约束（每行一条）</span>
                    <textarea
                      className="textarea"
                      rows={Math.max(3, sec.hard_constraints.length)}
                      value={arrayToLines(sec.hard_constraints)}
                      onChange={(e) => updateSection({ hard_constraints: linesToArray(e.target.value) })}
                    />
                  </div>

                  <div className={styles.block}>
                    <span className={styles.fieldLabel}>势力</span>
                    {sec.forces.map((f, i) => (
                      <div key={i} className={styles.rowGrid}>
                        <input
                          className="input"
                          placeholder="名称"
                          value={f.name}
                          onChange={(e) =>
                            updateSection({
                              forces: sec.forces.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)),
                            })
                          }
                        />
                        <input
                          className="input"
                          placeholder="立场"
                          value={f.stance}
                          onChange={(e) =>
                            updateSection({
                              forces: sec.forces.map((x, j) =>
                                j === i ? { ...x, stance: e.target.value } : x,
                              ),
                            })
                          }
                        />
                        <button
                          type="button"
                          className="btn btn-quiet"
                          onClick={() =>
                            updateSection({ forces: sec.forces.filter((_, j) => j !== i) })
                          }
                        >
                          删
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      className="btn btn-quiet"
                      onClick={() =>
                        updateSection({ forces: [...sec.forces, { name: '', stance: '', resources: [] }] })
                      }
                    >
                      + 添加势力
                    </button>
                  </div>

                  <div className={styles.block}>
                    <span className={styles.fieldLabel}>核心人物</span>
                    {sec.characters.map((c, i) => (
                      <div key={i} className={styles.charGrid}>
                        <input
                          className="input"
                          placeholder="姓名"
                          value={c.name}
                          onChange={(e) =>
                            updateSection({
                              characters: sec.characters.map((x, j) =>
                                j === i ? { ...x, name: e.target.value } : x,
                              ),
                            })
                          }
                        />
                        <input
                          className="input"
                          placeholder="境界上限"
                          value={c.realm_cap}
                          onChange={(e) =>
                            updateSection({
                              characters: sec.characters.map((x, j) =>
                                j === i ? { ...x, realm_cap: e.target.value } : x,
                              ),
                            })
                          }
                        />
                        <input
                          className="input"
                          placeholder="出身"
                          value={c.origin}
                          onChange={(e) =>
                            updateSection({
                              characters: sec.characters.map((x, j) =>
                                j === i ? { ...x, origin: e.target.value } : x,
                              ),
                            })
                          }
                        />
                        <button
                          type="button"
                          className="btn btn-quiet"
                          onClick={() =>
                            updateSection({ characters: sec.characters.filter((_, j) => j !== i) })
                          }
                        >
                          删
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      className="btn btn-quiet"
                      onClick={() =>
                        updateSection({
                          characters: [
                            ...sec.characters,
                            { name: '', role: '', race: '', origin: '', realm_cap: '', personality: '' },
                          ],
                        })
                      }
                    >
                      + 添加人物
                    </button>
                  </div>

                  <div className={styles.block}>
                    <span className={styles.fieldLabel}>关键地点</span>
                    {sec.locations.map((l, i) => (
                      <div key={i} className={styles.rowGrid}>
                        <input
                          className="input"
                          placeholder="名称"
                          value={l.name}
                          onChange={(e) =>
                            updateSection({
                              locations: sec.locations.map((x, j) =>
                                j === i ? { name: e.target.value } : x,
                              ),
                            })
                          }
                        />
                        <button
                          type="button"
                          className="btn btn-quiet"
                          onClick={() =>
                            updateSection({ locations: sec.locations.filter((_, j) => j !== i) })
                          }
                        >
                          删
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      className="btn btn-quiet"
                      onClick={() => updateSection({ locations: [...sec.locations, { name: '' }] })}
                    >
                      + 添加地点
                    </button>
                  </div>

                  <div className={styles.saveRow}>
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={busy !== null}
                      onClick={confirm}
                    >
                      {busy === 'confirm' ? '确认中…' : '确认落库'}
                    </button>
                  </div>
                </div>
              )}
            </section>
          )}
        </div>
      </main>
    </div>
  )
}
