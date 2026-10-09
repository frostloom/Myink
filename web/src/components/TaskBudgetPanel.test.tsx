// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { TaskBudgetPanel } from './TaskBudgetPanel'
import { api } from '../lib/api'
vi.mock('../lib/api', () => ({ api: { resumeTask: vi.fn() } }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const budget = { limits: { max_requests: 1, max_cost_yuan: 5, max_runtime_seconds: 1800 }, requests_used: 1, cost_used_yuan: 0.1, cost_reserved_yuan: 0.2, runtime_used_seconds: 10, pause_reason: 'request_limit', stage: 'audit', version: 1, resume_publication: null }
it('retains the operation id on retry and prevents duplicate clicks', async () => {
  vi.mocked(api.resumeTask).mockRejectedValueOnce(new Error('网络失败')).mockResolvedValueOnce({ task_id: 't', status: 'queued' })
  const resumed = vi.fn()
  render(<TaskBudgetPanel task={{ task_id: 't', status: 'paused', budget }} onResumed={resumed} />)
  fireEvent.change(screen.getByLabelText('追加请求次数'), { target: { value: '2' } })
  fireEvent.click(screen.getByRole('button', { name: '追加并继续' }))
  await screen.findByRole('alert')
  const first = vi.mocked(api.resumeTask).mock.calls[0][1]
  fireEvent.click(screen.getByRole('button', { name: '重试本次恢复' }))
  await waitFor(() => expect(resumed).toHaveBeenCalledTimes(2))
  expect(vi.mocked(api.resumeTask).mock.calls[1][1]).toEqual(first)
  expect(first).toMatchObject({ add_requests: 2 })
})
it('shows unlimited dimensions and separates manual pause', () => {
  render(<TaskBudgetPanel task={{ task_id: 't', status: 'paused', budget: { ...budget, pause_reason: null, limits: { max_requests: 0, max_cost_yuan: 0, max_runtime_seconds: 0 } } }} onResumed={vi.fn()} />)
  expect(screen.getByText(/不限/)).toBeTruthy()
  expect(screen.queryByRole('button', { name: '追加并继续' })).toBeNull()
})
