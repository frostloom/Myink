// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import EnvironmentPage from './EnvironmentPage'
import { api } from '../lib/api'

vi.mock('../components/ProjectRail', () => ({ ProjectRail: () => <nav>项目</nav> }))
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ logout: vi.fn() }) }))
vi.mock('../lib/api', () => ({
  ApiError: class ApiError extends Error { code = 'API_ERROR' },
  api: {
    getEnvironment: vi.fn(), listProjects: vi.fn(),
    updateEnvironment: vi.fn(), listModels: vi.fn(), testConnection: vi.fn(),
  },
}))

const emptyEnv = {
  model_routes: {},
  model_connections: [],
  thinking_enabled: false,
  rankings: {
    enabled: true,
    timeout: 10, limit: 10,
  },
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

async function expandAdvanced() {
  const button = await screen.findByRole('button', { name: '展开高级设置' })
  fireEvent.click(button)
  await waitFor(() => expect((screen.getByLabelText('思考模式') as HTMLSelectElement).disabled).toBe(false))
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/environment']}>
      <Routes><Route path="/environment" element={<EnvironmentPage />} /></Routes>
    </MemoryRouter>,
  )
}

it('saves the rankings config without any MCP field', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue(emptyEnv)
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateEnvironment).mockResolvedValue(emptyEnv)

  renderPage()
  await expandAdvanced()
  fireEvent.change(await screen.findByLabelText('扫榜超时'), { target: { value: '8' } })
  fireEvent.click(screen.getByRole('button', { name: '保存扫榜配置' }))
  await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalledWith({
    rankings: { timeout: 8 },
  }))
})

it('has no MCP address input or probe button left in the rankings section', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue(emptyEnv)
  vi.mocked(api.listProjects).mockResolvedValue([])

  renderPage()
  await expandAdvanced()
  await screen.findByLabelText('扫榜超时')
  expect(screen.queryByLabelText('MCP 地址')).toBeNull()
  expect(screen.queryByRole('button', { name: '测试 MCP 连接' })).toBeNull()
  expect(screen.queryByText('MCP 服务')).toBeNull()
})
it('saves only the task budget defaults', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue(emptyEnv)
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateEnvironment).mockResolvedValue(emptyEnv)
  renderPage()
  await expandAdvanced()
  const requests = await screen.findByLabelText('任务请求上限')
  fireEvent.change(requests, { target: { value: '120' } })
  fireEvent.click(screen.getByRole('button', { name: '保存任务预算' }))
  await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalledWith({ task_budget: {
    max_requests: 120,
  } }))
})

 it('offers only published models and saves user selections without connection credentials', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue({ ...emptyEnv, available_models: [{id:'custom:published',name:'公开写作模型'}] } as never)
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateEnvironment).mockResolvedValue(emptyEnv)
  renderPage()
  await expandAdvanced()
  await screen.findAllByRole('option', { name: '公开写作模型' })
  expect(screen.queryByRole('button', {name:'添加网络模型'})).toBeNull()
  expect(screen.queryByLabelText('请求地址')).toBeNull()
  fireEvent.change(screen.getByLabelText('写作（writer）'), { target: { value: 'custom:published' } })
  fireEvent.click(screen.getByRole('button', { name: '保存模型偏好' }))
  await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalledWith({ model_routes: {writer:'custom:published'} }))
})


it('hides all advanced controls until explicitly expanded and starts collapsed on reentry', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue(emptyEnv)
  vi.mocked(api.listProjects).mockResolvedValue([])
  const view = renderPage()
  const toggle = await screen.findByRole('button', { name: '展开高级设置' })
  expect(toggle.getAttribute('aria-expanded')).toBe('false')
  for (const label of ['思考模式', '写作（writer）', '任务请求上限', '扫榜超时']) {
    expect(screen.queryByLabelText(label)).toBeNull()
  }
  fireEvent.click(toggle)
  expect(toggle.getAttribute('aria-expanded')).toBe('true')
  expect(await screen.findByLabelText('任务请求上限')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('任务请求上限'), { target: { value: '123' } })
  fireEvent.click(screen.getByRole('button', { name: '收起高级设置' }))
  expect(screen.queryByLabelText('任务请求上限')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '展开高级设置' }))
  expect((screen.getByLabelText('任务请求上限') as HTMLInputElement).value).toBe('123')
  view.unmount()
  renderPage()
  expect(screen.getByRole('button', { name: '展开高级设置' }).getAttribute('aria-expanded')).toBe('false')
})

