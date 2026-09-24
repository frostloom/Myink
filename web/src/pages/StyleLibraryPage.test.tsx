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

it('lists the builtins first and renders their profile keys', async () => {
  vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [BUILTIN] })
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '九州问天' }))
  expect((await screen.findByLabelText('pov') as HTMLTextAreaElement).value).toBe('第三人称限知')
  expect((await screen.findByLabelText('forbidden') as HTMLTextAreaElement).value).toBe('网络流行语')
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
