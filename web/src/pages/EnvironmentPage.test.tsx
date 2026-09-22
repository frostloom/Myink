// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
    testRankings: vi.fn(),
  },
}))

const emptyEnv = {
  model_routes: {},
  model_connections: [],
  thinking_enabled: false,
  rankings: {
    enabled: true, mcp_url: 'https://daosearch.io/api/mcp',
    timeout: 10, limit: 10, source: 'qidian', tool: '',
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

it('keeps the draft and presents failed saves in the notification region', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue({ ...emptyEnv, model_connections: [{
    id: 'test', name: '连接 A', protocol: 'openai', base_url: 'https://example.test/v1',
    model: 'writer', has_api_key: true,
  }] })
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateEnvironment).mockRejectedValue({ status: 500, code: '保存失败', body: null })
  renderPage()
  const name = await screen.findByLabelText('连接名称')
  fireEvent.change(name, { target: { value: '新名称' } })
  fireEvent.click(screen.getByRole('button', { name: '保存连接与路由' }))
  const notice = await screen.findByRole('alert')
  expect(notice.textContent).toContain('保存失败')
  expect(screen.getByRole('region', { name: '模型连接通知' }).contains(notice)).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '关闭通知' }))
  expect((name as HTMLInputElement).value).toBe('新名称')
  expect(api.updateEnvironment).toHaveBeenCalledTimes(1)
})

it.each(['models', 'test'] as const)('reports %s failures visibly without resubmitting on close', async (operation) => {
  vi.mocked(api.getEnvironment).mockResolvedValue({ ...emptyEnv, model_connections: [{
    id: 'test', name: '连接 A', protocol: 'openai', base_url: 'https://example.test/v1',
    model: 'writer', has_api_key: true,
  }] })
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.listModels).mockResolvedValue({ ok: false, models: [], error: '服务拒绝' })
  vi.mocked(api.testConnection).mockRejectedValue({ status: 500, code: '服务拒绝', body: null })
  renderPage()
  await screen.findByDisplayValue('连接 A')
  const button = screen.getByRole('button', { name: operation === 'models' ? '获取模型列表' : '测试连接' })
  fireEvent.click(button)
  const notice = await screen.findByRole('alert')
  expect(notice.textContent).toContain('服务拒绝')
  expect(within(screen.getByRole('region', { name: '模型连接通知' })).getByRole('alert')).toBe(notice)
  fireEvent.click(screen.getByRole('button', { name: '关闭通知' }))
  expect(screen.queryByRole('alert')).toBeNull()
  expect(operation === 'models' ? api.listModels : api.testConnection).toHaveBeenCalledTimes(1)
})

it('adds a network model and routes Writer through it without exposing saved keys', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue(emptyEnv)
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateEnvironment).mockResolvedValue(emptyEnv)
  vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('11111111-1111-4111-8111-111111111111')

  renderPage()
  await screen.findByText(/尚未添加网络模型/)
  fireEvent.click(screen.getByRole('button', { name: '添加网络模型' }))
  fireEvent.change(screen.getByLabelText('连接名称'), { target: { value: '我的 GPT' } })
  fireEvent.change(screen.getByLabelText('请求地址'), { target: { value: 'https://models.example.com/v1' } })
  fireEvent.change(screen.getByLabelText('模型 id'), { target: { value: 'novel-pro' } })
  fireEvent.change(screen.getByLabelText(/API Key/), { target: { value: 'secret-key' } })
  fireEvent.change(screen.getByLabelText('写作（writer）'), {
    target: { value: 'custom:11111111-1111-4111-8111-111111111111' },
  })
  fireEvent.click(screen.getByRole('button', { name: '保存连接与路由' }))

  await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalledWith({
    model_routes: { writer: 'custom:11111111-1111-4111-8111-111111111111' },
    model_connections: [{
      id: '11111111-1111-4111-8111-111111111111', name: '我的 GPT', protocol: 'openai',
      base_url: 'https://models.example.com/v1', model: 'novel-pro', api_key: 'secret-key',
    }],
    thinking_enabled: false,
  }))
})

