// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import PlatformConfiguration from './PlatformConfiguration'
import { platformApi } from '../../lib/platformApi'
vi.mock('../../lib/api', () => ({ api: { listGenrePacks: vi.fn().mockResolvedValue([]) } }))
vi.mock('../../lib/platformApi', () => ({
  platformApi: {
    getConfiguration: vi.fn(),
    getPromptTemplates: vi.fn(),
    updateConfiguration: vi.fn(),
    getReadiness: vi.fn(),
    listModels: vi.fn(),
    testConnection: vi.fn(),
  },
}))
const saved = {
  version: 4,
  model_connections: [
    {
      id: 'one',
      name: '我的模型',
      protocol: 'openai' as const,
      base_url: 'https://example.com/v1',
      model: 'writer-pro',
      has_api_key: true,
      enabled: true,
      user_visible: true,
    },
  ],
  model_routes: { writer: 'custom:one' },
  prompts: { writer: '保留提示词' },
  genre_packs: {},
}
function page(section = 'models') {
  render(
    <MemoryRouter>
      <Routes>
        <Route element={<Outlet context={{ onForbidden: vi.fn() }} />}>
          <Route path="/" element={<PlatformConfiguration section={section as 'models' | 'prompts'} />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}
beforeEach(() => {
  vi.mocked(platformApi.getPromptTemplates).mockResolvedValue([
    {
      role: 'writer',
      templates: [
        {
          id: 'system_write',
          title: '长篇正文写作',
          content: '真实系统模板正文',
          source: 'src/myink/workflow/prompts.py:SYSTEM_WRITE',
        },
      ],
    },
  ])
  vi.mocked(platformApi.getConfiguration).mockResolvedValue(saved)
  vi.mocked(platformApi.getReadiness).mockResolvedValue({ ready: true, checks: [] })
  vi.mocked(platformApi.updateConfiguration).mockResolvedValue({ ...saved, version: 5 })
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})
it('shows a model list and opens a single editor; cancel never saves or probes', async () => {
  page()
  await screen.findByRole('heading', { name: 'AI 模型' })
  expect(screen.queryByLabelText('请求地址')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '新增模型' }))
  expect(screen.getByRole('dialog', { name: '新增模型' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '取消' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(platformApi.updateConfiguration).not.toHaveBeenCalled()
  expect(platformApi.testConnection).not.toHaveBeenCalled()
  expect(platformApi.listModels).not.toHaveBeenCalled()
})
it('edits one model without resending its key or changing other platform settings', async () => {
  page()
  fireEvent.click(await screen.findByRole('button', { name: '编辑 我的模型' }))
  fireEvent.change(screen.getByLabelText('显示名称'), { target: { value: '新名称' } })
  fireEvent.click(screen.getByRole('button', { name: '保存模型' }))
  await waitFor(() => expect(platformApi.updateConfiguration).toHaveBeenCalled())
  const body = vi.mocked(platformApi.updateConfiguration).mock.calls[0][0]
  expect(body.version).toBe(4)
  expect(body.prompts).toEqual(saved.prompts)
  expect(body.model_routes).toEqual(saved.model_routes)
  expect(body.model_connections[0].name).toBe('新名称')
  expect(body.model_connections[0]).not.toHaveProperty('api_key')
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})
it('keeps the editor draft on a version conflict', async () => {
  vi.mocked(platformApi.updateConfiguration).mockRejectedValue({ status: 409 })
  page()
  fireEvent.click(await screen.findByRole('button', { name: '编辑 我的模型' }))
  fireEvent.change(screen.getByLabelText('显示名称'), { target: { value: '草稿名称' } })
  fireEvent.click(screen.getByRole('button', { name: '保存模型' }))
  await screen.findByRole('alert')
  expect((screen.getByLabelText('显示名称') as HTMLInputElement).value).toBe('草稿名称')
})
it('requires confirmation before deleting a model and clears its role references', async () => {
  page()
  fireEvent.click(await screen.findByRole('button', { name: '删除 我的模型' }))
  expect(platformApi.updateConfiguration).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
  await waitFor(() => expect(platformApi.updateConfiguration).toHaveBeenCalled())
  const body = vi.mocked(platformApi.updateConfiguration).mock.calls[0][0]
  expect(body.model_connections).toEqual([])
  expect(body.model_routes).toEqual({})
  expect(body.prompts).toEqual(saved.prompts)
})

it('creates a model from the service preset and keeps existing resources intact', async () => {
  page()
  fireEvent.click(await screen.findByRole('button', { name: '新增模型' }))
  fireEvent.change(screen.getByLabelText('显示名称'), { target: { value: '我的 DeepSeek' } })
  fireEvent.change(screen.getByLabelText('模型服务商'), { target: { value: 'deepseek' } })
  expect((screen.getByLabelText('请求地址') as HTMLInputElement).value).toBe('https://api.deepseek.com/v1')
  fireEvent.change(screen.getByLabelText('模型 ID'), { target: { value: 'deepseek-chat' } })
  fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'test-only-key' } })
  fireEvent.click(screen.getByRole('button', { name: '保存模型' }))
  await waitFor(() => expect(platformApi.updateConfiguration).toHaveBeenCalled())
  const body = vi.mocked(platformApi.updateConfiguration).mock.calls[0][0]
  expect(body.model_connections).toHaveLength(2)
  expect(body.model_connections[1]).toMatchObject({
    name: '我的 DeepSeek',
    protocol: 'openai',
    base_url: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    api_key: 'test-only-key',
  })
  expect(body.model_connections[0]).not.toHaveProperty('api_key')
  expect(body.prompts).toEqual(saved.prompts)
})
it('actively retrieves model choices using saved credentials without revealing them', async () => {
  vi.mocked(platformApi.listModels).mockResolvedValue({
    ok: true,
    models: ['model-alpha', 'model-beta'],
    error: null,
  })
  page()
  fireEvent.click(await screen.findByRole('button', { name: '编辑 我的模型' }))
  fireEvent.click(screen.getByRole('button', { name: '获取模型列表' }))
  fireEvent.click(await screen.findByRole('button', { name: 'model-beta' }))
  expect((screen.getByLabelText('模型 ID') as HTMLInputElement).value).toBe('model-beta')
  expect(platformApi.listModels).toHaveBeenCalledWith({
    protocol: 'openai',
    base_url: 'https://example.com/v1',
    model: 'writer-pro',
    connection_id: 'one',
  })
  expect(platformApi.updateConfiguration).not.toHaveBeenCalled()
})
it('renders only the selected settings section', async () => {
  page('prompts')
  await screen.findByRole('heading', { name: '提示词' })
  expect(screen.getByRole('button', { name: '编辑 写作提示词' })).toBeTruthy()
  expect(screen.queryByLabelText('默认思考模式')).toBeNull()
  expect(screen.queryByRole('region', { name: '平台就绪状态' })).toBeNull()
  expect(screen.queryByRole('button', { name: '添加网络模型' })).toBeNull()
})

