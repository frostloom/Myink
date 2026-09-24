// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { adminApi, type AdminMetrics, type AdminProject } from '../lib/adminApi'
import AdminPage, { AdminConsole } from './AdminPage'
import { ProjectDetailPage } from './admin/ProjectDetail'
import { RunDetailPage } from './admin/RunDetail'
import { TaskDetailPage } from './admin/TaskDetail'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../lib/adminApi', async (original) => {
  const actual = await original<typeof import('../lib/adminApi')>()
  return {
    ...actual,
    adminApi: Object.fromEntries(
      Object.keys(actual.adminApi).map((key) => [key, vi.fn()]),
    ) as unknown as typeof actual.adminApi,
  }
})

const metrics: AdminMetrics = {
  run_count: 2, input_tokens: 1200, output_tokens: 800, cost_est: 0.42, duration_ms: 3500,
}

const taskAverages = {
  avg_cost_per_task: 0.21, avg_duration_ms_per_task: 1750, avg_runs_per_task: 2,
}

const book: AdminProject = {
  id: 'book-1', user_id: 'user-1', username: 'alice', title: '山河册', genre: '奇幻',
  current_chapter: 2, target_words: 100000, creation_status: 'ready',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z',
  chapter_count: 2, word_count: 4500, task_count: 1, metrics, task_averages: taskAverages,
}

const limits = { max_depth: 10, max_items: 80, max_text: 16000, max_bytes: 65536 }

const auth = {
  session: {
    token: 'token-admin', userId: 'admin-1', username: 'root', tier: 'normal',
    role: 'admin' as const, roleVerified: true, expiresAt: Date.now() + 60_000,
  },
  status: 'authenticated' as const,
  revalidate: vi.fn(),
  logout: vi.fn(),
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

// 详情页是 /admin 下的子路由（闸门与外壳都在父路由上），测试也得按同一棵树挂载。
function buildRouter(initialEntry = '/admin') {
  return createMemoryRouter([
    {
      path: '/admin',
      element: <AdminPage />,
      children: [
        { index: true, element: <AdminConsole /> },
        { path: 'projects/:projectId', element: <ProjectDetailPage /> },
        { path: 'tasks/:taskId', element: <TaskDetailPage /> },
        { path: 'runs/:runId', element: <RunDetailPage /> },
      ],
    },
  ], { initialEntries: [initialEntry] })
}

function renderPage(initialEntry = '/admin') {
  const router = buildRouter(initialEntry)
  return { ...render(<RouterProvider router={router} />), router }
}

beforeEach(() => {
  vi.mocked(useAuth).mockReturnValue(auth as unknown as ReturnType<typeof useAuth>)
  auth.revalidate.mockReset()
  // mockResolvedValue 不会清掉上一轮留下的 mockResolvedValueOnce 队列，必须逐个 mockReset。
  for (const fn of Object.values(adminApi)) vi.mocked(fn).mockReset()
  vi.mocked(adminApi.getOverview).mockResolvedValue({
    user_count: 4, project_count: 6, chapter_count: 18, task_count: 9,
    metrics, task_status_counts: { queued: 2, completed: 7 },
  })
  vi.mocked(adminApi.listProjects).mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 })
  vi.mocked(adminApi.getProject).mockResolvedValue(book)
  vi.mocked(adminApi.listTasks).mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 })
  vi.mocked(adminApi.listRuns).mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 })
  vi.mocked(adminApi.listAccessLogs).mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('shows the global overview with labeled metrics and status counts', async () => {
  renderPage()

  expect(await screen.findByRole('heading', { name: '管理员控制台' })).toBeTruthy()
  expect(await screen.findByText('4')).toBeTruthy()
  expect(screen.getByText('预估成本')).toBeTruthy()
  expect(screen.getByText('排队中')).toBeTruthy()
})

it('opens the tab named in the url instead of always landing on the overview', async () => {
  vi.mocked(adminApi.listAccessLogs).mockResolvedValue({
    items: [{ id: 2, actor_id: 'admin-1', action: 'admin.overview', target: 'collection', created_at: '2026-01-01T00:00:00Z' }],
    total: 1, limit: 25, offset: 0,
  })
  renderPage('/admin?tab=logs')

  expect(await screen.findByText('admin.overview')).toBeTruthy()
  expect(screen.getByRole('button', { name: '访问日志' }).getAttribute('aria-pressed')).toBe('true')
})