it('resets only one override and adopts server effective values and metadata', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue({ ...emptyEnv,
    task_budget: { max_requests: 0, max_cost_yuan: 7, max_runtime_seconds: 2000 },
    overridden_fields: ['task_budget.max_requests', 'task_budget.max_cost_yuan'],
  } as never)
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateEnvironment).mockResolvedValue({ ...emptyEnv,
    task_budget: { max_requests: 180, max_cost_yuan: 7, max_runtime_seconds: 2400 },
    thinking_enabled: true, overridden_fields: ['task_budget.max_cost_yuan'],
  } as never)
  renderPage()
  await expandAdvanced()
  fireEvent.click(screen.getByRole('button', { name: '恢复任务请求上限默认值' }))
  await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalledWith({ reset_preferences: ['task_budget.max_requests'] }))
  await waitFor(() => expect((screen.getByLabelText('任务请求上限') as HTMLInputElement).value).toBe('180'))
  expect((screen.getByLabelText('任务费用上限（元）') as HTMLInputElement).value).toBe('7')
  expect((screen.getByLabelText('思考模式') as HTMLSelectElement).value).toBe('1')
  expect((screen.getByRole('button', { name: '恢复任务请求上限默认值' }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: '恢复任务费用上限（元）默认值' }) as HTMLButtonElement).disabled).toBe(false)
})

it('applies successful budget responses instead of freezing untouched inherited leaves', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue({ ...emptyEnv, overridden_fields: [] } as never)
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateEnvironment).mockResolvedValue({ ...emptyEnv,
    task_budget: { max_requests: 0, max_cost_yuan: 9, max_runtime_seconds: 3600 },
    overridden_fields: ['task_budget.max_requests'],
  } as never)
  renderPage()
  await expandAdvanced()
  fireEvent.change(screen.getByLabelText('任务请求上限'), { target: { value: '0' } })
  fireEvent.click(screen.getByRole('button', { name: '保存任务预算' }))
  await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalledWith({ task_budget: { max_requests: 0 } }))
  await waitFor(() => expect((screen.getByLabelText('任务费用上限（元）') as HTMLInputElement).value).toBe('9'))
  expect((screen.getByRole('button', { name: '恢复任务请求上限默认值' }) as HTMLButtonElement).disabled).toBe(false)
})

it('saves explicit false thinking without freezing either model route', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue({ ...emptyEnv, thinking_enabled: true,
    model_routes: { writer: 'custom:published' }, available_models: [{ id: 'custom:published', name: '模型' }],
  })
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateEnvironment).mockResolvedValue(emptyEnv)
  renderPage()
  await expandAdvanced()
  fireEvent.change(screen.getByLabelText('思考模式'), { target: { value: '0' } })
  fireEvent.click(screen.getByRole('button', { name: '保存模型偏好' }))
  await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalledWith({ thinking_enabled: false }))
})

it('keeps draft values after failed save and reset', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue({ ...emptyEnv, overridden_fields: ['rankings.timeout'] } as never)
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateEnvironment).mockRejectedValue({ status: 503, code: '保存失败' })
  renderPage()
  await expandAdvanced()
  fireEvent.change(screen.getByLabelText('扫榜超时'), { target: { value: '8' } })
  fireEvent.click(screen.getByRole('button', { name: '保存扫榜配置' }))
  await screen.findByRole('alert')
  expect((screen.getByLabelText('扫榜超时') as HTMLInputElement).value).toBe('8')
  fireEvent.click(screen.getByRole('button', { name: '恢复扫榜超时默认值' }))
  await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalledTimes(2))
  expect((screen.getByLabelText('扫榜超时') as HTMLInputElement).value).toBe('8')
})

it('disables editing, saving and resetting after a loading failure until retry succeeds', async () => {
  vi.mocked(api.getEnvironment).mockRejectedValueOnce({ status: 503, code: '加载失败' }).mockResolvedValue(emptyEnv)
  vi.mocked(api.listProjects).mockResolvedValue([])
  renderPage()
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: '展开高级设置' }))
  expect((screen.getByLabelText('任务请求上限') as HTMLInputElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: '保存任务预算' }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: '恢复任务请求上限默认值' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '重新加载高级设置' }))
  await waitFor(() => expect((screen.getByLabelText('任务请求上限') as HTMLInputElement).disabled).toBe(false))
})
