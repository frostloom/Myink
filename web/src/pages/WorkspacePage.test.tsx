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
  GenerationPanel: ({ form, onTaskStart }: { form?: string; onTaskStart: (id: string, total?: number, seq?: number) => void }) => (
    <div>
      <span>gen-form-{form ?? 'long'}</span>
      <button type="button" onClick={() => onTaskStart('task-13', undefined, 13)}>start-13</button>
      {form === 'short' && <button type="button" onClick={() => onTaskStart('task-short')}>start-short</button>}
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

it('keeps the whole-story review reachable after a chapter is picked on a short book', async () => {
  mockShortBook([shortTask])
  liveTask.runs = [shortReviewRun]

  const router = createMemoryRouter(
    [{ path: '/projects/:projectId', element: <WorkspacePage /> }],
    { initialEntries: ['/projects/project-1'] },
  )
  render(<RouterProvider router={router} />)

  expect(await screen.findByText('gen-form-short')).toBeTruthy()
  // 整篇任务不属于任何一章：按章取任务会一条都取不到，审稿报告就整块消失了。
  expect(await screen.findByText('short-review-1')).toBeTruthy()
  expect(screen.getByText('timeline-task-short-chapter-none')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: 'chapter-2' }))
  await screen.findByText('write-page-2')

  fireEvent.click(screen.getByRole('button', { name: 'start-short' }))
  // 整篇任务不产出章节 Plan，翻到 Plan 页只会永远停在「等待计划」。
  expect(screen.queryByText('plan-page-2')).toBeNull()

  expect(screen.getByText('short-review-1')).toBeTruthy()
  expect(screen.getByText('timeline-task-short-chapter-none')).toBeTruthy()
})

it('shows the short-form panels instead of the long-form ones on a short book', async () => {
  mockShortBook([])

  const router = createMemoryRouter(
    [{ path: '/projects/:projectId', element: <WorkspacePage /> }],
    { initialEntries: ['/projects/project-1'] },
  )
  render(<RouterProvider router={router} />)

  expect(await screen.findByText('gen-form-short')).toBeTruthy()
  expect(screen.getByText('short-review-0')).toBeTruthy()
  expect(screen.queryByText('audit-panel')).toBeNull()
  expect(screen.queryByText('candidate-panel')).toBeNull()
  expect(screen.queryByText('lessons-panel')).toBeNull()
})

it('still shows the long-form panels on a book without a form', async () => {
  vi.mocked(api.listProjects).mockResolvedValue([{ ...shortProject, form: undefined }])
  vi.mocked(api.listChapters).mockResolvedValue([])
  vi.mocked(api.listCandidates).mockResolvedValue([])
  vi.mocked(api.listGraph).mockResolvedValue({ nodes: [], edges: [] })
  vi.mocked(api.listForeshadows).mockResolvedValue([])
  vi.mocked(api.listTasks).mockResolvedValue([])

  const router = createMemoryRouter(
    [{ path: '/projects/:projectId', element: <WorkspacePage /> }],
    { initialEntries: ['/projects/project-1'] },
  )
  render(<RouterProvider router={router} />)

  expect(await screen.findByText('gen-form-long')).toBeTruthy()
  expect(screen.getByText('audit-panel')).toBeTruthy()
  expect(screen.getByText('candidate-panel')).toBeTruthy()
  expect(screen.getByText('lessons-panel')).toBeTruthy()
  expect(screen.queryByText('short-review-0')).toBeNull()
})
