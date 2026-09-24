// 建书向导（§7.11）：书名/题材 + 一句话梗概 → 创建作品 → Planner 生成设定骨架草稿 →
// 可编辑确认 → 落库跳工作台。agent 只提案、用户确认是唯一 canon（§7.11 ③）。
// 布局复用 SettingsPage 的 wrap→rail→main→inner；分区编辑控件对齐 KeyField 风格。
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { RankingsPanel } from '../components/RankingsPanel'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import { isProjectDraft } from '../lib/projectCreation'
import { styleLibraryApi, type StyleLibraryItem } from '../lib/styleLibraryApi'
import { GenrePackFields } from '../components/GenrePackFields'
import {
  composeFields,
  displayGenre,
  emptyFields,
  groupCatalog,
  type GenreCatalogItem,
  type GenreFields,
} from '../lib/genrePacks'
import {
  emptySection,
  isSectionEmpty,
  sectionToBody,
  splitDraft,
  type SetupSection,
} from '../lib/bookDraft'
import type { BookOutline, OutlineChapter, OutlineStage, OutlineVolume, Project } from '../types'
import styles from './NewProjectPage.module.css'

const PENDING_PROJECT_CREATION_KEY = 'myink.pending-project-creation'

// 短篇形态参数（docs/SHORT-FORM.md §5）：长篇的章数/每章字数区间与短篇不同，
// 全篇总量上限决定后端会不会把每章字数压下来，压了就得告诉用户。
const SHORT_CHAPTER_MIN = 1
const SHORT_CHAPTER_MAX = 10
const SHORT_CHARS_MIN = 1000
const SHORT_CHARS_MAX = 8000
const SHORT_TOTAL_MAX = 20000

function pendingProjectCreationId(): string {
  const existing = window.sessionStorage.getItem(PENDING_PROJECT_CREATION_KEY)
  if (existing) return existing
  const created = window.crypto.randomUUID()
  window.sessionStorage.setItem(PENDING_PROJECT_CREATION_KEY, created)
  return created
}

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

function chapterRangeLabel(start?: number, end?: number): string {
  return start && end ? `第 ${start}–${end} 章` : ''
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
  return formatApiError(err, fallback)
}