it('assigns the first enabled model as the required writer default', async () => {
  vi.mocked(platformApi.getConfiguration).mockResolvedValue({
    ...saved,
    model_connections: [],
    model_routes: {},
  })
  page()
  fireEvent.click(await screen.findByRole('button', { name: '新增模型' }))
  fireEvent.change(screen.getByLabelText('显示名称'), { target: { value: '第一个模型' } })
  fireEvent.change(screen.getByLabelText('模型 ID'), { target: { value: 'writer-first' } })
  fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'test-key' } })
  fireEvent.click(screen.getByRole('button', { name: '保存模型' }))
  await waitFor(() => expect(platformApi.updateConfiguration).toHaveBeenCalled())
  const body = vi.mocked(platformApi.updateConfiguration).mock.calls[0][0]
  expect(body.model_routes.writer).toBe(`custom:${body.model_connections[0].id}`)
})
it('does not disable a model that is still assigned to a platform role', async () => {
  page()
  fireEvent.click(await screen.findByRole('button', { name: '编辑 我的模型' }))
  fireEvent.click(screen.getByLabelText('启用模型'))
  fireEvent.click(screen.getByRole('button', { name: '保存模型' }))
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('模型分配'))
  expect(platformApi.updateConfiguration).not.toHaveBeenCalled()
})
it('requires an explicit replacement when deleting a writer default with other models remaining', async () => {
  vi.mocked(platformApi.getConfiguration).mockResolvedValue({
    ...saved,
    model_connections: [
      ...saved.model_connections,
      { ...saved.model_connections[0], id: 'two', name: '备用模型' },
    ],
  })
  page()
  fireEvent.click(await screen.findByRole('button', { name: '删除 我的模型' }))
  fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
  expect(platformApi.updateConfiguration).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('替代写作模型'), { target: { value: 'custom:two' } })
  fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
  await waitFor(() => expect(platformApi.updateConfiguration).toHaveBeenCalled())
  expect(vi.mocked(platformApi.updateConfiguration).mock.calls[0][0].model_routes.writer).toBe('custom:two')
})