it('does not request or render protected data for a normal user', () => {
  vi.mocked(useAuth).mockReturnValue({
    ...auth,
    session: { ...auth.session, role: 'user', roleVerified: true },
  } as unknown as ReturnType<typeof useAuth>)
  renderPage()
  expect(screen.queryByText('管理员控制台')).toBeNull()
  expect(adminApi.getOverview).not.toHaveBeenCalled()
})

it('does not trust an authenticated cached admin whose role is not server-verified', () => {
  vi.mocked(useAuth).mockReturnValue({
    ...auth,
    status: 'authenticated',
    session: { ...auth.session, role: 'admin', roleVerified: false },
  } as unknown as ReturnType<typeof useAuth>)
  renderPage()
  expect(screen.queryByText('管理员控制台')).toBeNull()
  expect(adminApi.getOverview).not.toHaveBeenCalled()
})

it('discards an old account response after the token changes', async () => {
  const oldResult = deferred<Awaited<ReturnType<typeof adminApi.getOverview>>>()
  vi.mocked(adminApi.getOverview)
    .mockReturnValueOnce(oldResult.promise)
    .mockResolvedValueOnce({
      user_count: 2, project_count: 1, chapter_count: 3, task_count: 1,
      metrics: { ...metrics, run_count: 1 }, task_status_counts: {},
    })
  const view = renderPage()

  vi.mocked(useAuth).mockReturnValue({
    ...auth,
    session: { ...auth.session, token: 'token-admin-b', userId: 'admin-2' },
  } as unknown as ReturnType<typeof useAuth>)
  // 换一个 router 实例：同一个实例上父组件重渲染不会改路由树，也就不会重挂载子树。
  view.rerender(<RouterProvider router={buildRouter()} />)
  expect(await screen.findByText('2')).toBeTruthy()

  oldResult.resolve({
    user_count: 99, project_count: 99, chapter_count: 99, task_count: 99,
    metrics, task_status_counts: {},
  })
  await Promise.resolve()
  expect(screen.queryByText('99')).toBeNull()
})

it('clears protected content and revalidates when an admin request returns 403', async () => {
  vi.mocked(adminApi.getOverview)
    .mockResolvedValueOnce({
      user_count: 4, project_count: 6, chapter_count: 18, task_count: 9,
      metrics, task_status_counts: {},
    })
    .mockRejectedValueOnce(new ApiError(403, 'FORBIDDEN', null))
  renderPage()
  expect(await screen.findByText('18')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '刷新当前视图' }))

  expect((await screen.findByRole('alert')).textContent).toContain('管理员权限已变化')
  expect(screen.queryByText('18')).toBeNull()
  expect(auth.revalidate).toHaveBeenCalledTimes(1)
})

it('leaves the console for a book detail page and comes back to the projects tab', async () => {
  vi.mocked(adminApi.listProjects).mockResolvedValue({ items: [book], total: 1, limit: 25, offset: 0 })
  vi.mocked(adminApi.listChapters).mockResolvedValue({
    items: [{
      id: 'chapter-1', project_id: 'book-1', chapter_seq: 1, title: '第一章', status: 'done',
      word_count: 2200, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z',
    }], total: 1, limit: 25, offset: 0,
  })
  vi.mocked(adminApi.getProjectContext).mockResolvedValue({
    project_id: 'book-1',
    settings: { data: { genre_pack: '东方奇幻' }, truncated: false, redacted: false, limits },
    outlines: { items: [], total: 0, limit: 25, truncated: false },
    events: { items: [], total: 0, limit: 25, truncated: false },
    facts: { items: [], total: 0, limit: 25, truncated: false },
    characters: { items: [], total: 0, limit: 25, truncated: false },
    foreshadows: { items: [], total: 0, limit: 25, truncated: false },
    threads: { items: [], total: 0, limit: 25, truncated: false },
  })
  vi.mocked(adminApi.getChapter).mockResolvedValue({
    id: 'chapter-1', project_id: 'book-1', chapter_seq: 1, title: '第一章', status: 'done',
    word_count: 2200, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z',
    content: '<script>不能执行</script>正文', summary: '章节摘要', version: 3,
  })
  const { router } = renderPage()
  fireEvent.click(screen.getByRole('button', { name: '作品' }))
  fireEvent.click(await screen.findByRole('button', { name: '查看《山河册》' }))

  // 整页切换：地址变了，表格不在这一页了
  expect(router.state.location.pathname).toBe('/admin/projects/book-1')
  expect(await screen.findByRole('heading', { name: '作品详情' })).toBeTruthy()
  expect((await screen.findByLabelText('作品设置')).textContent).toContain('东方奇幻')
  fireEvent.click(await screen.findByRole('button', { name: '查看第一章全文' }))
  expect(await screen.findByText('<script>不能执行</script>正文')).toBeTruthy()
  expect(screen.getByText('章节摘要')).toBeTruthy()
  expect(document.querySelector('script')).toBeNull()

  fireEvent.click(screen.getByRole('link', { name: '返回' }))
  expect(router.state.location.pathname + router.state.location.search).toBe('/admin?tab=projects')
})

