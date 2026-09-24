// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { shortCreationApi, type ShortCreationPayload } from '../lib/shortCreationApi'
import { styleLibraryApi } from '../lib/styleLibraryApi'
import { useAuth } from '../context/AuthContext'
import ShortCreationPage from './ShortCreationPage'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../lib/shortCreationApi', () => ({
  shortCreationApi: { get: vi.fn(), send: vi.fn(), commit: vi.fn(), reset: vi.fn() },
}))
vi.mock('../lib/styleLibraryApi', () => ({
  styleLibraryApi: { list: vi.fn(), extract: vi.fn(), save: vi.fn(), remove: vi.fn() },
}))

const session: ShortCreationPayload['session'] = {
  id: 's1', status: 'active', card: {}, style_item_id: null, style_name: null, book_id: null,
}

// 覆盖项按需给：session 只给要改的字段（卡片就是这么在用例里补出来的）。
function payload(over: {
  session?: Partial<ShortCreationPayload['session']>
  messages?: ShortCreationPayload['messages']
  ready?: boolean
} = {}): ShortCreationPayload {
  return {
    session: { ...session, ...over.session },
    messages: over.messages ?? [{ id: 1, role: 'assistant', content: '想写个什么样的短篇？', card: null, model_id: null, cost_est: 0, error: null, created_at: '2026-01-01T00:00:00Z' }],
    ready: over.ready ?? false,
  }
}

function renderPage() {
  const router = createMemoryRouter([
    { path: '/short/new', element: <ShortCreationPage /> },
    { path: '/projects/:projectId', element: <div>工作台</div> },
  ], { initialEntries: ['/short/new'] })
  return { ...render(<RouterProvider router={router} />), router }
}

beforeEach(() => {
  vi.mocked(useAuth).mockReturnValue({
    session: { token: 't', userId: 'u1', username: 'alice', tier: 'normal', role: 'user', roleVerified: true, expiresAt: Date.now() + 60000 },
    status: 'authenticated', revalidate: vi.fn(), logout: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>)
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload())
  vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [] })
})

afterEach(() => { cleanup(); vi.clearAllMocks() })

it('shows the greeting and the editable plan card', async () => {
  renderPage()
  expect(await screen.findByText('想写个什么样的短篇？')).toBeTruthy()
  expect(screen.getByLabelText('暂定名')).toBeTruthy()
  expect((screen.getByLabelText('章数') as HTMLInputElement).value).toBe('5')
})

it('disables confirm until every required field is filled', async () => {
  renderPage()
  const confirm = await screen.findByRole('button', { name: '确认，开写' })
  expect((confirm as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(screen.getByLabelText('方向'), { target: { value: '一句话方向' } })
  expect((confirm as HTMLButtonElement).disabled).toBe(true)   // 只有一格还不够
})

it('sends the message and renders both sides of the turn', async () => {
  vi.mocked(shortCreationApi.send).mockResolvedValue(payload({
    messages: payload().messages.concat([
      { id: 2, role: 'user', content: '渡口的故事', card: null, model_id: null, cost_est: 0, error: null, created_at: '2026-01-01T00:00:01Z' },
      { id: 3, role: 'assistant', content: '主角的压力是什么？', card: null, model_id: 'm', cost_est: 0.002, error: null, created_at: '2026-01-01T00:00:02Z' },
    ]),
  }))
  renderPage()
  fireEvent.change(await screen.findByLabelText('对助手说'), { target: { value: '渡口的故事' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  expect(await screen.findByText('主角的压力是什么？')).toBeTruthy()
  expect(screen.getByText('渡口的故事')).toBeTruthy()
})

it('confirms, then leaves for the workspace so writing starts there', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    ready: true,
    session: { card: { working_title: '最后一班渡船', direction: 'd', conflict_core: 'c', genre: 'g', protagonist_pressure: 'p', emotional_payoff: 'e', plot_sketch: 's', chapter_count: 5, chars_per_chapter: 4000 } },
  }))
  vi.mocked(shortCreationApi.commit).mockResolvedValue({
    project_id: 'p1', lengths_compressed: false, plan_warning: null, style_name: null,
  })
  const { router } = renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '确认，开写' }))
  // commit 只落书不出稿：入队由工作台那条路做（配额与成本只有一份实现）
  await waitFor(() => expect(shortCreationApi.commit).toHaveBeenCalled())
  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p1'))
})

it('starting over clears the conversation', async () => {
  vi.mocked(shortCreationApi.reset).mockResolvedValue({ ok: true })
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '重新开始' }))
  await waitFor(() => expect(shortCreationApi.reset).toHaveBeenCalled())
})

it('warns that the per-chapter figure will be compressed before commit', async () => {
  // 5 × 8000 超过全篇 20000 上限，后端会按 20000 // 5 = 4000 生成；卡上必须先说清楚。
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    session: { card: { chapter_count: 5, chars_per_chapter: 8000 } },
  }))
  renderPage()
  expect(await screen.findByText(/归一为每章 4000 字/)).toBeTruthy()
})

it('does not warn when the card fits under the whole-book cap', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    session: { card: { chapter_count: 5, chars_per_chapter: 4000 } },
  }))
  renderPage()
  await screen.findByLabelText('章数')
  expect(screen.queryByText(/归一为每章/)).toBeNull()
})

it('does not offer a confirm that can only fail once the session is committed', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    session: {
      status: 'committed',
      book_id: 'p1',
      card: {
        working_title: '最后一班渡船', direction: 'd', conflict_core: 'c', genre: 'g',
        protagonist_pressure: 'p', emotional_payoff: 'e', plot_sketch: 's',
        chapter_count: 5, chars_per_chapter: 4000,
      },
    },
  }))
  renderPage()
  const confirm = await screen.findByRole('button', { name: '确认，开写' })
  expect((confirm as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(confirm)
  expect(shortCreationApi.commit).not.toHaveBeenCalled()
  // 卡已填满也不该说「还差几个必填项」，而应指路「重新开始」，并给出刚开写的那本。
  const notice = screen.getByRole('status')
  expect(notice.textContent).toContain('重新开始')
  expect(screen.getByRole('link', { name: '这里' }).getAttribute('href')).toBe('/projects/p1')
})
