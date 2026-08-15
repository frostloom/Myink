// 工作台（三栏）：rail 项目切换 + 章节列表 | 章节编辑器 | 生成入口/时间线/校验报告/候选池。
// 生成任务进度状态在页面级提升：useTaskEvents(activeTaskId)，终态 → 刷新章节列表。
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { AuditPanel } from '../components/AuditPanel'
import { CandidatePanel } from '../components/CandidatePanel'
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
import type { ChapterMeta, MemoryCandidate, Project } from '../types'
import styles from './WorkspacePage.module.css'

export default function WorkspacePage() {
  const { projectId = '' } = useParams()
  const { logout } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()

  const [projects, setProjects] = useState<Project[]>([])
  const [chapters, setChapters] = useState<ChapterMeta[]>([])
  const [candidates, setCandidates] = useState<MemoryCandidate[]>([])
  const [selectedCid, setSelectedCid] = useState<string | null>(null)
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null)
  const [batchTotal, setBatchTotal] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshTick, setRefreshTick] = useState(0)
  const [exporting, setExporting] = useState(false)

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

  const handleTaskStart = useCallback((taskId: string, total?: number) => {
    setBatchTotal(total ?? null)
    setActiveTaskId(taskId)
  }, [])

  const task = useTaskEvents(activeTaskId, batchTotal ? { batchTotal } : undefined)
  const taskPhase = task.phase

  // 生成任务进入终态/过期 → 章节状态与内容已更新：刷新列表 + 让编辑器重拉当前章正文 + 重载候选池
  useEffect(() => {
    if (taskPhase === 'terminal' || taskPhase === 'expired' || taskPhase === 'error') {
      void loadChapters()
      loadCandidates()
      setRefreshTick((t) => t + 1)
    }
  }, [taskPhase, loadChapters, loadCandidates])

  // 批次/单章完成后自动打开最早生成的章节（新建书首轮批次结束 → 编辑器立即可用，
  // 「单章生成」随之可点）；用户已手动选中则不动。chapters 异步更新，依赖两者兜底。
  useEffect(() => {
    if (taskPhase !== 'terminal' || chapters.length === 0 || selectedCid) return
    const first = [...chapters].sort((a, b) => a.chapter_seq - b.chapter_seq)[0]
    setSelectedCid(first.id)
  }, [taskPhase, chapters, selectedCid])

  const selectedChapter = chapters.find((c) => c.id === selectedCid) ?? null

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
        <TaskHistory projectId={projectId} activeTaskId={activeTaskId} />
        <TaskTimeline
          taskId={activeTaskId}
          phase={task.phase}
          status={task.status}
          nodes={task.nodes}
          runs={task.runs}
          progress={task.progress}
          error={task.error}
          onRetry={task.retry}
          canControl={batchTotal !== null}
          refresh={task.refresh}
        />
        <AuditPanel runs={task.runs} onNavigateChapter={handleNavigateChapter} />
        <CandidatePanel
          projectId={projectId}
          candidates={candidates}
          onChanged={loadCandidates}
        />
        <LessonsPanel projectId={projectId} />
      </aside>
    </div>
  )
}