/** 形态由入口决定（/long/new 或 /short/new）；草稿恢复时以服务端记的形态为准。 */
export default function NewProjectPage({ form: routeForm = 'long' }: { form?: 'long' | 'short' }) {
  const { session, logout } = useAuth()
  const guest = useGuest()
  const token = session?.token ?? ''
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const resumeId = searchParams.get('draft')
  const currentPid = useRef<string | null>(null)

  const [title, setTitle] = useState('')
  // 已落库的书名（AI 起名/用户填写后确认）；书名留空时由 Planner 在设定草稿带 title 建议
  const [savedTitle, setSavedTitle] = useState('')
  const [catalog, setCatalog] = useState<GenreCatalogItem[]>([])
  const [primaryId, setPrimaryId] = useState<string | null>(null)
  const [secondaryId, setSecondaryId] = useState<string | null>(null)
  const [genreFields, setGenreFields] = useState<GenreFields>(emptyFields())
  const [premise, setPremise] = useState('')
  // 作品形态：短篇走另一条生成管道（整篇一次成稿），章数/每章字数的区间都不同
  const [form, setForm] = useState<'long' | 'short'>(routeForm)
  // 每章目标字数（§6.9 三层字数控制；500–20000，默认 3000）
  const [targetWords, setTargetWords] = useState('3000')
  // 短篇每章字数（1000–8000；全篇总量超上限时后端会压下来并回传提示）
  const [shortChars, setShortChars] = useState('2000')
  const [projects, setProjects] = useState<Project[]>([])
  const [pid, setPid] = useState<string | null>(null)
  const [section, setSection] = useState<SetupSection | null>(null)
  const [draftError, setDraftError] = useState<string | null>(null)
  // ③ 整书大纲（§11）：设定确认落库后出现；梗概 + 大致章节数 + 大致故事线 → Planner 提案
  const [setupConfirmed, setSetupConfirmed] = useState(false)
  const [outlineCount, setOutlineCount] = useState('200')
  const [outlineStoryline, setOutlineStoryline] = useState('')
  const [outline, setOutline] = useState<BookOutline | null>(null)
  const [outlineError, setOutlineError] = useState<string | null>(null)
  // 短篇方案的服务端回执：字数被压到多少（null = 没压过）、审纲留了改稿痕（都要让用户看见，§8 风险）
  const [compressedChars, setCompressedChars] = useState<number | null>(null)
  const [outlineWarning, setOutlineWarning] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(resumeId ? 'restore' : null)
  const [banner, setBanner] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  // 建书时选文风（可选）：列表来自账号文风库，值原样交给后端解析（内置预设是 "builtin:<id>"）
  const [styleItems, setStyleItems] = useState<StyleLibraryItem[]>([])
  const [styleItemId, setStyleItemId] = useState('')

  useEffect(() => {
    if (guest) {
      setProjects([])
      return
    }
    void api.listProjects().then(setProjects).catch(() => {})
    void api.listGenrePacks().then(setCatalog).catch(() => {
      setBanner('题材目录加载失败，可先不选题材创建')
    })
    // 拿不到文风列表就当没有：这一步可选，不该因为一个附带请求失败就挡住建书。
    void styleLibraryApi.list(token).then((out) => setStyleItems(out.items))
      .catch(() => setStyleItems([]))
  }, [guest, token])

  useEffect(() => {
    // 游客不进建书向导：题材目录、草稿恢复都是需要凭据的请求，一律不发。
    if (guest) {
      setBusy(null)
      return
    }
    if (resumeId && currentPid.current === resumeId) return
    let disposed = false
    currentPid.current = null
    setPid(null)
    setTitle('')
    setSavedTitle('')
    setPrimaryId(null)
    setSecondaryId(null)
    setGenreFields(emptyFields())
    setPremise('')
    setForm(routeForm)
    setTargetWords('3000')
    setShortChars('2000')
    setStyleItemId('')
    setSection(null)
    setDraftError(null)
    setSetupConfirmed(false)
    // 章数初值必须落在本形态的区间里：短篇是 1–10，长篇的 200 会被后端章数校验挡下。
    setOutlineCount(routeForm === 'short' ? '5' : '200')
    setOutlineStoryline('')
    setOutline(null)
    setOutlineError(null)
    setCompressedChars(null)
    setOutlineWarning(null)
    setBanner(null)
    setOk(null)
    setBusy(resumeId ? 'restore' : null)
    if (!resumeId) return () => { disposed = true }
    void api.getCreation(resumeId).then(({ project, context }) => {
      if (disposed) return
      if (!isProjectDraft(project)) {
        navigate(`/projects/${project.id}`, { replace: true })
        return
      }
      currentPid.current = project.id
      setPid(project.id)
      setTitle(project.title)
      setSavedTitle(project.title)
      const resolvedForm = project.form ?? context.form ?? routeForm
      setForm(resolvedForm)
      setTargetWords(String(project.target_words ?? 3000))
      setShortChars(String(context.chars_per_chapter ?? 2000))
      setPremise(context.premise ?? '')
      setOutlineCount(String(context.chapter_count ?? (resolvedForm === 'short' ? 5 : 200)))
      setOutlineStoryline(context.storyline ?? '')
      setSection(splitDraft(context.setup_draft ?? {}))
      setSetupConfirmed(project.creation_status === 'setup_confirmed')
      setDraftError(context.setup_error ?? null)
      setOutlineError(context.outline_error ?? null)
      setCompressedChars(context.lengths_compressed ? context.chars_per_chapter ?? null : null)
      setOutlineWarning(context.outline_warning ?? null)
      setOutline({ objective: context.outline_draft?.objective ?? '', volumes: context.outline_draft?.volumes ?? [] })
      setOk('已恢复待完成作品，可继续确认设定与大纲；不会重复创建作品。')
    }).catch((err) => { if (!disposed) setBanner(ApiMessage(err, '恢复草稿失败，请刷新重试')) })
      .finally(() => { if (!disposed) setBusy(null) })
    return () => { disposed = true }
  }, [guest, resumeId, navigate, routeForm])

  const primary = catalog.find((item) => item.id === primaryId) ?? null
  const secondary = catalog.find((item) => item.id === secondaryId) ?? null
  const genreLabel = displayGenre(primary, secondary)
  const isShort = form === 'short'

  /** 短篇方案的服务端回执（归一后的字数、审纲留痕）只落在创建上下文里，要再拉一次才算看见 */
  async function refreshShortNotice(forPid: string) {
    try {
      const { context } = await api.getCreation(forPid)
      setCompressedChars(context.lengths_compressed ? context.chars_per_chapter ?? null : null)
      setOutlineWarning(context.outline_warning ?? null)
    } catch {
      /* 回执是附加信息，读不到就不显示 */
    }
  }

  function pickPrimary(id: string) {
    const next = primaryId === id ? null : id
    setPrimaryId(next)
    setSecondaryId(null)
    const nextPrimary = catalog.find((item) => item.id === next) ?? null
    setGenreFields(composeFields(nextPrimary, null))
  }

  function pickSecondary(id: string) {
    if (!primaryId) return
    const next = secondaryId === id ? null : id
    setSecondaryId(next)
    const nextSecondary = catalog.find((item) => item.id === next) ?? null
    setGenreFields(composeFields(primary, nextSecondary))
  }

  async function createAndDraft() {
    if (pid || resumeId || busy) return
    const brief = premise.trim()
    if (!brief) {
      setBanner('请填写创作简报（设定与大纲的种子）')
      return
    }
    const words = Number(targetWords)
    if (!isShort && (!Number.isInteger(words) || words < 500 || words > 20000)) {
      setBanner('目标字数需为 500–20000 的整数')
      return
    }
    const finalTitle = title.trim() || '未命名作品'
    const chapterCount = Number(outlineCount)
    const countMin = isShort ? SHORT_CHAPTER_MIN : 50
    const countMax = isShort ? SHORT_CHAPTER_MAX : 1000
    if (!Number.isInteger(chapterCount) || chapterCount < countMin || chapterCount > countMax) {
      setBanner(isShort ? '大致章节数需为 1–10 的整数' : '大致章节数需为 50–1000 的整数')
      return
    }
    const chars = Number(shortChars)
    if (isShort && (!Number.isInteger(chars) || chars < SHORT_CHARS_MIN || chars > SHORT_CHARS_MAX)) {
      setBanner('每章字数需为 1000–8000 的整数')
      return
    }
    let requestId: string
    try {
      requestId = pendingProjectCreationId()
    } catch {
      setBanner('无法安全保存创建请求，请检查浏览器存储权限后重试')
      return
    }
    setBusy('create')
    setBanner(null)
    setOk(null)
    try {
      const project = await api.createProject({
        title: finalTitle,
        primary_id: primaryId,
        secondary_id: secondaryId,
        genre_fields: genreFields,
        // 形态由入口决定，显式声明：短篇的篇幅走 chars_per_chapter（长篇的每章字数走 target_words），互不代填
        form,
        ...(isShort
          ? { chars_per_chapter: chars }
          : { target_words: words }),
        premise: brief,
        chapter_count: chapterCount,
        storyline: outlineStoryline.trim(),
        request_id: requestId,
        // 不指定就显式发 null：后端把「没选」与「选了查不到」分得很开（后者 404）。
        style_item_id: styleItemId || null,
      })
      let storageCleanupFailed = false
      try {
        window.sessionStorage.removeItem(PENDING_PROJECT_CREATION_KEY)
      } catch {
        storageCleanupFailed = true
      }
      currentPid.current = project.id
      setPid(project.id)
      setSearchParams({ draft: project.id }, { replace: true })
      setSavedTitle(finalTitle)
      void api.listProjects().then(setProjects).catch(() => {})
      // InkOS 风格一键建书：设定草稿 + 整书大纲草稿并行生成（outline 只读 genre/premise，无需等设定确认）
      const results = await Promise.all([regenerate(project.id, true), generateOutline(project.id, true)])
      setOk(results.every(Boolean)
        ? '作品草稿已保存，设定与整书大纲提案已生成，请编辑并确认。'
        : '作品草稿已保存；草稿生成未全部完成，请检查提示后重试或手动填写。')
      if (storageCleanupFailed) {
        setBanner('作品已创建，但无法清除本机创建标识；后续重试会安全复用同一作品。')
      }
    } catch (err) {
      setBanner(ApiMessage(err, '创建作品失败，请重试'))
    } finally {
      setBusy(null)
    }
  }

  async function regenerate(forPid: string, managed = false) {
    if (!managed) setBusy('draft')
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
      return !resp.error
    } catch (err) {
      setBanner(ApiMessage(err, '生成设定草稿失败，请重试'))
      setSection(emptySection())
      return false
    } finally {
      if (!managed) setBusy(null)
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

  // ③ 提案保存到创建上下文供恢复；确认后才写入正式大纲。
  async function generateOutline(forPid: string, managed = false) {
    const cc = Number(outlineCount)
    const countMin = isShort ? SHORT_CHAPTER_MIN : 50
    const countMax = isShort ? SHORT_CHAPTER_MAX : 1000
    if (!Number.isInteger(cc) || cc < countMin || cc > countMax) {
      setBanner(isShort ? '大致章节数需为 1–10 的整数' : '大致章节数需为 50–1000 的整数')
      return false
    }
    if (!managed) setBusy('outline-draft')
    setBanner(null)
    setOutlineError(null)
    try {
      const resp = await api.outlineDraft(forPid, {
        premise: premise.trim(),
        chapter_count: cc,
        storyline: outlineStoryline.trim(),
        ...(isShort ? { chars_per_chapter: Number(shortChars) } : {}),
      })
      // 降级时 outline 为 {} → 归一为空结构，保证可编辑面板始终可渲染。
      setOutline({
        objective: typeof resp.outline.objective === 'string' ? resp.outline.objective : '',
        volumes: Array.isArray(resp.outline.volumes) ? resp.outline.volumes : [],
      })
      setOutlineError(resp.error)
      if (isShort) await refreshShortNotice(forPid)
      return !resp.error
    } catch (err) {
      setBanner(ApiMessage(err, '生成大纲失败，请重试'))
      setOutline({ objective: '', volumes: [] })
      return false
    } finally {
      if (!managed) setBusy(null)
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
    await api.confirmOutline(pid, {
      objective: outline.objective,
      volumes: outline.volumes.map((v) => ({
        title: v.title,
        theme: v.theme ?? '',
        goal: v.goal,
        key_results: v.key_results ?? [],
        end_event: v.end_event ?? '',
        chapter_start: v.chapter_start,
        chapter_end: v.chapter_end,
        stages: (v.stages ?? []).map((s) => ({
          name: s.name,
          chapter_start: s.chapter_start,
          chapter_end: s.chapter_end,
          goal: s.goal,
          beats: s.beats ?? [],
        })),
        // 短篇写手读的是逐章细纲，缺它就整篇成稿无从落地；长篇不传（形状是卷+阶段）
        ...(isShort
          ? {
              chapters: (v.chapters ?? []).map((c) => ({
                chapter_seq: c.chapter_seq,
                title: c.title ?? '',
                goal: c.goal ?? '',
                key_scene: c.key_scene ?? '',
                character_action: c.character_action ?? '',
                escalation_or_payoff: c.escalation_or_payoff ?? '',
                hook: c.hook ?? '',
              })),
            }
          : {}),
      })),
      premise: premise.trim(),
      chapter_count: Number(outlineCount) || 0,
      storyline: outlineStoryline.trim(),
    })
    await syncTitle()
  }

  async function confirmOutline() {
    if (!pid || !outline || !setupConfirmed) return
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
    if (!pid || !outline || !section || isSectionEmpty(section)) {
      setBanner('请先填写有效的设定与整书大纲')
      return
    }
    setBusy('confirm-all')
    setBanner(null)
    setOk(null)
    try {
      if (section) {
        await api.confirmSetup(pid, sectionToBody(section))
        setSetupConfirmed(true)
      }
      await persistOutline()
      await syncTitle()
      setOk('设定与整书大纲已落库，进入工作台')
      navigate(`/projects/${pid}`)
    } catch (err) {
      setBanner(ApiMessage(err, '确认失败，请重试'))
    } finally {
      setBusy(null)
    }
  }

  /** 未完成作品保留为草稿，不开放写作。 */
  async function leaveDraft() {
    if (!pid) return
    try {
      await syncTitle()
    } catch {
      /* 标题同步失败不阻塞进入 */
    }
    navigate(`/${form}`)
  }

  const updateOutline = (patch: Partial<BookOutline>) =>
    setOutline((o) => (o ? { ...o, ...patch } : o))

  const updateVolume = (vi: number, patch: Partial<OutlineVolume>) =>
    setOutline((o) =>
      o
        ? { ...o, volumes: o.volumes.map((v, j) => (j === vi ? { ...v, ...patch } : v)) }
        : o,
    )

  /** 短篇逐章细纲的编辑（章号不可手改：后端要求 1..N 齐整，改坏了确认必失败） */
  const updateShortChapter = (vi: number, ci: number, patch: Partial<OutlineChapter>) =>
    setOutline((o) =>
      o
        ? {
            ...o,
            volumes: o.volumes.map((v, j) =>
              j === vi
                ? { ...v, chapters: (v.chapters ?? []).map((c, k) => (k === ci ? { ...c, ...patch } : c)) }
                : v,
            ),
          }
        : o,
    )

  const updateStage = (vi: number, si: number, patch: Partial<OutlineStage>) =>
    setOutline((o) =>
      o
        ? {
            ...o,
            volumes: o.volumes.map((v, j) =>
              j === vi
                ? { ...v, stages: (v.stages ?? []).map((s, k) => (k === si ? { ...s, ...patch } : s)) }
                : v,
            ),
          }
        : o,
    )

  const removeStage = (vi: number, si: number) =>
    setOutline((o) =>
      o
        ? {
            ...o,
            volumes: o.volumes.map((v, j) =>
              j === vi ? { ...v, stages: (v.stages ?? []).filter((_, k) => k !== si) } : v,
            ),
          }
        : o,
    )

  const addStage = (vi: number) =>
    setOutline((o) =>
      o
        ? {
            ...o,
            volumes: o.volumes.map((v, j) =>
              j === vi
                ? { ...v, stages: [...(v.stages ?? []), { name: `第 ${(v.stages ?? []).length + 1} 段`, goal: '', beats: [] }] }
                : v,
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
                stages: [{ name: '本卷', goal: '', beats: [] }],
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
              <h1>{pid || resumeId ? '继续创建作品' : `新建${isShort ? '短篇' : '长篇'}`}</h1>
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
                disabled={busy === 'restore'}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="如《破晓录》，留空由 AI 起名"
                maxLength={60}
              />
            </label>
            <div className={styles.field}>
              <span className={styles.fieldLabel}>题材</span>
              <div className={styles.lockedGenre}>{genreLabel}</div>
              {groupCatalog(catalog).map(({ group, items }) => (
                <div key={group} className={styles.genreGroup}>
                  <div className={styles.genreGroupTitle}>主题材 · {group}</div>
                  <div className={styles.genreChips}>
                    {items.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        disabled={busy === 'restore' || pid !== null}
                        className={styles.chip + (primaryId === item.id ? ' ' + styles.chipOn : '')}
                        onClick={() => pickPrimary(item.id)}
                      >
                        {item.name}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              <div className={styles.genreGroup}>
                <div className={styles.genreGroupTitle}>辅题材（可选，须先选主题材）</div>
                {groupCatalog(catalog).map(({ group, items }) => (
                  <div key={`sec-${group}`}>
                    <div className={styles.genreSubTitle}>{group}</div>
                    <div className={styles.genreChips}>
                      {items.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          disabled={busy === 'restore' || pid !== null || !primaryId || item.id === primaryId}
                          className={styles.chip + (secondaryId === item.id ? ' ' + styles.chipOn : '')}
                          onClick={() => pickSecondary(item.id)}
                        >
                          {item.name}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <details className={styles.genreDetails}>
                <summary>题材详情（默认折叠，可按自己的想法改）</summary>
                <fieldset disabled={busy === 'restore' || pid !== null} style={{ border: 0, padding: 0, margin: 0 }}>
                  <GenrePackFields value={genreFields} onChange={setGenreFields} />
                </fieldset>
              </details>
            </div>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>文风（可选）</span>
              <select
                className="input"
                aria-label="文风"
                value={styleItemId}
                disabled={busy === 'restore' || pid !== null}
                onChange={(e) => setStyleItemId(e.target.value)}
              >
                <option value="">不指定</option>
                {styleItems.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}{item.builtin ? '（内置）' : '（我的）'}
                  </option>
                ))}
              </select>
            </label>
            {isShort ? (
              <>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>章数（1–10）</span>
                  <input
                    className="input"
                    type="number"
                    min={SHORT_CHAPTER_MIN}
                    max={SHORT_CHAPTER_MAX}
                    value={outlineCount}
                    disabled={busy === 'restore' || pid !== null}
                    onChange={(e) => setOutlineCount(e.target.value)}
                  />
                </label>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>
                    每章字数（{SHORT_CHARS_MIN}–{SHORT_CHARS_MAX}）
                  </span>
                  <input
                    className="input"
                    type="number"
                    min={SHORT_CHARS_MIN}
                    max={SHORT_CHARS_MAX}
                    step={500}
                    value={shortChars}
                    disabled={busy === 'restore' || pid !== null}
                    onChange={(e) => setShortChars(e.target.value)}
                  />
                </label>
              </>
            ) : (
              <label className={styles.field}>
                <span className={styles.fieldLabel}>每章目标字数（500–20000）</span>
                <input
                  className="input"
                  type="number"
                  min={500}
                  max={20000}
                  step={100}
                  value={targetWords}
                  disabled={busy === 'restore' || pid !== null}
                  onChange={(e) => setTargetWords(e.target.value)}
                />
              </label>
            )}
            <label className={styles.field}>
              <span className={styles.fieldLabel}>创作简报</span>
              <textarea
                className="textarea"
                rows={5}
                value={premise}
                disabled={busy === 'restore'}
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
                disabled={busy !== null || pid !== null || resumeId !== null}
                onClick={createAndDraft}
              >
                {pid ? '作品草稿已保存' : busy === 'create' ? '创建中…' : '创建作品'}
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
                  disabled={busy !== null || setupConfirmed}
                  onClick={() => regenerate(pid)}
                >
                  {busy === 'draft' ? '重新生成中…' : '重新生成草稿'}
                </button>
              </div>
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
              {outlineError && (
                <div className="banner banner-warning">LLM 生成降级：{outlineError}（可手填后确认）</div>
              )}
              <div className={styles.block}>
                <span className={styles.fieldLabel}>
                  {isShort
                    ? `大致章节数（${SHORT_CHAPTER_MIN}–${SHORT_CHAPTER_MAX}）`
                    : '大致章节数（50–1000）'}
                </span>
                <input
                  className="input"
                  type="number"
                  min={isShort ? SHORT_CHAPTER_MIN : 50}
                  max={isShort ? SHORT_CHAPTER_MAX : 1000}
                  value={outlineCount}
                  onChange={(e) => setOutlineCount(e.target.value)}
                />
              </div>
              {isShort && compressedChars !== null && (
                <div className="banner banner-warning">
                  每章字数已按全篇 {SHORT_TOTAL_MAX} 字上限归一为每章 {compressedChars} 字，生成时按这个数走。
                </div>
              )}
              {isShort && outlineWarning && (
                <div className="banner banner-warning">方案审纲留痕：{outlineWarning}</div>
              )}
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
                <div className={styles.outlineStack}>
                  <div className={styles.block}>
                    <span className={styles.fieldLabel}>全书 Objective（终局，可验证状态）</span>
                    <textarea
                      className={`textarea ${styles.growArea}`}
                      rows={4}
                      value={outline.objective}
                      onChange={(e) => updateOutline({ objective: e.target.value })}
                      placeholder="如：从杂役修士成为宗门长老并公开父辈冤案真相"
                    />
                  </div>
                  {isShort && (
                    <div className={styles.block}>
                      <span className={styles.fieldLabel}>
                        逐章方案（短篇唯一一卷；写手照它一次成稿，章号不可改）
                      </span>
                      {outline.volumes.length === 0 && (
                        <div className="empty">方案为空（LLM 未产出），请点上方「重新生成大纲」。</div>
                      )}
                      {outline.volumes.map((v, vi) => (
                        <div key={vi} className={styles.block}>
                          <label className={styles.field}>
                            <span className={styles.fieldLabel}>篇名</span>
                            <input
                              className="input"
                              placeholder="全篇 · 篇名"
                              value={v.title}
                              onChange={(e) => updateVolume(vi, { title: e.target.value })}
                            />
                          </label>
                          <label className={styles.field}>
                            <span className={styles.fieldLabel}>主题</span>
                            <input
                              className="input"
                              placeholder="一句话主题"
                              value={v.theme ?? ''}
                              onChange={(e) => updateVolume(vi, { theme: e.target.value })}
                            />
                          </label>
                          <label className={styles.field}>
                            <span className={styles.fieldLabel}>全篇目标（结局时主角必须达到的可验证状态）</span>
                            <textarea
                              className={`textarea ${styles.growArea}`}
                              rows={3}
                              value={v.goal}
                              onChange={(e) => updateVolume(vi, { goal: e.target.value })}
                            />
                          </label>
                          {(v.chapters ?? []).map((c, ci) => {
                            const seq = c.chapter_seq ?? ci + 1
                            return (
                              <div key={ci} className={styles.stageFold}>
                                <div className={styles.block}>
                                  <div className={styles.foldTitle}>
                                    第 {seq} 章{c.title ? ` · ${c.title}` : ''}
                                  </div>
                                  <label className={styles.field}>
                                    <span className={styles.fieldLabel}>第 {seq} 章 · 章节标题</span>
                                    <input
                                      className="input"
                                      placeholder="像平台内容，不要文艺化总结"
                                      value={c.title ?? ''}
                                      onChange={(e) => updateShortChapter(vi, ci, { title: e.target.value })}
                                    />
                                  </label>
                                  <label className={styles.field}>
                                    <span className={styles.fieldLabel}>第 {seq} 章 · 本章目标</span>
                                    <textarea
                                      className="textarea"
                                      rows={2}
                                      placeholder="本章结束时必须达到的可验证状态"
                                      value={c.goal ?? ''}
                                      onChange={(e) => updateShortChapter(vi, ci, { goal: e.target.value })}
                                    />
                                  </label>
                                  <label className={styles.field}>
                                    <span className={styles.fieldLabel}>第 {seq} 章 · 关键场面</span>
                                    <input
                                      className="input"
                                      placeholder="谁 + 在何处 + 做什么"
                                      value={c.key_scene ?? ''}
                                      onChange={(e) => updateShortChapter(vi, ci, { key_scene: e.target.value })}
                                    />
                                  </label>
                                  <label className={styles.field}>
                                    <span className={styles.fieldLabel}>第 {seq} 章 · 角色动作</span>
                                    <input
                                      className="input"
                                      placeholder="主角主动做出的选择或行动"
                                      value={c.character_action ?? ''}
                                      onChange={(e) =>
                                        updateShortChapter(vi, ci, { character_action: e.target.value })
                                      }
                                    />
                                  </label>
                                  <label className={styles.field}>
                                    <span className={styles.fieldLabel}>第 {seq} 章 · 压力升级或回报</span>
                                    <input
                                      className="input"
                                      placeholder="本章的压力升级或回报"
                                      value={c.escalation_or_payoff ?? ''}
                                      onChange={(e) =>
                                        updateShortChapter(vi, ci, { escalation_or_payoff: e.target.value })
                                      }
                                    />
                                  </label>
                                  <label className={styles.field}>
                                    <span className={styles.fieldLabel}>第 {seq} 章 · 章尾钩子</span>
                                    <input
                                      className="input"
                                      placeholder="让读者接着读下一章的那个具体理由"
                                      value={c.hook ?? ''}
                                      onChange={(e) => updateShortChapter(vi, ci, { hook: e.target.value })}
                                    />
                                  </label>
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      ))}
                    </div>
                  )}
                  {!isShort && outline.volumes.map((v, vi) => {
                    const volumeRange = chapterRangeLabel(v.chapter_start, v.chapter_end)
                    const stageCount = (v.stages ?? []).length
                    return (
                      <details key={vi} className={styles.volumeFold}>
                        <summary className={styles.foldSummary}>
                          <span className={styles.foldTitle}>
                            第 {vi + 1} 卷大纲
                            {v.title ? ` · ${v.title}` : ''}
                          </span>
                          <span className={styles.foldMeta}>
                            {volumeRange || '章区间未定'}
                            {stageCount ? ` · ${stageCount} 段` : ''}
                          </span>
                        </summary>
                        <div className={styles.foldBody}>
                          <label className={styles.field}>
                            <span className={styles.fieldLabel}>卷名</span>
                            <input
                              className="input"
                              placeholder="卷名"
                              value={v.title}
                              onChange={(e) => updateVolume(vi, { title: e.target.value })}
                            />
                          </label>
                          <label className={styles.field}>
                            <span className={styles.fieldLabel}>主题</span>
                            <input
                              className="input"
                              value={v.theme ?? ''}
                              placeholder="一句话主题"
                              onChange={(e) => updateVolume(vi, { theme: e.target.value })}
                            />
                          </label>
                          <div className={styles.rangeRow}>
                            <label className={styles.field}>
                              <span className={styles.fieldLabel}>起始章</span>
                              <input
                                className="input"
                                type="number"
                                min={1}
                                placeholder="起始章"
                                value={v.chapter_start ?? ''}
                                onChange={(e) =>
                                  updateVolume(vi, { chapter_start: Number(e.target.value) || undefined })
                                }
                              />
                            </label>
                            <label className={styles.field}>
                              <span className={styles.fieldLabel}>结束章</span>
                              <input
                                className="input"
                                type="number"
                                min={1}
                                placeholder="结束章"
                                value={v.chapter_end ?? ''}
                                onChange={(e) =>
                                  updateVolume(vi, { chapter_end: Number(e.target.value) || undefined })
                                }
                              />
                            </label>
                          </div>
                          <label className={styles.field}>
                            <span className={styles.fieldLabel}>卷目标</span>
                            <textarea
                              className={`textarea ${styles.growArea}`}
                              rows={3}
                              placeholder="本卷结束时主角须达到的可验证状态"
                              value={v.goal}
                              onChange={(e) => updateVolume(vi, { goal: e.target.value })}
                            />
                          </label>
                          <label className={styles.field}>
                            <span className={styles.fieldLabel}>关键结果 KR（每行一条）</span>
                            <textarea
                              className={`textarea ${styles.growArea}`}
                              rows={4}
                              placeholder="每行一条可验证结果"
                              value={arrayToLines(v.key_results ?? [])}
                              onChange={(e) => updateVolume(vi, { key_results: linesToArray(e.target.value) })}
                            />
                          </label>
                          <label className={styles.field}>
                            <span className={styles.fieldLabel}>卷末不可逆事件</span>
                            <textarea
                              className={`textarea ${styles.growArea}`}
                              rows={3}
                              placeholder="只写事件，不写第几章"
                              value={v.end_event ?? ''}
                              onChange={(e) => updateVolume(vi, { end_event: e.target.value })}
                            />
                          </label>
                          {(v.stages ?? []).map((s, si) => {
                            const stageRange = chapterRangeLabel(s.chapter_start, s.chapter_end)
                            return (
                              <details key={si} className={styles.stageFold}>
                                <summary className={styles.foldSummary}>
                                  <span className={styles.foldTitle}>
                                    {s.name || `第 ${si + 1} 段`}
                                  </span>
                                  <span className={styles.foldMeta}>{stageRange || '章区间未定'}</span>
                                </summary>
                                <div className={styles.foldBody}>
                                  <div className={styles.stageHead}>
                                    <label className={styles.field}>
                                      <span className={styles.fieldLabel}>阶段名</span>
                                      <input
                                        className="input"
                                        placeholder="前期 / 中期 / 后期"
                                        value={s.name}
                                        onChange={(e) => updateStage(vi, si, { name: e.target.value })}
                                      />
                                    </label>
                                    <button
                                      type="button"
                                      className="btn btn-quiet"
                                      onClick={() => removeStage(vi, si)}
                                    >
                                      删除本段
                                    </button>
                                  </div>
                                  <div className={styles.rangeRow}>
                                    <label className={styles.field}>
                                      <span className={styles.fieldLabel}>起始章</span>
                                      <input
                                        className="input"
                                        type="number"
                                        min={1}
                                        placeholder="起始章"
                                        value={s.chapter_start ?? ''}
                                        onChange={(e) =>
                                          updateStage(vi, si, {
                                            chapter_start: Number(e.target.value) || undefined,
                                          })
                                        }
                                      />
                                    </label>
                                    <label className={styles.field}>
                                      <span className={styles.fieldLabel}>结束章</span>
                                      <input
                                        className="input"
                                        type="number"
                                        min={1}
                                        placeholder="结束章"
                                        value={s.chapter_end ?? ''}
                                        onChange={(e) =>
                                          updateStage(vi, si, {
                                            chapter_end: Number(e.target.value) || undefined,
                                          })
                                        }
                                      />
                                    </label>
                                  </div>
                                  <label className={styles.field}>
                                    <span className={styles.fieldLabel}>阶段目标</span>
                                    <textarea
                                      className={`textarea ${styles.growArea}`}
                                      rows={3}
                                      placeholder="约 30 章一段，写作时会注入当前阶段"
                                      value={s.goal}
                                      onChange={(e) => updateStage(vi, si, { goal: e.target.value })}
                                    />
                                  </label>
                                  <label className={styles.field}>
                                    <span className={styles.fieldLabel}>阶段节拍（每行一条）</span>
                                    <textarea
                                      className={`textarea ${styles.growArea}`}
                                      rows={Math.max(4, s.beats?.length ?? 0)}
                                      placeholder="谁 + 在何处 + 做什么 + 导致什么"
                                      value={arrayToLines(s.beats ?? [])}
                                      onChange={(e) =>
                                        updateStage(vi, si, { beats: linesToArray(e.target.value) })
                                      }
                                    />
                                  </label>
                                </div>
                              </details>
                            )
                          })}
                          <button type="button" className="btn btn-quiet" onClick={() => addStage(vi)}>
                            + 本卷加一段
                          </button>
                        </div>
                      </details>
                    )
                  })}
                  <div className={styles.saveRow}>
                    {/* 短篇只能有一卷：不给「新增一卷」，避免做出后端必拒的方案 */}
                    {!isShort && (
                      <button type="button" className="btn btn-quiet" disabled={busy !== null} onClick={addVolume}>
                        + 新增一卷
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn btn-quiet"
                      disabled={busy !== null || !setupConfirmed || !outline.objective.trim() || outline.volumes.length === 0}
                      onClick={confirmOutline}
                    >
                      {busy === 'outline-confirm' ? '确认中…' : '仅确认大纲并进入'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={busy !== null || !outline.objective.trim() || outline.volumes.length === 0 || emptyDraft}
                      onClick={confirmAll}
                    >
                      {busy === 'confirm-all' ? '确认中…' : '确认设定与大纲并进入工作台'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-quiet"
                      disabled={busy !== null}
                      onClick={leaveDraft}
                    >
                      保留草稿，返回作品库
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
                    onClick={leaveDraft}
                  >
                    保留草稿，返回作品库
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
