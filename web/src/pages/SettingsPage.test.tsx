// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import SettingsPage from './SettingsPage'
import { api } from '../lib/api'

vi.mock('../components/ProjectRail', () => ({ ProjectRail: () => <nav>项目</nav> }))
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ logout: vi.fn() }) }))
vi.mock('../lib/api', () => ({
  ApiError: class ApiError extends Error { code = 'API_ERROR' },
  api: {
    getSettings: vi.fn(), listProjects: vi.fn(),
    updateProject: vi.fn(),
    putGenrePack: vi.fn(), restoreGenrePack: vi.fn(),
  },
}))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('keeps genre information and generation settings, hosts no style editing', async () => {
  vi.mocked(api.getSettings).mockResolvedValue({
    style_profile: {}, skill_pack: null, genre_pack: {}, model_routes: {},
    model_connections: [], version: 1,
  })
  vi.mocked(api.listProjects).mockResolvedValue([])

  render(
    <MemoryRouter initialEntries={['/projects/p/settings']}>
      <Routes><Route path="/projects/:projectId/settings" element={<SettingsPage />} /></Routes>
    </MemoryRouter>,
  )
  await screen.findByText('生成设置')
  expect(screen.getByText('本书题材')).toBeTruthy()
  // 文风在建书时定死，本页不再有编辑入口（也不再有样本提取）
  expect(screen.queryByText('文风档案')).toBeNull()
  expect(screen.queryByText('样本提取')).toBeNull()
  expect(screen.queryByText('题材预设')).toBeNull()
  expect(screen.queryByText('模型连接与路由')).toBeNull()
  expect(screen.getByRole('link', { name: '模型偏好与扫榜' })).toBeTruthy()
})

it('keeps published genre snapshots read only and never offers root editing or restore', async () => {
 vi.mocked(api.getSettings).mockResolvedValue({style_profile:{},skill_pack:null,model_routes:{},model_connections:[],version:1,genre_pack:{source_id:'fantasy',source_name:'奇幻',secondary_id:null,secondary_name:null,selling_point:'已发布卖点',subgenres:[],taboos:[],pacing:'',satisfaction:[],mechanics:[],world_hints:[]}})
 vi.mocked(api.listProjects).mockResolvedValue([])
 render(<MemoryRouter initialEntries={['/projects/p/settings']}><Routes><Route path="/projects/:projectId/settings" element={<SettingsPage/>}/></Routes></MemoryRouter>)
 await screen.findByText('已发布卖点')
 expect(screen.queryByRole('textbox')).toBeNull()
 expect(screen.queryByRole('button',{name:'保存本书题材'})).toBeNull()
 expect(screen.queryByRole('button',{name:'恢复建书时的题材字段'})).toBeNull()
})
