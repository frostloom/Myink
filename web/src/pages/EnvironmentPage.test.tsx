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
  fireEvent.change(await screen.findByLabelText('扫榜超时'), { target: { value: '8' } })
  fireEvent.click(screen.getByRole('button', { name: '保存扫榜配置' }))
  await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalledWith({
    rankings: { enabled: true, timeout: 8, limit: 10 },
  }))
})

it('has no MCP address input or probe button left in the rankings section', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue(emptyEnv)
  vi.mocked(api.listProjects).mockResolvedValue([])

  renderPage()
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
  const requests = await screen.findByLabelText('任务请求上限')
  fireEvent.change(requests, { target: { value: '120' } })
  fireEvent.click(screen.getByRole('button', { name: '保存任务预算' }))
  await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalledWith({ task_budget: {
    max_requests: 120, max_cost_yuan: 5, max_runtime_seconds: 1800,
  } }))
})

 it('offers only published models and saves user selections without connection credentials', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue({ ...emptyEnv, available_models: [{id:'custom:published',name:'公开写作模型'}] } as never)
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateEnvironment).mockResolvedValue(emptyEnv)
  renderPage()
  await screen.findAllByRole('option', { name: '公开写作模型' })
  expect(screen.queryByRole('button', {name:'添加网络模型'})).toBeNull()
  expect(screen.queryByLabelText('请求地址')).toBeNull()
  fireEvent.change(screen.getByLabelText('写作（writer）'), { target: { value: 'custom:published' } })
  fireEvent.click(screen.getByRole('button', { name: '保存模型偏好' }))
  await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalledWith({ model_routes: {writer:'custom:published'}, thinking_enabled:false }))
})
