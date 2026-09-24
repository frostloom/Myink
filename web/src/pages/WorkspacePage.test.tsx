// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import type { AgentRun, ChapterMeta } from '../types'
import WorkspacePage from './WorkspacePage'

const liveTask = vi.hoisted(() => ({
  runs: [] as AgentRun[],
  artifacts: [] as Array<{
    artifactId: string
    taskId: string
    stage: string
    chapterSeq: number
    attempt: number
    content: string
    complete: boolean
    failed: boolean
    artifact: unknown | null
    message: string | null
  }>,
}))

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ logout: vi.fn(), session: { userId: 'test-user', username: 'alice' } }),
}))

vi.mock('../hooks/useTaskEvents', () => ({
  useTaskEvents: (taskId: string | null) => ({
    phase: taskId ? 'running' : 'idle',
    status: taskId ? 'running' : null,
    nodes: [],
    artifacts: taskId ? liveTask.artifacts : [],
    runs: taskId ? liveTask.runs : [],
    progress: null,
    error: null,
    payload: {},
    lastEventId: null,
    stop: vi.fn(),
    retry: vi.fn(),
    refresh: vi.fn(),
  }),
}))

vi.mock('../components/ProjectRail', () => ({ ProjectRail: () => <div /> }))
vi.mock('../components/LessonsPanel', () => ({ LessonsPanel: () => <div>lessons-panel</div> }))
vi.mock('../components/AuditPanel', () => ({ AuditPanel: () => <div>audit-panel</div> }))
vi.mock('../components/CandidatePanel', () => ({ CandidatePanel: () => <div>candidate-panel</div> }))
vi.mock('../components/ShortStoryPanel', () => ({
  ShortStoryPanel: ({ runs }: { runs: AgentRun[] }) => <div>short-review-{runs.length}</div>,
}))
vi.mock('../components/ChapterEditor', () => ({
  ChapterEditor: ({ chapter }: { chapter: ChapterMeta }) => <div>editor-{chapter.chapter_seq}</div>,
}))
vi.mock('../components/ChapterPlanPanel', () => ({
  ChapterPlanPanel: ({ taskId, chapterSeq, onConfirmed }: {
    taskId: string | null
    chapterSeq: number
    onConfirmed: (taskId: string, chapterSeq: number) => void
  }) => <div>
    <span>plan-page-{chapterSeq}</span>
    <button type="button" onClick={() => taskId && onConfirmed(taskId, chapterSeq)}>confirm-plan</button>
  </div>,
}))
vi.mock('../components/StreamingChapterView', () => ({
  StreamingChapterView: ({ chapterSeq }: { chapterSeq: number }) => (
    <section aria-label={`第 ${chapterSeq} 章生成正文`}>write-page-{chapterSeq}</section>
  ),
}))
vi.mock('../components/ChapterList', () => ({
  ChapterList: ({ chapters, onSelect }: { chapters: ChapterMeta[]; onSelect: (id: string) => void }) => (
    <div>
      {chapters.map((chapter) => (
        <button key={chapter.id} type="button" onClick={() => onSelect(chapter.id)}>
          chapter-{chapter.chapter_seq}
        </button>
      ))}
    </div>
  ),
}))
vi.mock('../components/GenerationPanel', () => ({
  GenerationPanel: ({ onTaskStart }: {
    onTaskStart: (id: string, total?: number, seq?: number) => void
  }) => (
    <div>
      <span>generation-panel</span>
      <button type="button" onClick={() => onTaskStart('task-13', undefined, 13)}>start-13</button>
    </div>
  ),
}))
vi.mock('../components/TaskTimeline', () => ({
  TaskTimeline: ({ taskId, chapterSeq }: { taskId: string | null; chapterSeq: number | null }) => (
    <div>timeline-{taskId ?? 'none'}-chapter-{chapterSeq ?? 'none'}</div>
  ),
}))

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      listProjects: vi.fn(),
      listChapters: vi.fn(),
      listCandidates: vi.fn(),
      listGraph: vi.fn(),
      listForeshadows: vi.fn(),
      listTasks: vi.fn(),
      generateShort: vi.fn(),
    },
  }
})

const chapter12: ChapterMeta = {
  id: 'chapter-12',
  chapter_seq: 12,
  title: null,
  status: 'confirmed',
  word_count: 3000,
  summary: null,
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  liveTask.artifacts = []
  liveTask.runs = []
  sessionStorage.clear()
})

