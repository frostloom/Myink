// 建书向导（§7.11）：书名/题材 + 一句话梗概 → 创建作品 → Planner 生成设定骨架草稿 →
// 可编辑确认 → 落库跳工作台。agent 只提案、用户确认是唯一 canon（§7.11 ③）。
// 布局复用 SettingsPage 的 wrap→rail→main→inner；分区编辑控件对齐 KeyField 风格。
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { RankingsPanel } from '../components/RankingsPanel'
import { useAuth } from '../context/AuthContext'
import { api, ApiError, GATE_CODES } from '../lib/api'
import { GENRE_SUGGESTIONS, parseGenres, toggleGenre } from '../lib/genres'
import {
  emptySection,
  isSectionEmpty,
  sectionToBody,
  splitDraft,
  type SetupSection,
} from '../lib/bookDraft'
import type { BookOutline, OutlineChapter, OutlineVolume, Project } from '../types'
import styles from './NewProjectPage.module.css'

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
  // 已落库的书名（AI 起名/用户填写后确认）；书名留空时由 Planner 在设定草稿带 title 建议
  const [savedTitle, setSavedTitle] = useState('')
  const [genre, setGenre] = useState('')
  const [premise, setPremise] = useState('')
  // 每章目标字数（§6.9 三层字数控制；500–20000，默认 3000）
  const [targetWords, setTargetWords] = useState('3000')
  const [projects, setProjects] = useState<Project[]>([])
  const [pid, setPid] = useState<string | null>(null)
  const [section, setSection] = useState<SetupSection | null>(null)
  const [draftError, setDraftError] = useState<string | null>(null)
  // ③ 整书大纲（§11）：设定确认落库后出现；梗概 + 大致章节数 + 大致故事线 → Planner 提案
  const [setupConfirmed, setSetupConfirmed] = useState(false)
  const [outlineCount, setOutlineCount] = useState('20')
  const [outlineStoryline, setOutlineStoryline] = useState('')
  const [outline, setOutline] = useState<BookOutline | null>(null)
  const [outlineError, setOutlineError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)

  async function createAndDraft() {
    const brief = premise.trim()
    if (!brief) {
      setBanner('请填写创作简报（设定与大纲的种子）')
      return
    }
    const words = Number(targetWords)
    if (!Number.isInteger(words) || words < 500 || words > 20000) {
      setBanner('目标字数需为 500–20000 的整数')
      return
    }
    const finalTitle = title.trim() || '未命名作品'
    setBusy('create')
    setBanner(null)
    setOk(null)
    try {
      const project = await api.createProject({ title: finalTitle, genre, target_words: words })
      setPid(project.id)
      setSavedTitle(finalTitle)
      setProjects(await api.listProjects())
      // InkOS 风格一键建书：设定草稿 + 整书大纲草稿并行生成（outline 只读 genre/premise，无需等设定确认）
      await Promise.all([regenerate(project.id), generateOutline(project.id)])
      setOk('作品已创建，设定与整书大纲草稿已生成，可编辑后确认')
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
      // AI 起名（InkOS --title 可选同款）：书名留空时 Planner 在设定草稿带 title 建议，创建后回写
      const aiTitle = typeof resp.draft.title === 'string' ? resp.draft.title.trim() : ''
      if (!title.trim() && aiTitle) {
        setTitle(aiTitle)
        setSavedTitle(aiTitle)
        try {
          await api.updateProject(forPid, { title: aiTitle })
        } catch {
          /* 标题是标签，回写失败静默（不阻塞草稿生成） */
        }
      }
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
      await syncTitle()
      setSetupConfirmed(true)
      setOk('设定已确认落库，可继续检查整书大纲（第 ③ 步）')
    } catch (err) {
      setBanner(ApiMessage(err, '确认落库失败，请重试'))
    } finally {
      setBusy(null)
    }
  }

  // ③ 整书大纲：Planner 按目标章节数分卷提案 Objective + 卷 + 逐章；草稿不落库，确认后 PUT 整体替换。
  async function generateOutline(forPid: string) {
    const cc = Number(outlineCount)
    if (!Number.isInteger(cc) || cc < 1 || cc > 200) {
      setBanner('大致章节数需为 1–200 的整数')
      return
    }
    setBusy('outline-draft')
    setBanner(null)
    setOutlineError(null)
    try {
      const resp = await api.outlineDraft(forPid, {
        premise: premise.trim(),
        chapter_count: cc,
        storyline: outlineStoryline.trim(),
      })
      // 降级时 outline 为 {} → 归一为空结构，保证可编辑面板始终可渲染。
      setOutline({
        objective: typeof resp.outline.objective === 'string' ? resp.outline.objective : '',
        volumes: Array.isArray(resp.outline.volumes) ? resp.outline.volumes : [],
      })
      setOutlineError(resp.error)
    } catch (err) {
      setBanner(ApiMessage(err, '生成大纲失败，请重试'))
    } finally {
      setBusy(null)
    }
  }

  /** 输入框书名与已落库书名不同步时回写（输入框为 canon；AI 起名/手动改名后生效） */
  async function syncTitle() {
    if (!pid) return
    const t = title.trim()
    if (t && t !== savedTitle) {
      await api.updateProject(pid, { title: t })
      setSavedTitle(t)
    }
  }

  /** 大纲确认落库（单独确认 / 确认全部共用） */
  async function persistOutline() {
    if (!pid || !outline) return
    const totalChapters = outline.volumes.reduce((n, v) => n + v.chapters.length, 0)
    await api.confirmOutline(pid, {
      objective: outline.objective,
      volumes: outline.volumes.map((v) => ({
        title: v.title,
        theme: v.theme ?? '',
        goal: v.goal,
        key_results: v.key_results ?? [],
        end_event: v.end_event ?? '',
        chapters: v.chapters.map((c) => ({ title: c.title, goal: c.goal, beats: c.beats ?? [] })),
      })),
      premise: premise.trim(),
      chapter_count: Number(outlineCount) || totalChapters,
      storyline: outlineStoryline.trim(),
    })
    await syncTitle()
  }

  async function confirmOutline() {
    if (!pid || !outline) return
    setBusy('outline-confirm')
    setBanner(null)
    setOk(null)
    try {
      await persistOutline()
      setOk('整书大纲已落库，进入工作台')
      navigate(`/projects/${pid}`)
    } catch (err) {
      setBanner(ApiMessage(err, '确认大纲失败，请重试'))
    } finally {
      setBusy(null)
    }
  }

  /** 确认全部并进入工作台（InkOS 风格一次落地）：设定未确认先落，再落大纲，再进入 */
  async function confirmAll() {
    if (!pid) return
    setBusy('confirm-all')
    setBanner(null)
    setOk(null)
    try {
      if (!setupConfirmed && section) {
        await api.confirmSetup(pid, sectionToBody(section))
        setSetupConfirmed(true)
      }
      if (outline) await persistOutline()
      await syncTitle()
      setOk('设定与整书大纲已落库，进入工作台')
      navigate(`/projects/${pid}`)
    } catch (err) {
      setBanner(ApiMessage(err, '确认失败，请重试'))
    } finally {
      setBusy(null)
    }
  }

  /** 暂不规划直接进入：先同步书名再跳转 */
  async function enterWorkspace() {
    if (!pid) return
    try {
      await syncTitle()
    } catch {
      /* 标题同步失败不阻塞进入 */
    }
    navigate(`/projects/${pid}`)
  }

  const updateOutline = (patch: Partial<BookOutline>) =>
    setOutline((o) => (o ? { ...o, ...patch } : o))

  const updateVolume = (vi: number, patch: Partial<OutlineVolume>) =>
    setOutline((o) =>
      o
        ? { ...o, volumes: o.volumes.map((v, j) => (j === vi ? { ...v, ...patch } : v)) }
        : o,
    )

  const updateChapter = (vi: number, ci: number, patch: Partial<OutlineChapter>) =>
    setOutline((o) =>
      o
        ? {
            ...o,
            volumes: o.volumes.map((v, j) =>
              j === vi
                ? { ...v, chapters: v.chapters.map((c, k) => (k === ci ? { ...c, ...patch } : c)) }
                : v,
            ),
          }
        : o,
    )

  const removeChapter = (vi: number, ci: number) =>
    setOutline((o) =>
      o
        ? {
            ...o,
            volumes: o.volumes.map((v, j) =>
              j === vi ? { ...v, chapters: v.chapters.filter((_, k) => k !== ci) } : v,
            ),
          }
        : o,
    )

  const addChapter = (vi: number) =>
    setOutline((o) =>
      o
        ? {
            ...o,
            volumes: o.volumes.map((v, j) =>
              j === vi ? { ...v, chapters: [...v.chapters, { title: '', goal: '', beats: [] }] } : v,
            ),
          }
        : o,
    )

  const addVolume = () =>
    setOutline((o) =>
      o
        ? {
            ...o,
            volumes: [
              ...o.volumes,
              {
                title: `第 ${o.volumes.length + 1} 卷`,
                goal: '',
                chapters: [{ title: '', goal: '' }],
              },
            ],
          }
        : o,
    )

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
              <div className={styles.crumb}>创作简报启动，AI 生成设定骨架与整书大纲，你确认后落库。</div>
            </div>
          </header>

          {banner && <div className="banner banner-error">{banner}</div>}
          {ok && <div className="banner banner-warning">{ok}</div>}

          {/* 扫榜灵感（§10）：建书前的题材风向参考，全局端点；不注入任何生成节点 */}
          <RankingsPanel />

          <section className={`panel ${styles.section}`}>
            <h2 className={styles.sectionTitle}>① 作品信息</h2>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>书名</span>
              <input
                className="input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="如《破晓录》，留空由 AI 起名"
                maxLength={60}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>
                题材
                <span className={styles.hint}>（自由输入，或点下方标签组合，可叠加如「都市修仙」）</span>
              </span>
              <input
                className="input"
                value={genre}
                onChange={(e) => setGenre(e.target.value)}
                placeholder="如：都市修仙"
                maxLength={64}
              />
              <div className={styles.genreChips}>
                {GENRE_SUGGESTIONS.map((g) => {
                  const on = parseGenres(genre).includes(g)
                  return (
                    <button
                      key={g}
                      type="button"
                      className={styles.chip + (on ? ' ' + styles.chipOn : '')}
                      onClick={() => setGenre(toggleGenre(genre, g))}
                    >
                      {g}
                    </button>
                  )
                })}
              </div>
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
              <span className={styles.fieldLabel}>创作简报</span>
              <textarea
                className="textarea"
                rows={5}
                value={premise}
                onChange={(e) => setPremise(e.target.value)}
                placeholder={
                  '写你的脑洞，越具体越好：题材、主角身份、金手指、世界观、关键冲突或想要的结局。\n' +
                  '例：都市修仙，主角是个程序员，靠解析代码的方式理解修仙功法。\n' +
                  '或：被逐出宗门的外门弟子，带着一枚能推演因果的玉佩，从北境一路查清父母死因并证道。'
                }
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

          {pid && (
            <section className={`panel ${styles.section}`}>
              <div className={styles.draftHead}>
                <h2 className={styles.sectionTitle}>③ 整书大纲</h2>
                <button
                  type="button"
                  className="btn btn-quiet"
                  disabled={busy !== null}
                  onClick={() => pid && generateOutline(pid)}
                >
                  {busy === 'outline-draft' ? '生成中…' : outline ? '重新生成大纲' : '生成大纲'}
                </button>
              </div>
              <p className={styles.hint}>
                按梗概（与可选的补充故事线，不填则 Planner 自动推导）把全书划成 3-5 卷（起/承/转/合），
                产出「全书 Objective → 卷 → 逐章目标 + 细纲节拍」骨架。每章写作注入所属卷目标、
                关键结果与本章细纲，从源头区分各章开头（不靠上一章开头避雷），可编辑后确认。
              </p>
              {outlineError && (
                <div className="banner banner-warning">LLM 生成降级：{outlineError}（可手填后确认）</div>
              )}
              <div className={styles.block}>
                <span className={styles.fieldLabel}>大致章节数（1–200）</span>
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={200}
                  value={outlineCount}
                  onChange={(e) => setOutlineCount(e.target.value)}
                />
              </div>
              <details className={styles.block}>
                <summary className={styles.fieldLabel}>
                  补充故事线（可选，不填则由 Planner 自动推导）
                </summary>
                <textarea
                  className="textarea"
                  rows={2}
                  value={outlineStoryline}
                  onChange={(e) => setOutlineStoryline(e.target.value)}
                  placeholder="如：前期入宗立身，中期追查玉佩真相，后期宗门惊变、决战北境。"
                />
              </details>
              {outline && (
                <div>
                  <div className={styles.block}>
                    <span className={styles.fieldLabel}>全书 Objective（终局，可验证状态）</span>
                    <textarea
                      className="textarea"
                      rows={2}
                      value={outline.objective}
                      onChange={(e) => updateOutline({ objective: e.target.value })}
                      placeholder="如：从杂役修士成为宗门长老并公开父辈冤案真相"
                    />
                  </div>
                  {outline.volumes.map((v, vi) => {
                    const base = outline.volumes
                      .slice(0, vi)
                      .reduce((n, pv) => n + pv.chapters.length, 0)
                    return (
                      <div key={vi} className={`${styles.block} ${styles.volumeBlock}`}>
                        <div className={styles.rowGrid}>
                          <span className={styles.fieldLabel}>
                            第 {vi + 1} 卷 · 共 {v.chapters.length} 章
                          </span>
                          <input
                            className="input"
                            placeholder="卷名"
                            value={v.title}
                            onChange={(e) => updateVolume(vi, { title: e.target.value })}
                          />
                        </div>
                        <div className={styles.rowGrid}>
                          <span className={styles.fieldLabel}>主题</span>
                          <input
                            className="input"
                            value={v.theme ?? ''}
                            placeholder="一句话主题"
                            onChange={(e) => updateVolume(vi, { theme: e.target.value })}
                          />
                        </div>
                        <textarea
                          className="textarea"
                          rows={1}
                          placeholder="卷目标（本卷结束时主角须达到的可验证状态）"
                          value={v.goal}
                          onChange={(e) => updateVolume(vi, { goal: e.target.value })}
                        />
                        <textarea
                          className="textarea"
                          rows={1}
                          placeholder="关键结果 KR（每行一条，每 3-5 章推进一个）"
                          value={arrayToLines(v.key_results ?? [])}
                          onChange={(e) => updateVolume(vi, { key_results: linesToArray(e.target.value) })}
                        />
                        <textarea
                          className="textarea"
                          rows={1}
                          placeholder="卷末不可逆事件（只写事件，不写第几章）"
                          value={v.end_event ?? ''}
                          onChange={(e) => updateVolume(vi, { end_event: e.target.value })}
                        />
                        {v.chapters.map((c, ci) => (
                          <div key={ci} className={styles.block}>
                            <div className={styles.rowGrid}>
                              <span className={styles.fieldLabel}>第 {base + ci + 1} 章</span>
                              <input
                                className="input"
                                placeholder="章名"
                                value={c.title}
                                onChange={(e) => updateChapter(vi, ci, { title: e.target.value })}
                              />
                              <button
                                type="button"
                                className="btn btn-quiet"
                                onClick={() => removeChapter(vi, ci)}
                              >
                                删
                              </button>
                            </div>
                            <textarea
                              className="textarea"
                              rows={1}
                              placeholder="本章目标（会注入本章写作）"
                              value={c.goal}
                              onChange={(e) => updateChapter(vi, ci, { goal: e.target.value })}
                            />
                            <textarea
                              className="textarea"
                              rows={Math.max(1, c.beats?.length ?? 0)}
                              placeholder="细纲节拍（每行一条：谁 + 在何处 + 做什么 + 导致什么 + 章末钩子，注入本章写作）"
                              value={arrayToLines(c.beats ?? [])}
                              onChange={(e) =>
                                updateChapter(vi, ci, { beats: linesToArray(e.target.value) })
                              }
                            />
                          </div>
                        ))}
                        <button type="button" className="btn btn-quiet" onClick={() => addChapter(vi)}>
                          + 本卷加一章
                        </button>
                      </div>
                    )
                  })}
                  <div className={styles.saveRow}>
                    <button type="button" className="btn btn-quiet" disabled={busy !== null} onClick={addVolume}>
                      + 新增一卷
                    </button>
                    <button
                      type="button"
                      className="btn btn-quiet"
                      disabled={busy !== null}
                      onClick={confirmOutline}
                    >
                      {busy === 'outline-confirm' ? '确认中…' : '仅确认大纲并进入'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={busy !== null}
                      onClick={confirmAll}
                    >
                      {busy === 'confirm-all' ? '确认中…' : '确认设定与大纲并进入工作台'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-quiet"
                      disabled={busy !== null}
                      onClick={enterWorkspace}
                    >
                      暂不规划，直接进入
                    </button>
                  </div>
                </div>
              )}
              {!outline && (
                <div className={styles.saveRow}>
                  <button
                    type="button"
                    className="btn btn-quiet"
                    disabled={busy !== null}
                    onClick={enterWorkspace}
                  >
                    暂不规划，直接进入工作台
                  </button>
                </div>
              )}
            </section>
          )}
        </div>
      </main>
    </div>
  )
}
