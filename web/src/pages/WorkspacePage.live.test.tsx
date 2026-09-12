// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import { openSSE, type SSEEvent } from '../lib/sse'
import type { ChapterMeta, TaskDetail, TaskSummary } from '../types'
import WorkspacePage from './WorkspacePage'

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ logout: vi.fn() }),
}))
vi.mock('../components/ProjectRail', () => ({ ProjectRail: () => <div /> }))
vi.mock('../components/LessonsPanel', () => ({ LessonsPanel: () => <div /> }))
vi.mock('../components/AuditPanel', () => ({ AuditPanel: () => <div /> }))
vi.mock('../components/CandidatePanel', () => ({ CandidatePanel: () => <div /> }))
vi.mock('../components/GenerationPanel', () => ({ GenerationPanel: () => <div /> }))
vi.mock('../components/TaskTimeline', () => ({ TaskTimeline: () => <div /> }))
vi.mock('../components/ChapterEditor', () => ({ ChapterEditor: () => <div>saved-chapter</div> }))
vi.mock('../components/ChapterPlanPanel', () => ({
  ChapterPlanPanel: () => <section>live-plan-page</section>,
}))
vi.mock('../lib/sse', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/sse')>()),
  openSSE: vi.fn(),
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
      getTask: vi.fn(),
    },
  }
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('replaces the full Plan page with live正文 before the model stream completes', async () => {
  const chapter: ChapterMeta = {
    id: 'chapter-14', chapter_seq: 14, title: null,
    status: 'planning', word_count: 0, summary: null,
  }
  const summary: TaskSummary = {
    task_id: 'task-14', task_type: 'chapter_generate', status: 'running',
    chapter_seq: 14, batch_size: null, batch_current: null,
    cost_total: 0, error: null, created_at: null,
  }
  const detail: TaskDetail = {
    task_id: 'task-14', task_type: 'chapter_generate', status: 'running',
    payload: { seq: 14, mode: 'auto' }, error: null, retry_count: 0,
    trace_id: null, chapter_seq: 14, batch_task_id: null,
    created_at: null, cost_total: 0, runs: [],
  }
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.listChapters).mockResolvedValue([chapter])
  vi.mocked(api.listCandidates).mockResolvedValue([])
  vi.mocked(api.listGraph).mockResolvedValue({ nodes: [], edges: [] })
  vi.mocked(api.listForeshadows).mockResolvedValue([])
  vi.mocked(api.listTasks).mockResolvedValue([summary])
  vi.mocked(api.getTask).mockResolvedValue(detail)

  let startWrite!: () => void
  let finishStream!: () => void
  const waitForWrite = new Promise<void>((resolve) => { startWrite = resolve })
  const waitForFinish = new Promise<void>((resolve) => { finishStream = resolve })
  const event = (patch: Partial<SSEEvent>): SSEEvent => ({
    type: 'artifact_delta', task_id: 'task-14', node: '', status: '', message: '',
    stage: 'plan', chapter_seq: 14, attempt: 1, offset: 0,
    artifact_id: 'plan-1', content: '', artifact: '', ...patch,
  })

  vi.mocked(openSSE).mockImplementation(async (_url, onEvent) => {
    onEvent(event({ type: 'status', status: 'running' }))
    onEvent(event({ type: 'artifact_reset' }))
    onEvent(event({ type: 'artifact_delta', content: '{"goals":["承接"]}' }))
    onEvent(event({ type: 'artifact_complete', offset: 16 }))
    await waitForWrite
    onEvent(event({
      type: 'artifact_reset', stage: 'write', artifact_id: 'write-1',
    }))
    onEvent(event({
      type: 'artifact_delta', stage: 'write', artifact_id: 'write-1',
      content: '=== CONTENT ===\n模型仍在写，这段已经到达浏览器',
    }))
    await waitForFinish
    onEvent(event({
      type: 'artifact_complete', stage: 'write', artifact_id: 'write-1', offset: 21,
    }))
    onEvent(event({ type: 'status', status: 'awaiting_review' }))
    return { reason: 'terminal' }
  })

  const router = createMemoryRouter(
    [{ path: '/projects/:projectId', element: <WorkspacePage /> }],
    { initialEntries: ['/projects/project-1'] },
  )
  render(<RouterProvider router={router} />)

  expect(await screen.findByText('live-plan-page')).toBeTruthy()
  expect(screen.queryByText('模型仍在写，这段已经到达浏览器')).toBeNull()

  await act(async () => { startWrite() })
  expect(await screen.findByText('模型仍在写，这段已经到达浏览器')).toBeTruthy()
  expect(screen.getByText('实时写作', { selector: 'span' })).toBeTruthy()
  expect(screen.queryByText('live-plan-page')).toBeNull()
  expect(vi.mocked(openSSE).mock.results[0]?.type).toBe('return')

  await act(async () => { finishStream() })
  await waitFor(() => expect(api.getTask).toHaveBeenCalled())
})