it('focuses and describes the missing field without saving', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue(emptyEnv)
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('33333333-3333-4333-8333-333333333333')

  renderPage()
  await screen.findByText(/尚未添加网络模型/)
  fireEvent.click(screen.getByRole('button', { name: '添加网络模型' }))
  fireEvent.change(screen.getByLabelText('请求地址'), { target: { value: 'https://models.example.com/v1' } })
  fireEvent.change(screen.getByLabelText('模型 id'), { target: { value: 'novel-pro' } })
  fireEvent.change(screen.getByLabelText(/API Key/), { target: { value: 'secret-key' } })
  fireEvent.click(screen.getByRole('button', { name: '保存连接与路由' }))

  const field = screen.getByLabelText('连接名称')
  expect(document.activeElement).toBe(field)
  expect(field.getAttribute('aria-invalid')).toBe('true')
  expect(document.getElementById(field.getAttribute('aria-describedby') ?? '')?.textContent).toContain('连接名称')
  expect(field.scrollIntoView).toHaveBeenCalled()
  expect(api.updateEnvironment).not.toHaveBeenCalled()
})

it('fetches the model list into the datalist and tests connectivity', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue(emptyEnv)
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.listModels).mockResolvedValue({ ok: true, models: ['novel-pro', 'novel-mini'], error: null })
  vi.mocked(api.testConnection).mockResolvedValue({ ok: true, latency_ms: 88, reply: 'pong', error: null })
  vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('22222222-2222-4222-8222-222222222222')

  renderPage()
  await screen.findByText(/尚未添加网络模型/)
  fireEvent.click(screen.getByRole('button', { name: '添加网络模型' }))
  fireEvent.change(screen.getByLabelText('请求地址'), { target: { value: 'https://models.example.com/v1' } })
  fireEvent.change(screen.getByLabelText('模型 id'), { target: { value: 'novel-pro' } })
  fireEvent.change(screen.getByLabelText(/API Key/), { target: { value: 'secret-key' } })

  fireEvent.click(screen.getByRole('button', { name: '获取模型列表' }))
  await waitFor(() => expect(api.listModels).toHaveBeenCalledWith({
    protocol: 'openai', base_url: 'https://models.example.com/v1', model: 'novel-pro', api_key: 'secret-key',
  }))
  await within(screen.getByRole('main')).findByText(/已获取 2 个模型/)
  const options = Array.from(document.querySelectorAll('datalist option'))
    .map((option) => option.getAttribute('value'))
  expect(options).toEqual(['novel-pro', 'novel-mini'])

  fireEvent.click(screen.getByRole('button', { name: '测试连接' }))
  await waitFor(() => expect(api.testConnection).toHaveBeenCalled())
  await within(screen.getByRole('main')).findByText(/连接正常 · 88 ms/)
})

it('does not offer built-in DeepSeek models in the role dropdowns', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue(emptyEnv)
  vi.mocked(api.listProjects).mockResolvedValue([])

  renderPage()
  const writer = await screen.findByLabelText('写作（writer）')
  const labels = Array.from(writer.querySelectorAll('option')).map((option) => option.textContent)
  expect(labels).toEqual(['未指定'])
  expect(screen.getByLabelText('审核（audit）')).toBeTruthy()
  expect(screen.getByLabelText('摘要（summarize）')).toBeTruthy()
  expect(screen.getByLabelText('思考模式')).toBeTruthy()
  expect(screen.queryByText(/deepseek/i)).toBeNull()
  expect(screen.queryByRole('button', { name: '填入 DeepSeek 官方地址' })).toBeNull()
})

it('saves rankings config and tests MCP connectivity', async () => {
  vi.mocked(api.getEnvironment).mockResolvedValue(emptyEnv)
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateEnvironment).mockResolvedValue(emptyEnv)
  vi.mocked(api.testRankings).mockResolvedValue({ ok: true, tools: ['qidian_rank', 'community_rank'], error: null })

  renderPage()
  await screen.findByLabelText('MCP 地址')
  fireEvent.change(screen.getByLabelText('MCP 地址'), { target: { value: 'https://mcp.example.com/api' } })
  fireEvent.change(screen.getByLabelText('扫榜超时'), { target: { value: '8' } })
  fireEvent.click(screen.getByRole('button', { name: '测试扫榜连接' }))
  await waitFor(() => expect(api.testRankings).toHaveBeenCalledWith({
    mcp_url: 'https://mcp.example.com/api', timeout: 8,
  }))
  await screen.findByText(/连接正常 · 发现 2 个工具/)

  fireEvent.click(screen.getByRole('button', { name: '保存扫榜配置' }))
  await waitFor(() => expect(api.updateEnvironment).toHaveBeenCalledWith({
    rankings: {
      enabled: true, mcp_url: 'https://mcp.example.com/api',
      timeout: 8, limit: 10, source: 'qidian', tool: '',
    },
  }))
})
