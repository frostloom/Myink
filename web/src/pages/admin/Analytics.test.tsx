// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import {
  adminApi,
  type AdminGenerationTask,
  type AdminMetrics,
  type AdminProject,
  type AdminTaskAverages,
  type AdminTaskChapter,
  type AdminUser,
} from '../../lib/adminApi'
import { Analytics } from './Analytics'

vi.mock('../../lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/adminApi')>()
  return {
    ...actual,
    adminApi: {
      ...actual.adminApi,
      listUsers: vi.fn(),
      listProjects: vi.fn(),
      listGenerationTasks: vi.fn(),
      listTaskChapters: vi.fn(),
      listFindings: vi.fn(),
    },
  }
})

const metrics: AdminMetrics = {
  run_count: 12, input_tokens: 3000, output_tokens: 4000, cost_est: 1.85, duration_ms: 1850,
}

const averages: AdminTaskAverages = {
  avg_cost_per_task: 0.21, avg_duration_ms_per_task: 1250, avg_runs_per_task: 2,
}
const noTasks: AdminTaskAverages = {
  avg_cost_per_task: null, avg_duration_ms_per_task: null, avg_runs_per_task: null,
}

const user: AdminUser = {
  id: 'user-1', username: 'alice', tier: 'normal', role: 'user', project_count: 2,
  chapter_count: 7, word_count: 12000, task_count: 3, metrics, task_averages: averages,
}
const idleUser: AdminUser = {
  id: 'user-2', username: 'bob', tier: 'normal', role: 'user', project_count: 1,
  chapter_count: 0, word_count: 0, task_count: 0, metrics: { ...metrics, run_count: 0 },
  task_averages: noTasks,
}

const project: AdminProject = {
  id: 'book-1', user_id: 'user-1', username: 'alice', title: '山河册', genre: '奇幻',
  current_chapter: 4, target_words: 100000, creation_status: 'ready',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z',
  chapter_count: 4, word_count: 4500, task_count: 3, metrics,
  task_averages: { avg_cost_per_task: 0.4, avg_duration_ms_per_task: 900, avg_runs_per_task: 3.5 },
}

const task: AdminGenerationTask = {
  id: 'task-1', task_type: 'batch_generate', status: 'done', chapter_seq: null,
  batch_task_id: null, retry_count: 1, chapter_count: 3, snapshot_count: 2,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:05:00Z', metrics,
}

const chapter: AdminTaskChapter = {
  chapter_seq: 2, stages: ['recall', 'write', 'validate'], metrics,
  snapshots: [{
    id: 31, stage: 'write', attempt: 1, model_id: 'model-a', cost_est: 0.1234,
    duration_ms: 4200, degraded: false, created_at: '2026-01-01T00:00:00Z',
  }],
}

function pageOf<T>(items: T[]) {
  return { items, total: items.length, limit: 25, offset: 0 }
}