it('keeps auto Plan full-page until the first real Write artifact then flips once', async () => {
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.listChapters)
    .mockResolvedValueOnce([chapter12])
    .mockImplementation(() => new Promise<ChapterMeta[]>(() => {}))
  vi.mocked(api.listCandidates).mockResolvedValue([])
  vi.mocked(api.listGraph).mockResolvedValue({ nodes: [], edges: [] })
  vi.mocked(api.listForeshadows).mockResolvedValue([])
  vi.mocked(api.listTasks).mockResolvedValue([])

  const router = createMemoryRouter(
    [{ path: '/projects/:projectId', element: <WorkspacePage /> }],
    { initialEntries: ['/projects/project-1'] },
  )
  render(<RouterProvider router={router} />)

  fireEvent.click(await screen.findByRole('button', { name: 'chapter-12' }))
  fireEvent.click(screen.getByRole('button', { name: 'start-13' }))
  expect(await screen.findByText('plan-page-13')).toBeTruthy()
  expect(screen.queryByText('write-page-13')).toBeNull()

  liveTask.artifacts = [{
    artifactId: 'plan-1', taskId: 'task-13', stage: 'plan', chapterSeq: 13,
    attempt: 1, content: '{"goals":["推进"]}', complete: true,
    failed: false, artifact: null, message: null,
  }]
  await act(async () => { await router.navigate('/projects/project-1?stream=plan') })
  expect(await screen.findByText('plan-page-13')).toBeTruthy()

  liveTask.artifacts = [...liveTask.artifacts, {
    artifactId: 'write-1', taskId: 'task-13', stage: 'write', chapterSeq: 13,
    attempt: 1, content: '第一段', complete: false,
    failed: false, artifact: null, message: null,
  }]
  await act(async () => { await router.navigate('/projects/project-1?stream=write') })
  expect(await screen.findByText('write-page-13')).toBeTruthy()
  expect(screen.queryByText('plan-page-13')).toBeNull()

  fireEvent.click(screen.getByRole('button', { name: /Plan/ }))
  expect(await screen.findByText('plan-page-13')).toBeTruthy()
  liveTask.artifacts = liveTask.artifacts.map((item) => (
    item.stage === 'write' ? { ...item, content: '第一段和第二段' } : item
  ))
  await act(async () => { await router.navigate('/projects/project-1?stream=delta') })
  expect(screen.getByText('plan-page-13')).toBeTruthy()
  expect(screen.queryByText('write-page-13')).toBeNull()
})

it('creates and selects chapter 13 before showing its task flow', async () => {
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.listChapters)
    .mockResolvedValueOnce([chapter12])
    // 保持 worker 尚未返回真实章节的瞬间，验证前端先建立目标章页面。
    .mockImplementation(() => new Promise<ChapterMeta[]>(() => {}))
  vi.mocked(api.listCandidates).mockResolvedValue([])
  vi.mocked(api.listGraph).mockResolvedValue({ nodes: [], edges: [] })
  vi.mocked(api.listForeshadows).mockResolvedValue([])
  vi.mocked(api.listTasks).mockResolvedValue([])

  const router = createMemoryRouter(
    [{ path: '/projects/:projectId', element: <WorkspacePage /> }],
    { initialEntries: ['/projects/project-1'] },
  )
  render(<RouterProvider router={router} />)

  fireEvent.click(await screen.findByRole('button', { name: 'chapter-12' }))
  await screen.findByText('editor-12')
  fireEvent.click(screen.getByRole('button', { name: 'start-13' }))

  expect(await screen.findByText('plan-page-13')).toBeTruthy()
  expect(screen.queryByRole('region', { name: '第 13 章生成正文' })).toBeNull()
  expect(screen.getByText('timeline-task-13-chapter-13')).toBeTruthy()
  expect(screen.queryByText('timeline-task-13-chapter-12')).toBeNull()
  await waitFor(() => expect(screen.getByRole('button', { name: 'chapter-13' })).toBeTruthy())

  fireEvent.click(screen.getByRole('button', { name: 'confirm-plan' }))
  expect(await screen.findByRole('region', { name: '第 13 章生成正文' })).toBeTruthy()
  expect(screen.queryByText('plan-page-13')).toBeNull()

  fireEvent.click(screen.getByRole('button', { name: /Plan/ }))
  expect(await screen.findByText('plan-page-13')).toBeTruthy()
  expect(screen.queryByRole('region', { name: '第 13 章生成正文' })).toBeNull()

  fireEvent.click(screen.getByRole('button', { name: /正文/ }))
  expect(await screen.findByText('write-page-13')).toBeTruthy()
  expect(screen.queryByText('plan-page-13')).toBeNull()
})

