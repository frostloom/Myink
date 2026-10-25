// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, MemoryRouter, Route, RouterProvider, Routes } from 'react-router-dom'
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
  expect(screen.getByRole('link', { name: '高级设置' })).toBeTruthy()
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


it.each(['success', 'failure'] as const)('ignores a late project A settings %s after navigating to B', async (outcome) => {
  let finish!: (value: Awaited<ReturnType<typeof api.getSettings>>) => void
  let fail!: (error: Error) => void
  const settings = { style_profile: {}, skill_pack: null, genre_pack: {}, model_routes: {}, model_connections: [], version: 1 }
  vi.mocked(api.getSettings).mockImplementation(pid => pid === 'a'
    ? new Promise((resolve, reject) => { finish = resolve; fail = reject }) : Promise.resolve(settings))
  vi.mocked(api.listProjects).mockResolvedValue([
    { id: 'a', title: 'A', genre: '悬疑', current_chapter: 0, target_words: 1500 },
    { id: 'b', title: 'B', genre: '悬疑', current_chapter: 0, target_words: 6000 },
  ])
  const router = createMemoryRouter([{ path: '/projects/:projectId/settings', element: <SettingsPage /> }], { initialEntries: ['/projects/a/settings'] })
  render(<RouterProvider router={router} />)
  await act(async () => { await router.navigate('/projects/b/settings') })
  await waitFor(() => expect((screen.getByRole('spinbutton') as HTMLInputElement).value).toBe('6000'))
  await act(async () => { if (outcome === 'success') finish(settings); else fail(new Error('old load failure')) })
  expect((screen.getByRole('spinbutton') as HTMLInputElement).value).toBe('6000')
  expect(screen.queryByText('设置加载失败')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '保存目标字数' }))
  await waitFor(() => expect(api.updateProject).toHaveBeenCalledWith('b', { target_words: 6000 }))
})

it('isolates an old save failure from the new project save in progress', async () => {
  let failA!: (error: Error) => void
  vi.mocked(api.getSettings).mockResolvedValue({ style_profile: {}, skill_pack: null, genre_pack: {}, model_routes: {}, model_connections: [], version: 1 })
  vi.mocked(api.listProjects).mockResolvedValue([
    { id: 'a', title: 'A', genre: '悬疑', current_chapter: 0, target_words: 1500 },
    { id: 'b', title: 'B', genre: '悬疑', current_chapter: 0, target_words: 6000 },
  ])
  vi.mocked(api.updateProject).mockImplementation(pid => pid === 'a'
    ? new Promise((_resolve, reject) => { failA = reject }) : new Promise(() => {}))
  const router = createMemoryRouter([{ path: '/projects/:projectId/settings', element: <SettingsPage /> }], { initialEntries: ['/projects/a/settings'] })
  render(<RouterProvider router={router} />)
  await waitFor(() => expect((screen.getByRole('spinbutton') as HTMLInputElement).value).toBe('1500'))
  fireEvent.click(screen.getByRole('button', { name: '保存目标字数' }))
  await act(async () => { await router.navigate('/projects/b/settings') })
  await waitFor(() => expect((screen.getByRole('spinbutton') as HTMLInputElement).value).toBe('6000'))
  const saveB = screen.getByRole('button', { name: '保存目标字数' }) as HTMLButtonElement
  expect(saveB.disabled).toBe(false)
  fireEvent.click(saveB)
  await act(async () => failA(new Error('old save failure')))
  expect(screen.queryByText('old save failure')).toBeNull()
  expect((screen.getByRole('button', { name: '保存中…' }) as HTMLButtonElement).disabled).toBe(true)
})
