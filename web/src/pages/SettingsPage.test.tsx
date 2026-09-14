// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import SettingsPage from './SettingsPage'
import { api } from '../lib/api'

vi.mock('../components/ProjectRail', () => ({ ProjectRail: () => <nav>项目</nav> }))
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ logout: vi.fn() }) }))
vi.mock('../lib/api', () => ({
  ApiError: class ApiError extends Error { code = 'API_ERROR' },
  api: {
    getSettings: vi.fn(), listSkillPresets: vi.fn(), listProjects: vi.fn(),
    updateSettings: vi.fn(), updateProject: vi.fn(), putStyleProfile: vi.fn(),
    extractStyleSample: vi.fn(), listModels: vi.fn(), testConnection: vi.fn(),
  },
}))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('adds a network model and routes Writer through it without exposing saved keys', async () => {
  vi.mocked(api.getSettings).mockResolvedValue({
    style_profile: {}, skill_pack: null, model_routes: {}, model_connections: [], version: 1,
  })
  vi.mocked(api.listSkillPresets).mockResolvedValue([])
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.updateSettings).mockResolvedValue({
    style_profile: {}, skill_pack: null, model_routes: {}, model_connections: [], version: 2,
  })
  vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('11111111-1111-4111-8111-111111111111')

  render(
    <MemoryRouter initialEntries={['/projects/p/settings']}>
      <Routes><Route path="/projects/:projectId/settings" element={<SettingsPage />} /></Routes>
    </MemoryRouter>,
  )
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

  await waitFor(() => expect(api.updateSettings).toHaveBeenCalledWith(
    'p',
    { writer: 'custom:11111111-1111-4111-8111-111111111111' },
    [{
      id: '11111111-1111-4111-8111-111111111111', name: '我的 GPT', protocol: 'openai',
      base_url: 'https://models.example.com/v1', model: 'novel-pro', api_key: 'secret-key',
    }],
  ))
})

it('names the missing field beside the save button and does not save', async () => {
  vi.mocked(api.getSettings).mockResolvedValue({
    style_profile: {}, skill_pack: null, model_routes: {}, model_connections: [], version: 1,
  })
  vi.mocked(api.listSkillPresets).mockResolvedValue([])
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('33333333-3333-4333-8333-333333333333')

  render(
    <MemoryRouter initialEntries={['/projects/p/settings']}>
      <Routes><Route path="/projects/:projectId/settings" element={<SettingsPage />} /></Routes>
    </MemoryRouter>,
  )
  await screen.findByText(/尚未添加网络模型/)
  fireEvent.click(screen.getByRole('button', { name: '添加网络模型' }))
  fireEvent.change(screen.getByLabelText('请求地址'), { target: { value: 'https://models.example.com/v1' } })
  fireEvent.change(screen.getByLabelText('模型 id'), { target: { value: 'novel-pro' } })
  fireEvent.change(screen.getByLabelText(/API Key/), { target: { value: 'secret-key' } })
  fireEvent.click(screen.getByRole('button', { name: '保存连接与路由' }))

  const status = await screen.findByRole('status')
  expect(status.textContent).toContain('第 1 个模型连接缺少：连接名称')
  expect(api.updateSettings).not.toHaveBeenCalled()
})

it('fetches the model list into the datalist and tests connectivity', async () => {
  vi.mocked(api.getSettings).mockResolvedValue({
    style_profile: {}, skill_pack: null, model_routes: {}, model_connections: [], version: 1,
  })
  vi.mocked(api.listSkillPresets).mockResolvedValue([])
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.listModels).mockResolvedValue({ ok: true, models: ['novel-pro', 'novel-mini'], error: null })
  vi.mocked(api.testConnection).mockResolvedValue({ ok: true, latency_ms: 88, reply: 'pong', error: null })
  vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('22222222-2222-4222-8222-222222222222')

  render(
    <MemoryRouter initialEntries={['/projects/p/settings']}>
      <Routes><Route path="/projects/:projectId/settings" element={<SettingsPage />} /></Routes>
    </MemoryRouter>,
  )
  await screen.findByText(/尚未添加网络模型/)
  fireEvent.click(screen.getByRole('button', { name: '添加网络模型' }))
  fireEvent.change(screen.getByLabelText('请求地址'), { target: { value: 'https://models.example.com/v1' } })
  fireEvent.change(screen.getByLabelText('模型 id'), { target: { value: 'novel-pro' } })
  fireEvent.change(screen.getByLabelText(/API Key/), { target: { value: 'secret-key' } })

  fireEvent.click(screen.getByRole('button', { name: '获取模型列表' }))
  await waitFor(() => expect(api.listModels).toHaveBeenCalledWith('p', {
    protocol: 'openai', base_url: 'https://models.example.com/v1', model: 'novel-pro', api_key: 'secret-key',
  }))
  await screen.findByText(/已获取 2 个模型/)
  const options = Array.from(document.querySelectorAll('datalist option'))
    .map((option) => option.getAttribute('value'))
  expect(options).toEqual(['novel-pro', 'novel-mini'])

  fireEvent.click(screen.getByRole('button', { name: '测试连接' }))
  await waitFor(() => expect(api.testConnection).toHaveBeenCalled())
  await screen.findByText(/连接正常 · 88 ms/)
})