it('opens a book detail page straight from its url and still fetches that one book', async () => {
  vi.mocked(adminApi.listChapters).mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 })
  vi.mocked(adminApi.getProjectContext).mockResolvedValue({
    project_id: 'book-1',
    settings: { data: {}, truncated: false, redacted: false, limits },
    outlines: { items: [], total: 0, limit: 25, truncated: false },
    events: { items: [], total: 0, limit: 25, truncated: false },
    facts: { items: [], total: 0, limit: 25, truncated: false },
    characters: { items: [], total: 0, limit: 25, truncated: false },
    foreshadows: { items: [], total: 0, limit: 25, truncated: false },
    threads: { items: [], total: 0, limit: 25, truncated: false },
  })
  renderPage('/admin/projects/book-1')

  expect(await screen.findByRole('heading', { name: '《山河册》' })).toBeTruthy()
  expect(adminApi.getProject).toHaveBeenCalledWith('token-admin', 'book-1', expect.any(AbortSignal))
  expect(adminApi.listProjects).not.toHaveBeenCalled()
})

it('leaves the console for a task detail page, keeping the node drilldown inline', async () => {
  const task = {
    id: 'task-1', project_id: 'book-1', user_id: 'user-1', username: 'alice', project_title: '山河册',
    task_type: 'chapter_generate', status: 'failed', chapter_seq: 1, batch_task_id: null, retry_count: 1,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:01:00Z', metrics,
  }
  const capture = (data: unknown, truncated = false, redacted = false) => ({
    data, truncated, redacted, limits,
  })
  vi.mocked(adminApi.listTasks).mockResolvedValue({ items: [task], total: 1, limit: 25, offset: 0 })
  vi.mocked(adminApi.getTask).mockResolvedValue({
    ...task,
    payload: capture({ chapter: 1 }), error: capture('模型超时'),
    elapsed_ms: 60000, elapsed_includes_waits: true,
  })
  vi.mocked(adminApi.listTaskRuns).mockResolvedValue({
    items: [{
      id: 11, project_id: 'book-1', user_id: 'user-1', username: 'alice', project_title: '山河册',
      task_id: 'task-1', node: 'draft', role: 'writer', model_id: 'model-a', input_tokens: 12,
      output_tokens: 24, cost_est: 0.1, duration_ms: 0, cache_hit: false, degraded: true,
      retry_count: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:01Z',
    }], total: 1, limit: 25, offset: 0,
  })
  vi.mocked(adminApi.getRun).mockResolvedValue({
    id: 11, project_id: 'book-1', user_id: 'user-1', username: 'alice', project_title: '山河册',
    task_id: 'task-1', node: 'draft', role: 'writer', model_id: 'model-a', input_tokens: 12,
    output_tokens: 24, cost_est: 0.1, duration_ms: 0, cache_hit: false, degraded: true,
    retry_count: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:01Z',
    detail: capture(null), error: capture('旧错误', true, true),
    detail_missing: true, prompt_missing: true,
  })
  const { router } = renderPage()
  fireEvent.click(screen.getByRole('button', { name: '任务' }))
  fireEvent.click(await screen.findByRole('button', { name: '查看任务 task-1' }))

  expect(router.state.location.pathname).toBe('/admin/tasks/task-1')
  expect(await screen.findByText('模型超时')).toBeTruthy()
  // 章内下钻与任务→运行下钻仍然是页内展开，不另开路由
  fireEvent.click(await screen.findByRole('button', { name: '查看节点 draft #11' }))
  expect(await screen.findByText('旧记录未保存详情，无法重建。')).toBeTruthy()
  expect(router.state.location.pathname).toBe('/admin/tasks/task-1')
  expect(screen.getByText('旧记录未保存提示词，无法重建。')).toBeTruthy()
  expect(screen.getByText('内容已截断')).toBeTruthy()
  expect(screen.getByText('敏感信息已脱敏')).toBeTruthy()

  fireEvent.click(screen.getByRole('link', { name: '返回' }))
  expect(router.state.location.pathname + router.state.location.search).toBe('/admin?tab=tasks')
})