it.each(['models', 'test'] as const)('keeps actionable %s probe diagnostics visible', async (operation) => {
  vi.mocked(platformApi.listModels).mockResolvedValue({
    ok: false,
    models: [],
    error: '服务商不支持模型列表',
  })
  vi.mocked(platformApi.testConnection).mockResolvedValue({
    ok: false,
    error: '模型不存在，请检查模型 ID',
    latency_ms: 0,
    reply: null,
  })
  page()
  fireEvent.click(await screen.findByRole('button', { name: '编辑 我的模型' }))
  fireEvent.click(screen.getByRole('button', { name: operation === 'models' ? '获取模型列表' : '测试连接' }))
  expect((await screen.findByRole('alert')).textContent).toContain(
    operation === 'models' ? '服务商不支持模型列表' : '模型不存在，请检查模型 ID',
  )
})

it('shows the deployed built-in model as an editable model and assignment option', async () => {
  vi.mocked(platformApi.getConfiguration).mockResolvedValue({
    ...saved,
    model_connections: [{ ...saved.model_connections[0], name: '平台内置模型', origin: 'builtin' as const, model: 'deepseek-v4.1-flash' }],
  })
  page()
  expect(await screen.findByText('平台内置')).toBeTruthy()
  expect(screen.getByText('deepseek-v4.1-flash')).toBeTruthy()
  expect(screen.getByRole('link', { name: '调整模型分配' }).getAttribute('href')).toBe('/admin/model-routes')
  fireEvent.click(screen.getByRole('button', { name: '编辑 平台内置模型' }))
  expect((screen.getByLabelText('API Key') as HTMLInputElement).value).toBe('')
})

it('assigns the built-in model to backend roles without copying credentials', async () => {
  vi.mocked(platformApi.getConfiguration).mockResolvedValue({
    ...saved,
    model_connections: [{ ...saved.model_connections[0], name: '平台内置模型', origin: 'builtin' as const, model: 'deepseek-v4.1-flash' }],
  })
  page('routes')
  const role = await screen.findByLabelText('审核')
  fireEvent.change(role, { target: { value: 'custom:one' } })
  fireEvent.click(screen.getByRole('button', { name: '保存平台配置' }))
  await waitFor(() => expect(platformApi.updateConfiguration).toHaveBeenCalled())
  const body = vi.mocked(platformApi.updateConfiguration).mock.calls[0][0]
  expect(body.model_routes.audit).toBe('custom:one')
  expect(body.model_routes.writer).toBe('custom:one')
  expect(body.model_connections[0]).not.toHaveProperty('api_key')
  expect(body.model_connections[0]).not.toHaveProperty('origin')
})
