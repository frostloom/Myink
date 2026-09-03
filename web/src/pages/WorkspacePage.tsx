// 工作台（三栏）：rail 项目切换 + 章节列表 | 章节编辑器 | 生成入口/时间线/校验报告/候选池。
// 生成任务进度状态在页面级提升：useTaskEvents(activeTaskId)，终态 → 刷新章节列表。
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AuditPanel } from '../components/AuditPanel'
import { CandidatePanel, type ReleaseTarget } from '../components/CandidatePanel'
import { ChapterEditor } from '../components/ChapterEditor'
import { ChapterList } from '../components/ChapterList'
import { GenerationPanel } from '../components/GenerationPanel'
import { LessonsPanel } from '../components/LessonsPanel'
import { ProjectRail } from '../components/ProjectRail'
import { TaskHistory } from '../components/TaskHistory'
import { TaskTimeline } from '../components/TaskTimeline'
import { useAuth } from '../context/AuthContext'
import { useTaskEvents } from '../hooks/useTaskEvents'
import { api, ApiError } from '../lib/api'
import { nodesForChapter, runsForChapter } from '../lib/taskChapter'
import type { ChapterMeta, MemoryCandidate, Project } from '../types'
import styles from './WorkspacePage.module.css'

export default function WorkspacePage() {
  const { projectId = '' } = useParams()
  const { logout } = useAuth()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const [projects, setProjects] = useState<Project[]>([])
  const [chapters, setChapters] = useState<ChapterMeta[]>([])
  const [candidates, setCandidates] = useState<MemoryCandidate[]>([])
  const [selectedCid, setSelectedCid] = useState<string | null>(null)
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null)
  const [batchTotal, setBatchTotal] = useState<number | null>(null)
  // 活动单章任务对应的章（§11 右栏按章过滤）：批次任务为 null（按 :ch{seq} 子线程切）
  const [activeChapterSeq, setActiveChapterSeq] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshTick, setRefreshTick] = useState(0)
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  // 放行本章（§6.11 确认流收尾）：awaiting_review 单章任务确认完候选后 resume 落库正文
  const [releaseTarget, setReleaseTarget] = useState<ReleaseTarget | null>(null)
  // 放行复用同一 task_id 续跑，SSE 需强制重连（useTaskEvents resumeKey 触发）
  const [releaseResumeKey, setReleaseResumeKey] = useState<number | null>(null)

  // 候选池加载失败静默降级（空列表），不阻塞主链路
  const loadCandidates = useCallback(() => {
    api.listCandidates(projectId).then(setCandidates).catch(() => setCandidates([]))
  }, [projectId])

  // 章序 → 待确认候选数（候选面板与章节列表角标联动）
  const pendingByChapter = useMemo(() => {
    const m = new Map<number, number>()
    for (const c of candidates) {
      m.set(c.source_chapter, (m.get(c.source_chapter) ?? 0) + 1)
    }
    return m
  }, [candidates])

  const loadProjects = useCallback(() => {
    api.listProjects().then(setProjects).catch(() => setProjects([]))
  }, [])

  const loadChapters = useCallback(async () => {
    setError(null) // 新一次加载先清陈旧错误横幅
    try {
      const list = await api.listChapters(projectId)
      setChapters(list)
      return list
    } catch (err) {
      setError(err instanceof ApiError ? err.code : '章节加载失败')
      return []
    }
  }, [projectId])

  useEffect(() => {
    // projectId 变化 = 切书：清空上一本的选择/任务/批次上下文 + 重载候选池
    setSelectedCid(null)
    setActiveTaskId(null)
    setBatchTotal(null)
    setActiveChapterSeq(null)
    setReleaseTarget(null)
    setReleaseResumeKey(null)
    setError(null)
    loadProjects()
    void loadChapters()
    loadCandidates()
  }, [loadProjects, loadChapters, loadCandidates])

  // 跨页深链（审计视图「跳章」→ /projects/:pid?chapter=<seq>）：一次性选中目标章并清参数
  useEffect(() => {
    const seqRaw = searchParams.get('chapter')
    if (seqRaw === null) return
    const target = chapters.find((c) => c.chapter_seq === Number(seqRaw))
    if (target) {
      setSelectedCid(target.id)
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, chapters, setSearchParams])

  const handleTaskStart = useCallback(
    (taskId: string, total?: number, chapterSeq?: number) => {
      setBatchTotal(total ?? null)
      setActiveTaskId(taskId)
      // 单章任务带出对应章（右栏按章过滤）；批次任务不带（按 :ch{seq} 子线程切）
      setActiveChapterSeq(chapterSeq ?? null)
    },
    [],
  )

  // 放行本章：resume 同一 task_id 续跑（§6.11 确认流收尾）。taskId 不变但 SSE 已关流，
  // 用 releaseResumeKey 强制重连；终态 → 既有 effect 刷章节/候选，正文出现、按钮消失。
  const handleRelease = useCallback((taskId: string, chapterSeq: number) => {
    setBatchTotal(null)
    setActiveChapterSeq(chapterSeq)
    setActiveTaskId(taskId)
    setReleaseTarget(null)
    setReleaseResumeKey(Date.now())
  }, [])

  const task = useTaskEvents(
    activeTaskId,
    batchTotal
      ? { batchTotal }
      : releaseResumeKey !== null
        ? { resumeKey: releaseResumeKey }
        : undefined,
  )
  const taskPhase = task.phase

  // 生成任务进入终态/过期 → 章节状态与内容已更新：刷新列表 + 让编辑器重拉当前章正文 + 重载候选池
  useEffect(() => {
    if (taskPhase === 'terminal' || taskPhase === 'expired' || taskPhase === 'error') {
      void loadChapters()
      loadCandidates()
      setRefreshTick((t) => t + 1)
      // 单章任务停在 awaiting_review → 候选确认完后给「放行本章」；放行完成（done）即清
      if (task.status === 'awaiting_review' && activeTaskId && activeChapterSeq) {
        setReleaseTarget({ taskId: activeTaskId, chapterSeq: activeChapterSeq })
      } else if (task.status === 'done' || task.status === 'failed' || task.status === 'cancelled') {
        setReleaseTarget(null)
      }
    }
  }, [taskPhase, task.status, loadChapters, loadCandidates, activeTaskId, activeChapterSeq])

  // 批次/单章完成后自动打开最早生成的章节（新建书首轮批次结束 → 编辑器立即可用，
  // 「单章生成」随之可点）；用户已手动选中则不动。chapters 异步更新，依赖两者兜底。
  useEffect(() => {
    if (taskPhase !== 'terminal' || chapters.length === 0 || selectedCid) return
    const first = [...chapters].sort((a, b) => a.chapter_seq - b.chapter_seq)[0]
    setSelectedCid(first.id)
  }, [taskPhase, chapters, selectedCid])

  const selectedChapter = chapters.find((c) => c.id === selectedCid) ?? null

  // 兜底：刷新/重挂载后当前章若停在 awaiting_review（无活动任务流），从任务列表找回
  // 待人工任务补设放行目标。只设不清——放行完成由终态 effect 清、点按钮由 handleRelease
  // 清，此处清会在同一次提交里覆盖终态 effect 刚设的目标（selectedChapter.status 仍陈旧）。
  useEffect(() => {
    if (!selectedChapter || selectedChapter.status !== 'awaiting_review') return
    let cancelled = false
    api
      .listTasks(projectId, selectedChapter.chapter_seq)
      .then((tasks) => {
        if (cancelled) return
        const awaiting = tasks.find((t) => t.status === 'awaiting_review')
        if (awaiting) {
          setReleaseTarget({ taskId: awaiting.task_id, chapterSeq: selectedChapter.chapter_seq })
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [projectId, selectedChapter?.id, selectedChapter?.status, selectedChapter?.chapter_seq])

  // 右栏按章过滤（§11）：选中某章时，节点流转/花费只显示该章——批次按 :ch{seq}
  // 子线程切、单章按发起时带出的章对齐；未选中章则不过滤（时间线整体兜底）。
  const selectedSeq = selectedChapter?.chapter_seq ?? null
  const taskRuns = runsForChapter(task.runs, {
    taskId: activeTaskId,
    batch: batchTotal !== null,
    selectedSeq,
    activeChapterSeq,
  })
  const taskNodes = nodesForChapter(task.nodes, {
    taskId: activeTaskId,
    batch: batchTotal !== null,
    selectedSeq,
    activeChapterSeq,
  })

  const handleNotFound = useCallback(() => {
    setSelectedCid(null)
    void loadChapters()
  }, [loadChapters])

  const handleSaved = useCallback(() => {
    void loadChapters()
  }, [loadChapters])

  // Markdown 导出（纯前端拼接下载）：逐章拉正文 → 标题/章节分隔 → Blob 下载
  const handleExportMarkdown = useCallback(async () => {
    if (exporting || chapters.length === 0) return
    setExporting(true)
    try {
      const project = projects.find((p) => p.id === projectId)
      const lines: string[] = [`# ${project?.title ?? 'Ai Ink 作品'}`, '']
      for (const c of chapters) {
        const detail = await api.getChapter(projectId, c.id)
        const title = detail.title?.trim() || ''
        lines.push(title ? `## 第 ${c.chapter_seq} 章 · ${title}` : `## 第 ${c.chapter_seq} 章`, '')
        lines.push(detail.content?.trim() ?? '', '')
      }
      const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${project?.title ?? 'ai-ink'}.md`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('导出失败')
    } finally {
      setExporting(false)
    }
  }, [exporting, chapters, projects, projectId])

  const handleNavigateChapter = useCallback(
    (seq: number) => {
      const target = chapters.find((c) => c.chapter_seq === seq)
      if (target) setSelectedCid(target.id)
    },
    [chapters],
  )

  // 整本书删除（阶段 6 硬删）：confirm → 删除成功回作品库；有进行中任务 → Python 409
  const handleDeleteBook = useCallback(() => {
    const project = projects.find((p) => p.id === projectId)
    const title = project?.title ?? '本书'
    if (!window.confirm(`删除《${title}》？全书正文、记忆、向量与任务记录将一并移除，不可撤销。`)) return
    setDeleting(true)
    api
      .deleteProject(projectId)
      .then(() => navigate('/projects'))
      .catch((err) => {
        setDeleting(false)
        setError(
          err instanceof ApiError && err.status === 409
            ? '本书有进行中任务，无法删除。请先暂停/取消后再试。'
            : err instanceof ApiError
              ? `删除失败：${err.code}`
              : '删除失败',
        )
      })
  }, [projects, projectId, navigate])

  return (
    <div className={styles.wrap}>
      <ProjectRail projects={projects} onLogout={logout} />

      <aside className={styles.chapters} aria-label="章节列表">
        <div className={styles.sideHead}>
          <h3 className={styles.sideTitle}>章节</h3>
          <button
            type="button"
            className="btn btn-quiet"
            disabled={exporting || chapters.length === 0}
            onClick={() => void handleExportMarkdown()}
          >
            {exporting ? '导出中…' : '导出 .md'}
          </button>
          <button
            type="button"
            className="btn btn-quiet"
            disabled={deleting}
            onClick={handleDeleteBook}
          >
            {deleting ? '删除中…' : '删除本书'}
          </button>
        </div>
        <ChapterList
          chapters={chapters}
          selectedCid={selectedCid}
          onSelect={setSelectedCid}
          pendingByChapter={pendingByChapter}
        />
      </aside>

      <main className={styles.main}>
        {error && <div className="banner banner-error">{error}</div>}
        {selectedChapter ? (
          <ChapterEditor
            projectId={projectId}
            chapter={selectedChapter}
            onNotFound={handleNotFound}
            onSaved={handleSaved}
            onMemoryChanged={loadCandidates}
            refreshTick={refreshTick}
          />
        ) : (
          <div className="empty">
            {chapters.length === 0 ? '还没有章节。在右侧发起首次生成。' : '选择左侧章节开始编辑。'}
          </div>
        )}
      </main>

      <aside className={styles.right} aria-label="生成与校验">
        <GenerationPanel
          projectId={projectId}
          chapters={chapters}
          selectedChapter={selectedChapter}
          onTaskStart={handleTaskStart}
        />
        <TaskHistory
          projectId={projectId}
          activeTaskId={activeTaskId}
          selectedSeq={selectedSeq}
        />
        <TaskTimeline
          taskId={activeTaskId}
          phase={task.phase}
          status={task.status}
          nodes={taskNodes}
          runs={taskRuns}
          progress={task.progress}
          chapterSeq={selectedSeq}
          error={task.error}
          onRetry={task.retry}
          canControl={batchTotal !== null}
          refresh={task.refresh}
        />
        <AuditPanel runs={taskRuns} onNavigateChapter={handleNavigateChapter} />
        <CandidatePanel
          projectId={projectId}
          candidates={candidates}
          onChanged={loadCandidates}
          releaseTarget={releaseTarget}
          onReleased={handleRelease}
        />
        <LessonsPanel projectId={projectId} />
      </aside>
    </div>
  )
}