it('shows the task status fetched by id, not a stale list snapshot', async () => {
  const task = {
    id: 'task-refresh', project_id: 'book-1', user_id: 'user-1', username: 'alice', project_title: '山河册',
    task_type: 'chapter_generate', status: 'queued', chapter_seq: 1, batch_task_id: null, retry_count: 0,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', metrics,
  }
  const capture = { data: null, truncated: false, redacted: false, limits }
  vi.mocked(adminApi.listTaskRuns).mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 })
  vi.mocked(adminApi.getTask)
    .mockResolvedValueOnce({ ...task, payload: capture, error: capture, elapsed_ms: 0, elapsed_includes_waits: true })
    .mockResolvedValueOnce({
      ...task, status: 'done', updated_at: '2026-01-01T00:01:00Z',
      payload: capture, error: capture, elapsed_ms: 60000, elapsed_includes_waits: true,
    })
  renderPage('/admin/tasks/task-refresh')

  const heading = await screen.findByRole('heading', { name: '山河册 · 单章生成' })
  const detailSection = heading.closest('section')
  expect(detailSection).not.toBeNull()
  expect(await screen.findByText('alice · 第 1 章 · 排队中')).toBeTruthy()

  fireEvent.click(within(detailSection as HTMLElement).getByRole('button', { name: '刷新当前视图' }))

  expect(await screen.findByText('alice · 第 1 章 · 完成')).toBeTruthy()
})

it('opens a run detail page from the runs table and from its url', async () => {
  vi.mocked(adminApi.listRuns).mockResolvedValue({
    items: [{
      id: 20, project_id: 'book-1', user_id: 'user-1', username: 'alice', project_title: '山河册',
      task_id: null, node: 'book_setup', role: null, model_id: 'model-a', input_tokens: 10,
      output_tokens: 20, cost_est: 0.03, duration_ms: 1200, cache_hit: false, degraded: false,
      retry_count: 0, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:01Z',
    }], total: 1, limit: 25, offset: 0,
  })
  vi.mocked(adminApi.getRun).mockResolvedValue({
    id: 20, project_id: 'book-1', user_id: 'user-1', username: 'alice', project_title: '山河册',
    task_id: null, node: 'book_setup', role: null, model_id: 'model-a', input_tokens: 10,
    output_tokens: 20, cost_est: 0.03, duration_ms: 1200, cache_hit: false, degraded: false,
    retry_count: 0, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:01Z',
    detail: { data: { turn: 3 }, truncated: false, redacted: false, limits },
    error: { data: null, truncated: false, redacted: false, limits },
    detail_missing: false, prompt_missing: true,
  })
  const { router } = renderPage('/admin/runs/20')

  expect(await screen.findByRole('heading', { name: '运行详情' })).toBeTruthy()
  expect(await screen.findByText('旧记录未保存提示词，无法重建。')).toBeTruthy()
  expect(adminApi.getRun).toHaveBeenCalledWith('token-admin', 20, expect.any(AbortSignal))

  fireEvent.click(screen.getByRole('link', { name: '返回' }))
  expect(router.state.location.pathname + router.state.location.search).toBe('/admin?tab=runs')
})

it('keeps taskless setup runs discoverable and loads access logs', async () => {
  vi.mocked(adminApi.listRuns).mockResolvedValue({
    items: [{
      id: 20, project_id: 'book-1', user_id: 'user-1', username: 'alice', project_title: '山河册',
      task_id: null, node: 'book_setup', role: null, model_id: 'model-a', input_tokens: 10,
      output_tokens: 20, cost_est: 0.03, duration_ms: 1200, cache_hit: false, degraded: false,
      retry_count: 0, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:01Z',
    }], total: 1, limit: 25, offset: 0,
  })
  vi.mocked(adminApi.listAccessLogs).mockResolvedValue({
    items: [{ id: 2, actor_id: 'admin-1', action: 'admin.overview', target: 'collection', created_at: '2026-01-01T00:00:00Z' }],
    total: 1, limit: 25, offset: 0,
  })
  renderPage()
  fireEvent.click(screen.getByRole('button', { name: '全部运行' }))
  expect(await screen.findByText('#20')).toBeTruthy()
  expect(screen.getByText('0.0300')).toBeTruthy()
  expect(screen.getByRole('button', { name: '查看节点 book_setup #20' })).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '访问日志' }))
  expect(await screen.findByText('admin.overview')).toBeTruthy()
  expect(screen.getByText('collection')).toBeTruthy()
})
