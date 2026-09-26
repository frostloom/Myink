// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import StyleLibraryPage from './StyleLibraryPage'
import { styleLibraryApi } from '../lib/styleLibraryApi'

vi.mock('../components/ProjectRail', () => ({ ProjectRail: () => <nav>项目</nav> }))
vi.mock('../lib/api', () => ({ api: { listProjects: vi.fn().mockResolvedValue([]) } }))
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ session: { token: 'tok' }, logout: vi.fn() }),
}))
vi.mock('../hooks/useGuest', () => ({ useGuest: () => false }))
vi.mock('../lib/styleLibraryApi', () => ({
  styleLibraryApi: { list: vi.fn(), extract: vi.fn(), save: vi.fn(), patch: vi.fn(), remove: vi.fn() },
}))

const BUILTIN = {
  id: 'builtin:xianxia-jiuzhou', name: '九州问天', builtin: true, removable: false,
  profile: { pov: '第三人称限知', forbidden: ['网络流行语'] }, note: '', sample_chars: 0,
  created_at: null,
}

beforeEach(() => {
  vi.mocked(styleLibraryApi.list).mockReset()
  vi.mocked(styleLibraryApi.extract).mockReset()
  vi.mocked(styleLibraryApi.save).mockReset()
  vi.mocked(styleLibraryApi.patch).mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderPage() {
  return render(<MemoryRouter><StyleLibraryPage /></MemoryRouter>)
}

it('lists the builtins first and reads their profile back as prose', async () => {
  vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [BUILTIN] })
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '九州问天' }))
  // 看已有项是「读」：中文维度名 + 内容，不是一排只读输入框。
  expect(await screen.findByText('第三人称限知')).toBeTruthy()
  expect(screen.getByText('视角')).toBeTruthy()
  expect(screen.getByText('禁用表达（每行一条）')).toBeTruthy()
  expect(screen.getByText('网络流行语')).toBeTruthy()
  expect(screen.queryByLabelText('视角')).toBeNull()
})

it('hides the delete action for a builtin', async () => {
  vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [BUILTIN] })
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '九州问天' }))
  expect(screen.queryByRole('button', { name: '删除文风' })).toBeNull()
})

it('extracts a sample, lets the user name it, and saves it into the list', async () => {
  vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [] })
  vi.mocked(styleLibraryApi.extract).mockResolvedValue({
    draft: { pov: '第一人称', extract_error: '模型这一趟没成功' },
  })
  vi.mocked(styleLibraryApi.save).mockResolvedValue({
    id: 'new-1', name: '渡口白描', builtin: false, removable: true,
    profile: { pov: '第一人称' }, note: '', sample_chars: 12, created_at: '2026-09-24',
  })
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '新建文风' }))
  fireEvent.change(screen.getByLabelText('粘贴文章'), { target: { value: '渡口的老人守着最后一班船。' } })
  fireEvent.click(screen.getByRole('button', { name: '提取文风' }))
  expect((await screen.findByRole('alert')).textContent).toContain('模型这一趟没成功')
  fireEvent.change(screen.getByLabelText('文风名'), { target: { value: '渡口白描' } })
  fireEvent.click(screen.getByRole('button', { name: '保存文风' }))
  await waitFor(() => expect(styleLibraryApi.save).toHaveBeenCalled())
  // extract_error 只是页面上的降级提示，不能跟着档案一起落库。
  // 这里断言键集合而不是 toMatchObject —— 后者允许多余键，漏一个 extract_error 也照样通过。
  const body = vi.mocked(styleLibraryApi.save).mock.calls[0][1]
  expect(body.name).toBe('渡口白描')
  expect(Object.keys(body.profile)).toEqual(['pov'])
  expect(body.profile).toMatchObject({ pov: '第一人称' })
  expect(await screen.findByRole('button', { name: '渡口白描' })).toBeTruthy()
})

