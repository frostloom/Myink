// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../lib/api'
import { adminApi, type AdminUser } from '../../lib/adminApi'
import { UserDetailPage } from './UserDetail'

vi.mock('../../lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/adminApi')>()
  return {
    ...actual,
    adminApi: { ...actual.adminApi, getUser: vi.fn(), listRuns: vi.fn() },
  }
})

const alice: AdminUser = {
  id: 'user-1', username: 'alice', tier: 'normal', role: 'user',
  project_count: 1, chapter_count: 2, word_count: 300, task_count: 0,
  metrics: { run_count: 0, input_tokens: 0, output_tokens: 0, cost_est: 0, duration_ms: 0 },
  task_averages: { avg_cost_per_task: null, avg_duration_ms_per_task: null, avg_runs_per_task: null },
}

// 详情页是 /admin 下的子路由，闸门与 token 在父路由上——测试按同一棵树挂载。
function Shell() {
  return <Outlet context={{ token: 'token-admin', onForbidden: vi.fn() }} />
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/admin/users/user-1']}>
      <Routes>
        <Route path="/admin" element={<Shell />}>
          <Route path="users/:userId" element={<UserDetailPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('loads one account from the single-user endpoint, not from a search query', async () => {
  vi.mocked(adminApi.getUser).mockResolvedValue(alice)
  vi.mocked(adminApi.listRuns).mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 })
  renderDetail()
  expect(await screen.findByRole('heading', { name: /alice/ })).toBeTruthy()
  expect(adminApi.getUser).toHaveBeenCalledWith('token-admin', 'user-1', expect.any(AbortSignal))
})

it('tells the reader a missing user does not exist instead of echoing the 404 code', async () => {
  vi.mocked(adminApi.getUser).mockRejectedValue(new ApiError(404, 'NOT_FOUND', {}))
  vi.mocked(adminApi.listRuns).mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 })
  renderDetail()
  expect(await screen.findByText('用户不存在')).toBeTruthy()
})
