// 工作台（三栏）：rail 项目切换 + 章节列表 | 章节编辑器 | 生成入口/时间线/校验报告。
// 生成任务进度状态在页面级提升：useTaskEvents(activeTaskId)，终态 → 刷新章节列表。
import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { AuditPanel } from '../components/AuditPanel'
import { ChapterEditor } from '../components/ChapterEditor'
import { ChapterList } from '../components/ChapterList'
import { GenerationPanel } from '../components/GenerationPanel'
import { ProjectRail } from '../components/ProjectRail'
import { TaskTimeline } from '../components/TaskTimeline'
import { useAuth } from '../context/AuthContext'
import { useTaskEvents } from '../hooks/useTaskEvents'
import { api, ApiError } from '../lib/api'
import type { ChapterMeta, Project } from '../types'
import styles from './WorkspacePage.module.css'

export default function WorkspacePage() {
  const { projectId = '' } = useParams()
  const { logout } = useAuth()

  const [projects, setProjects] = useState<Project[]>([])
  const [chapters, setChapters] = useState<ChapterMeta[]>([])
  const [selectedCid, setSelectedCid] = useState<string | null>(null)
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshTick, setRefreshTick] = useState(0)

  const loadProjects = useCallback(() => {
    api.listProjects().then(setProjects).catch(() => setProjects([]))
  }, [])

  const loadChapters = useCallback(async () => {
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
    loadProjects()
    void loadChapters()
  }, [loadProjects, loadChapters])

  const task = useTaskEvents(activeTaskId)
  const taskPhase = task.phase

  // 生成任务进入终态/过期 → 章节状态与内容已更新：刷新列表 + 让编辑器重拉当前章正文
  useEffect(() => {
    if (taskPhase === 'terminal' || taskPhase === 'expired' || taskPhase === 'error') {
      void loadChapters()
      setRefreshTick((t) => t + 1)
    }
  }, [taskPhase, loadChapters])

  const selectedChapter = chapters.find((c) => c.id === selectedCid) ?? null

  const handleNotFound = useCallback(() => {
    setSelectedCid(null)
    void loadChapters()
  }, [loadChapters])

  const handleSaved = useCallback(() => {
    void loadChapters()
  }, [loadChapters])

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
        <h3 className={styles.sideTitle}>章节</h3>
        <ChapterList
          chapters={chapters}
          selectedCid={selectedCid}
          onSelect={setSelectedCid}
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
          onTaskStart={setActiveTaskId}
        />
        <TaskTimeline
          taskId={activeTaskId}
          phase={task.phase}
          status={task.status}
          nodes={task.nodes}
          runs={task.runs}
          progress={task.progress}
          error={task.error}
          onRetry={task.retry}
        />
        <AuditPanel runs={task.runs} onNavigateChapter={handleNavigateChapter} />
      </aside>
    </div>
  )
}