it('ignores a late chapter list from the previous book after switching projects', async () => {
  const bookAChapter: ChapterMeta = {
    id: 'chapter-3',
    chapter_seq: 3,
    title: null,
    status: 'planning',
    word_count: 0,
    summary: null,
  }
  let resolveA: (value: ChapterMeta[]) => void = () => {}
  const bookAPending = new Promise<ChapterMeta[]>((resolve) => { resolveA = resolve })

  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.listChapters).mockImplementation((pid: string) => (
    pid === 'project-a' ? bookAPending : Promise.resolve([])
  ))
  vi.mocked(api.listCandidates).mockResolvedValue([])
  vi.mocked(api.listGraph).mockResolvedValue({ nodes: [], edges: [] })
  vi.mocked(api.listForeshadows).mockResolvedValue([])
  vi.mocked(api.listTasks).mockResolvedValue([])

  const router = createMemoryRouter(
    [{ path: '/projects/:projectId', element: <WorkspacePage /> }],
    { initialEntries: ['/projects/project-a'] },
  )
  render(<RouterProvider router={router} />)

  await act(async () => { await router.navigate('/projects/project-b') })
  await act(async () => { resolveA([bookAChapter]) })

  expect(screen.queryByRole('button', { name: 'chapter-3' })).toBeNull()
  expect(screen.getByText('还没有章节。在右侧发起首次生成。')).toBeTruthy()
})

it('reconnects from the remembered write when the worker has not persisted the task yet', async () => {
  sessionStorage.setItem('myink.activeWrite.test-user.project-a', JSON.stringify({
    taskId: 'task-2', chapterSeq: 2, batchTotal: null,
  }))
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.listChapters).mockResolvedValue([])
  vi.mocked(api.listCandidates).mockResolvedValue([])
  vi.mocked(api.listGraph).mockResolvedValue({ nodes: [], edges: [] })
  vi.mocked(api.listForeshadows).mockResolvedValue([])
  vi.mocked(api.listTasks).mockResolvedValue([])

  const router = createMemoryRouter(
    [{ path: '/projects/:projectId', element: <WorkspacePage /> }],
    { initialEntries: ['/projects/project-b'] },
  )
  render(<RouterProvider router={router} />)
  await screen.findByText('还没有章节。在右侧发起首次生成。')

  await act(async () => { await router.navigate('/projects/project-a') })

  expect(await screen.findByText('plan-page-2')).toBeTruthy()
  expect(screen.getByText('timeline-task-2-chapter-2')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'chapter-2' })).toBeTruthy()
})

it('reconnects an in-flight writing task after switching back before the chapter row exists', async () => {
  const running = {
    task_id: 'task-3',
    task_type: 'chapter_generate' as const,
    status: 'running' as const,
    chapter_seq: 3,
    batch_size: null,
    batch_current: null,
    cost_total: 0,
    error: null,
    created_at: null,
  }
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.listChapters).mockResolvedValue([])
  vi.mocked(api.listCandidates).mockResolvedValue([])
  vi.mocked(api.listGraph).mockResolvedValue({ nodes: [], edges: [] })
  vi.mocked(api.listForeshadows).mockResolvedValue([])
  vi.mocked(api.listTasks).mockImplementation((pid: string) => (
    pid === 'project-a' ? Promise.resolve([running]) : Promise.resolve([])
  ))

  const router = createMemoryRouter(
    [{ path: '/projects/:projectId', element: <WorkspacePage /> }],
    { initialEntries: ['/projects/project-b'] },
  )
  render(<RouterProvider router={router} />)
  await screen.findByText('还没有章节。在右侧发起首次生成。')

  await act(async () => { await router.navigate('/projects/project-a') })

  expect(await screen.findByText('plan-page-3')).toBeTruthy()
  expect(screen.getByText('timeline-task-3-chapter-3')).toBeTruthy()
})