function renderAnalytics() {
  return render(<Analytics token="token-admin" onForbidden={vi.fn()} />)
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('shows per-task averages at the user level and says so when a user has no tasks', async () => {
  vi.mocked(adminApi.listUsers).mockResolvedValue(pageOf([user, idleUser]))
  renderAnalytics()

  expect(await screen.findByText('alice')).toBeTruthy()
  expect(screen.getByText(/0\.2100/).textContent).toContain('2.0 次调用/任务')
  expect(screen.getByText('无任务')).toBeTruthy()
})

it('pages and searches the user list through the API, not the local array', async () => {
  vi.mocked(adminApi.listUsers)
    .mockResolvedValueOnce({ ...pageOf([user, idleUser]), total: 26 })
    .mockResolvedValueOnce({ ...pageOf([idleUser]), total: 26 })
    .mockResolvedValueOnce({ ...pageOf([user]), total: 26, offset: 25 })
  renderAnalytics()
  await screen.findByText('alice')

  fireEvent.change(screen.getByLabelText('搜索用户'), { target: { value: ' ali ce ' } })
  fireEvent.submit(screen.getByRole('search', { name: '用户筛选' }))
  await waitFor(() => expect(adminApi.listUsers).toHaveBeenLastCalledWith(
    'token-admin', expect.objectContaining({ q: 'ali ce', offset: 0 }), expect.any(AbortSignal),
  ))
  expect(await screen.findByText('bob')).toBeTruthy()
  expect(screen.queryByText('alice')).toBeNull()

  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  await waitFor(() => expect(adminApi.listUsers).toHaveBeenLastCalledWith(
    'token-admin', expect.objectContaining({ offset: 25 }), expect.any(AbortSignal),
  ))
})

it('drills from a user to their books, tasks, chapters and snapshot refs', async () => {
  vi.mocked(adminApi.listUsers).mockResolvedValue(pageOf([user]))
  vi.mocked(adminApi.listProjects).mockResolvedValue(pageOf([project]))
  vi.mocked(adminApi.listGenerationTasks).mockResolvedValue(pageOf([task]))
  vi.mocked(adminApi.listTaskChapters).mockResolvedValue(pageOf([chapter]))
  vi.mocked(adminApi.listFindings).mockResolvedValue(pageOf([]))
  renderAnalytics()

  fireEvent.click(await screen.findByRole('button', { name: '分析 alice' }))
  await waitFor(() => expect(adminApi.listProjects).toHaveBeenCalledWith(
    'token-admin', expect.objectContaining({ userId: 'user-1' }), expect.any(AbortSignal),
  ))
  const userPanel = (await screen.findByRole('heading', { name: 'alice 的作品' })).closest('section')!
  expect(userPanel.textContent).toContain('0.4000')
  expect(userPanel.textContent).toContain('3.5 次调用/任务')

  fireEvent.click(screen.getByRole('button', { name: '查看《山河册》的分析' }))
  await waitFor(() => expect(adminApi.listGenerationTasks).toHaveBeenCalledWith(
    'token-admin', 'book-1', expect.objectContaining({ offset: 0 }), expect.any(AbortSignal),
  ))
  const bookPanel = (await screen.findByRole('heading', { name: '《山河册》的任务' })).closest('section')!
  expect(bookPanel.textContent).toContain('batch_generate')
  expect(bookPanel.textContent).toContain('1.85')
  expect(await screen.findByText('校验发现')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '查看任务 task-1 的每章分解' }))
  await waitFor(() => expect(adminApi.listTaskChapters).toHaveBeenCalledWith(
    'token-admin', 'task-1', expect.objectContaining({ offset: 0 }), expect.any(AbortSignal),
  ))
  const chapterPanel = (await screen.findByRole('heading', { name: '任务 task-1 的每章分解' })).closest('section')!
  expect(chapterPanel.textContent).toContain('recall / write / validate')
  expect(chapterPanel.textContent).toContain('第 2 章')

  fireEvent.click(screen.getByRole('button', { name: '查看第 2 章的快照' }))
  expect(await screen.findByRole('heading', { name: '第 2 章的快照' })).toBeTruthy()
  expect(screen.getByText('model-a')).toBeTruthy()
  expect(screen.getByRole('button', { name: '查看第 2 章 write 快照' })).toBeTruthy()
})

it('filters findings by severity and chapter and keeps them pageable', async () => {
  vi.mocked(adminApi.listUsers).mockResolvedValue(pageOf([user]))
  vi.mocked(adminApi.listProjects).mockResolvedValue(pageOf([project]))
  vi.mocked(adminApi.listGenerationTasks).mockResolvedValue(pageOf([]))
  vi.mocked(adminApi.listFindings).mockResolvedValue(pageOf([{
    snapshot_id: 31, task_id: 'task-1', chapter_seq: 2, attempt: 1,
    severity: 'major', conflict_type: '设定冲突', scope: '人物',
    source: 'world_facts', suggestion: '把铜镜改成铜铃', evidence: [{ chapter: 2, quote: '铜镜亮了' }],
  }]))
  renderAnalytics()

  fireEvent.click(await screen.findByRole('button', { name: '分析 alice' }))
  fireEvent.click(await screen.findByRole('button', { name: '查看《山河册》的分析' }))
  expect(await screen.findByText(/第 2 章：铜镜亮了/)).toBeTruthy()

  fireEvent.change(screen.getByLabelText('严重度'), { target: { value: 'major' } })
  fireEvent.change(screen.getByLabelText('章号'), { target: { value: '2' } })
  fireEvent.submit(screen.getByRole('form', { name: '发现筛选' }))
  await waitFor(() => expect(adminApi.listFindings).toHaveBeenLastCalledWith(
    'token-admin', 'book-1',
    expect.objectContaining({ severity: 'major', chapterSeq: 2, offset: 0 }),
    expect.any(AbortSignal),
  ))
})

it('clears the drill-down when the user list is re-searched', async () => {
  vi.mocked(adminApi.listUsers).mockResolvedValue(pageOf([user]))
  vi.mocked(adminApi.listProjects).mockResolvedValue(pageOf([project]))
  renderAnalytics()
  fireEvent.click(await screen.findByRole('button', { name: '分析 alice' }))
  await screen.findByRole('heading', { name: 'alice 的作品' })

  fireEvent.submit(screen.getByRole('search', { name: '用户筛选' }))

  await waitFor(() => expect(screen.queryByRole('heading', { name: 'alice 的作品' })).toBeNull())
})