it('renames my own item through patch without touching its profile', async () => {
  const mine = { ...BUILTIN, id: 'mine-1', name: '旧名', builtin: false, removable: true }
  vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [mine] })
  vi.mocked(styleLibraryApi.patch).mockResolvedValue({ ...mine, name: '新名' })
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '旧名' }))
  fireEvent.change(screen.getByLabelText('文风名'), { target: { value: '新名' } })
  fireEvent.click(screen.getByRole('button', { name: '重命名' }))
  await waitFor(() => expect(styleLibraryApi.patch).toHaveBeenCalledWith(
    'tok', 'mine-1', { name: '新名', note: '' }))
})

it('deletes my own item only after the confirmation is accepted', async () => {
  const mine = { ...BUILTIN, id: 'mine-1', name: '旧名', builtin: false, removable: true }
  vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [mine] })
  vi.mocked(styleLibraryApi.remove).mockResolvedValue({ ok: true })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '旧名' }))
  fireEvent.click(screen.getByRole('button', { name: '删除文风' }))
  await waitFor(() => expect(confirm).toHaveBeenCalled())
  expect(styleLibraryApi.remove).not.toHaveBeenCalled()
  confirm.mockReturnValue(true)
  fireEvent.click(screen.getByRole('button', { name: '删除文风' }))
  await waitFor(() => expect(styleLibraryApi.remove).toHaveBeenCalledWith('tok', 'mine-1'))
})

it('renders a profile key it does not understand instead of dropping it', async () => {
  // 统计层偶尔会吐出嵌套对象；认不出来也得把它显示出来，不能整个键消失。
  const odd = { ...BUILTIN, id: 'mine-2', name: '怪档', builtin: false, removable: true,
                profile: { rhythm: { long_sentence: 0.4 } } }
  vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [odd] })
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '怪档' }))
  expect(await screen.findByText('rhythm')).toBeTruthy()
  expect(screen.getByText('{"long_sentence":0.4}')).toBeTruthy()
})

it('names the eight prose dimensions in Chinese and folds the stats away', async () => {
  const extracted = {
    ...BUILTIN, id: 'mine-3', name: '渡口白描', builtin: false, removable: true,
    profile: {
      narrative_voice: '克制的冷调，靠短句与名词收束',
      pacing: '短句为主，到高潮反而放长',
      sentence_len_dist: { short: 0.5, mid: 0.4, long: 0.1 },
      dialogue_ratio: 0.32,
    },
  }
  vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [extracted] })
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '渡口白描' }))
  // 文笔在主区，按中文维度名读得出来。
  expect(await screen.findByText('叙事声音与语气')).toBeTruthy()
  expect(screen.getByText('克制的冷调，靠短句与名词收束')).toBeTruthy()
  expect(screen.getByText('节奏特征')).toBeTruthy()
  // 统计层收进折叠块，但仍在页面上——收起来不等于丢掉。
  expect(screen.getByText(/统计指纹/)).toBeTruthy()
  expect(screen.getByText('句长分布')).toBeTruthy()
  expect(screen.getByText('对话占比')).toBeTruthy()
})

it('keeps the prose dimensions editable while drafting', async () => {
  vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [] })
  vi.mocked(styleLibraryApi.extract).mockResolvedValue({
    draft: { narrative_voice: '冷调', sentence_len_dist: { short: 0.5 } },
  })
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '新建文风' }))
  fireEvent.change(screen.getByLabelText('粘贴文章'), { target: { value: '渡口的老人守着最后一班船。' } })
  fireEvent.click(screen.getByRole('button', { name: '提取文风' }))
  // 草稿里模型给的东西要能改：文笔八维是可编辑的输入框。
  const box = await screen.findByLabelText('叙事声音与语气') as HTMLTextAreaElement
  expect(box.value).toBe('冷调')
  fireEvent.change(box, { target: { value: '冷调，尽量少用形容词' } })
  expect((screen.getByLabelText('叙事声音与语气') as HTMLTextAreaElement).value).toBe('冷调，尽量少用形容词')
})