const shortProject = {
  id: 'project-1',
  title: '渡口',
  genre: '悬疑',
  current_chapter: 5,
  target_words: 2000,
  form: 'short' as const,
}

const shortTask = {
  task_id: 'task-short',
  task_type: 'short_generate',
  status: 'done' as const,
  chapter_seq: null,
  batch_size: null,
  batch_current: null,
  cost_total: 0.25,
  error: null,
  created_at: null,
}

const shortReviewRun: AgentRun = {
  task_id: 'task-short',
  node: 'short_review',
  model_id: 'deepseek-chat',
  input_tokens: 100,
  output_tokens: 200,
  cache_hit: false,
  duration_ms: 1000,
  cost_est: 0.1,
  retry_count: 0,
  degraded: false,
  error: null,
  detail: {
    short_review: { verdict: 'pass', issues: [], suggestions: [], warning: null },
    empty_chapters: [],
    length_findings: [],
    revised: false,
  },
}

function shortBookChapters(): ChapterMeta[] {
  return [1, 2, 3, 4, 5].map((seq) => ({
    id: `chapter-${seq}`,
    chapter_seq: seq,
    title: null,
    status: 'confirmed' as const,
    word_count: 2000,
    summary: null,
  }))
}

function mockShortBook(taskList: unknown[]) {
  vi.mocked(api.listProjects).mockResolvedValue([shortProject])
  vi.mocked(api.listChapters).mockResolvedValue(shortBookChapters())
  vi.mocked(api.listCandidates).mockResolvedValue([])
  vi.mocked(api.listGraph).mockResolvedValue({ nodes: [], edges: [] })
  vi.mocked(api.listForeshadows).mockResolvedValue([])
  vi.mocked(api.listTasks).mockResolvedValue(taskList as never)
}

function renderWorkspace(state?: Record<string, unknown>) {
  const router = createMemoryRouter(
    [{ path: '/projects/:projectId', element: <WorkspacePage /> }],
    { initialEntries: [{ pathname: '/projects/project-1', state }] },
  )
  render(<RouterProvider router={router} />)
  return router
}

it('renders no right column for a short book, and a status band instead', async () => {
  mockShortBook([])
  renderWorkspace()

  // 短篇没有右栏那一整套：生成面板、章节流转、审计/候选/经验都不该出现。
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('还没开始写'))
  expect(screen.getByRole('button', { name: '开始写' })).toBeTruthy()
  expect(screen.queryByText('generation-panel')).toBeNull()
  expect(screen.queryByText(/timeline-/)).toBeNull()
  expect(screen.queryByText('audit-panel')).toBeNull()
  expect(screen.queryByText('candidate-panel')).toBeNull()
  expect(screen.queryByText('lessons-panel')).toBeNull()
})

it('shows the plan warning on the short status band', async () => {
  mockShortBook([])
  renderWorkspace({ planWarning: '每章字数已按全篇上限归一' })

  expect((await screen.findByRole('status')).textContent).toContain('每章字数已按全篇上限归一')
})

it('auto-starts the short generation once on handover, then strips the intent', async () => {
  vi.mocked(api.generateShort).mockResolvedValue({ task_id: 'task-1', trace_id: 'trace-1', status: 'queued' })
  mockShortBook([])
  const router = renderWorkspace({ beginShortWriting: true })

  // 建书页确认完跳进来那一次：本页负责入队（状态带上才有重试入口）。
  await waitFor(() => expect(api.generateShort).toHaveBeenCalledWith('project-1'))
  await waitFor(() => expect(api.generateShort).toHaveBeenCalledTimes(1))
  // 意图被吃掉：history.state 上换成普通状态，硬刷新带不回来（带回来就是白花一次配额）。
  await waitFor(() => expect(router.state.location.state?.beginShortWriting).toBeUndefined())

  await act(async () => {
    await router.navigate('/projects/project-1', { replace: true, state: { beginShortWriting: true } })
  })
  expect(api.generateShort).toHaveBeenCalledTimes(1)
})

it('tells the reader the start failed and offers the retry that re-enqueues', async () => {
  vi.mocked(api.generateShort).mockRejectedValueOnce(new Error('gateway'))
  mockShortBook([])
  renderWorkspace({ beginShortWriting: true })

  // 入队是真失败了（回查确认没有任务）：状态带要说实话，并把重试摆在手边。
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('没能开始写'))
  const retry = screen.getByRole('button', { name: '重试' })
  vi.mocked(api.generateShort).mockResolvedValue({ task_id: 'task-1', trace_id: 'trace-1', status: 'queued' })
  await act(async () => { retry.click() })
  await waitFor(() => expect(api.generateShort).toHaveBeenCalledTimes(2))
  expect(api.generateShort).toHaveBeenLastCalledWith('project-1')
})

it('adopts a task that exists when the enqueue answer is lost, instead of claiming nothing started', async () => {
  // 服务端收到了这次入队（所以之后回查能看到任务），但回包丢了。任务从「拒绝落地」那一刻
  // 起才存在——挂载时那些回查（244、恢复）看得见的仍然是空书。
  let enqueued = false
  vi.mocked(api.generateShort).mockImplementation(() =>
    Promise.reject(new Error('timeout')).finally(() => { enqueued = true }))
  mockShortBook([])
  vi.mocked(api.listTasks).mockImplementation(() =>
    Promise.resolve((enqueued ? [{ ...shortTask, task_id: 'task-lost', status: 'running' }] : []) as never))
  renderWorkspace({ beginShortWriting: true })

  // 整篇其实在写。说「没能开始写」是把用户往死重试上引（重试还会被并发闸 429 挡掉），
  // 所以这里必须接上那条任务。
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('正在写整篇'))
  expect(screen.getByRole('status').textContent).not.toContain('没能开始写')
  expect(screen.queryByRole('button', { name: '重试' })).toBeNull()
})

it('does not auto-start when the handover did not ask for it', async () => {
  vi.mocked(api.generateShort).mockResolvedValue({ task_id: 'task-1', trace_id: 'trace-1', status: 'queued' })
  mockShortBook([])
  renderWorkspace({ planWarning: null })

  expect(await screen.findByRole('status')).toBeTruthy()
  await act(async () => { await Promise.resolve() })
  expect(api.generateShort).not.toHaveBeenCalled()
})

it('keeps the whole-story review reachable after a chapter is picked on a short book', async () => {
  mockShortBook([shortTask])
  liveTask.runs = [shortReviewRun]
  renderWorkspace()

  // 整篇任务不属于任何一章：按章切会把审稿报告整块滤空，所以中栏用的是整表取到的 runs。
  const review = await screen.findByText('short-review-1')
  expect(review.closest('details')).toBeTruthy()
  expect(screen.getByText('审稿结论')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: 'chapter-2' }))
  await screen.findByText('write-page-2')

  expect(screen.getByText('short-review-1')).toBeTruthy()
})

it('still shows the long-form panels on a book without a form', async () => {
  vi.mocked(api.listProjects).mockResolvedValue([{ ...shortProject, form: undefined }])
  vi.mocked(api.listChapters).mockResolvedValue([])
  vi.mocked(api.listCandidates).mockResolvedValue([])
  vi.mocked(api.listGraph).mockResolvedValue({ nodes: [], edges: [] })
  vi.mocked(api.listForeshadows).mockResolvedValue([])
  vi.mocked(api.listTasks).mockResolvedValue([])
  renderWorkspace()

  expect(await screen.findByText('generation-panel')).toBeTruthy()
  expect(screen.queryByRole('status')).toBeNull()
  expect(screen.getByText('audit-panel')).toBeTruthy()
  expect(screen.getByText('candidate-panel')).toBeTruthy()
  expect(screen.getByText('lessons-panel')).toBeTruthy()
  expect(screen.queryByText('short-review-0')).toBeNull()
})

it('never shows the plan stage for a short book', async () => {
  vi.mocked(api.generateShort).mockResolvedValue({ task_id: 'task-1', trace_id: 'trace-1', status: 'queued' })
  mockShortBook([])
  renderWorkspace()

  fireEvent.click(await screen.findByRole('button', { name: 'chapter-2' }))
  await screen.findByText('editor-2')
  // 起任务：只有任务在途时 nav 才会渲染，否则下面那条 null 断言是空的（P50）
  fireEvent.click(screen.getByRole('button', { name: '开始写' }))

  // 正向对照：nav 确实渲染出来了（正文阶段还在），证明下面那条 null 不是「整块没渲染」
  expect(await screen.findByRole('button', { name: /正文/ })).toBeTruthy()
  expect(screen.queryByRole('button', { name: /Plan/ })).toBeNull()
})
