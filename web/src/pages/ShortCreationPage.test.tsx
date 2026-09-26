// @vitest-environment jsdom
import { cleanup, createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  styleLibraryApi: { list: vi.fn() },
}))
// rail 要项目列表；这里只关心「rail 在不在」，让它拿到空列表即可。
vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    api: { ...actual.api, listProjects: vi.fn().mockResolvedValue([]) },
  }
})

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

// 一张聊齐备的卡：三段式第二段才看得见它。
const FULL_CARD = {
  working_title: '最后一班渡船', direction: 'd', conflict_core: 'c', genre: 'g',
  protagonist_pressure: 'p', emotional_payoff: 'e', plot_sketch: 's',
  chapter_count: 5, chars_per_chapter: 4000,
}

function renderPage() {
  const router = createMemoryRouter([
    { path: '/short/new', element: <ShortCreationPage /> },
    { path: '/projects/:projectId', element: <div>工作台</div> },
  ], { initialEntries: ['/short/new'] })
  return { ...render(<RouterProvider router={router} />), router }
}

/** 第一段 → 第二段：服务端说齐备之后，点开「开始建书」，等方案卡出现。 */
async function openCard() {
  fireEvent.click(await screen.findByRole('button', { name: '开始建书' }))
  return await screen.findByLabelText('暂定名')
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

it('keeps the card hidden until the server says it is ready', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({ messages: [], ready: false }))
  renderPage()
  // 第一段只有聊天：能说话，但既没有「开始建书」也没有方案卡。
  expect(await screen.findByLabelText('对助手说')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '开始建书' })).toBeNull()
  expect(screen.queryByLabelText('暂定名')).toBeNull()
})

it('shows the start option once ready, then the card, then commits and hands off to the workspace', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    messages: [], ready: true, session: { card: { ...FULL_CARD, working_title: '渡口' } },
  }))
  vi.mocked(shortCreationApi.commit).mockResolvedValue({
    project_id: 'p1', lengths_compressed: false, plan_warning: null, style_name: null,
  })
  const { router } = renderPage()

  // 第二段：卡带着服务端已经攒下的字段出现，作者可以在上面改。
  expect((await openCard() as HTMLTextAreaElement).value).toBe('渡口')
  expect(screen.queryByRole('button', { name: '开始建书' })).toBeNull()

  // 第三段：确认 → 落书 → 进工作台，入队归那边（状态带上才有重试入口）。
  fireEvent.click(screen.getByRole('button', { name: '确认，开写' }))
  await waitFor(() => expect(shortCreationApi.commit).toHaveBeenCalled())
  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p1'))
  expect(router.state.location.state).toEqual({ beginShortWriting: true, planWarning: null })
})

it('shows the greeting and the editable plan card', async () => {
  renderPage()
  expect(await screen.findByText('想写个什么样的短篇？')).toBeTruthy()
})

it('fills the card from the server and defaults the chapter count', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    messages: [], ready: true, session: { card: { working_title: '渡口' } },
  }))
  renderPage()
  await openCard()
  expect((screen.getByLabelText('章数') as HTMLInputElement).value).toBe('5')
})

it('disables confirm until every required field is filled', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    messages: [], ready: true, session: { card: { working_title: '渡口' } },
  }))
  renderPage()
  await openCard()
  const confirm = screen.getByRole('button', { name: '确认，开写' })
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

it('sends on Enter and leaves Shift+Enter to insert a newline', async () => {
  vi.mocked(shortCreationApi.send).mockResolvedValue(payload({ messages: [], ready: false }))
  renderPage()
  const box = await screen.findByLabelText('对助手说')
  fireEvent.change(box, { target: { value: '一个渡口的故事' } })
  fireEvent.keyDown(box, { key: 'Enter', shiftKey: false })
  await waitFor(() => expect(shortCreationApi.send).toHaveBeenCalledWith('t', '一个渡口的故事', {}))
  fireEvent.change(box, { target: { value: '第二句' } })
  fireEvent.keyDown(box, { key: 'Enter', shiftKey: true })
  expect(shortCreationApi.send).toHaveBeenCalledTimes(1)
})

it('does not send on an Enter that is only committing an IME composition', async () => {
  renderPage()
  const box = await screen.findByLabelText('对助手说')
  fireEvent.change(box, { target: { value: '渡口' } })
  // 中文输入法选词时的回车：isComposing 为真，不该当发送。
  const event = createEvent.keyDown(box, { key: 'Enter' })
  Object.defineProperty(event, 'isComposing', { value: true })
  fireEvent(box, event)
  expect(shortCreationApi.send).not.toHaveBeenCalled()
})

it('does not offer a confirm once the session is committed', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    messages: [], ready: true,
    session: { status: 'committed', book_id: 'p1', card: FULL_CARD },
  }))
  renderPage()
  // 已经开写过的会话：既不给方案卡，也不给确认——只留指路的那一条。
  expect(await screen.findByRole('status')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '开始建书' })).toBeNull()
  expect(screen.queryByRole('button', { name: '确认，开写' })).toBeNull()
  const notice = screen.getByRole('status')
  expect(notice.textContent).toContain('重新开始')
  expect(screen.getByRole('link', { name: '这里' }).getAttribute('href')).toBe('/projects/p1')
})

it('starting over clears the conversation', async () => {
  vi.mocked(shortCreationApi.reset).mockResolvedValue({ ok: true })
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '重新开始' }))
  await waitFor(() => expect(shortCreationApi.reset).toHaveBeenCalled())
})

it('keeps the rail so the creation page is not a dead end', async () => {
  renderPage()
  expect(await screen.findByRole('navigation', { name: '作品分区' })).toBeTruthy()
  expect(await screen.findByRole('link', { name: /短篇/ })).toBeTruthy()
})

it('warns that the per-chapter figure will be compressed before commit', async () => {
  // 5 × 8000 超过全篇 20000 上限，后端会按 20000 // 5 = 4000 生成；卡上必须先说清楚。
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    messages: [], ready: true, session: { card: { chapter_count: 5, chars_per_chapter: 8000 } },
  }))
  renderPage()
  await openCard()
  expect(screen.getByText(/归一为每章 4000 字/)).toBeTruthy()
})

it('does not warn when the card fits under the whole-book cap', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    messages: [], ready: true, session: { card: { chapter_count: 5, chars_per_chapter: 4000 } },
  }))
  renderPage()
  await openCard()
  expect(screen.queryByText(/归一为每章/)).toBeNull()
})

it('does not warn when 章数 is fractional and truncation lands on the cap', async () => {
  // 卡上要是直接乘：5.5 × 4000 = 22000 > 20000 会说归一；后端先把卡片字段 int() 截成 5，
  // 5 × 4000 正好等于上限（不是 >），不压缩——卡上不该说要归一。
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({ messages: [], ready: true }))
  renderPage()
  await openCard()
  fireEvent.change(screen.getByLabelText('章数'), { target: { value: '5.5' } })
  fireEvent.change(screen.getByLabelText('每章字数'), { target: { value: '4000' } })
  expect(screen.queryByText(/归一为每章/)).toBeNull()
})

it('does not warn when 每章字数 is fractional and truncation lands on the cap', async () => {
  // 5 × 4000.5 = 20000.25 > 20000 会说归一；后端 int(4000.5) = 4000，5 × 4000 不超上限。
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({ messages: [], ready: true }))
  renderPage()
  await openCard()
  fireEvent.change(screen.getByLabelText('章数'), { target: { value: '5' } })
  fireEvent.change(screen.getByLabelText('每章字数'), { target: { value: '4000.5' } })
  expect(screen.queryByText(/归一为每章/)).toBeNull()
})

it('offers the style selector and a link to the library, with no inline import', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({ messages: [], ready: true }))
  renderPage()
  await openCard()
  expect(screen.getByLabelText('文风')).toBeTruthy()
  expect(screen.getByRole('link', { name: '去文风库添加' }).getAttribute('href')).toBe('/styles')
  // 导入文章那条动线整体搬去文风库页面了，这一页只留一个指路的链接。
  expect(screen.queryByRole('button', { name: '导入文章存成我的文风' })).toBeNull()
  expect(screen.queryByLabelText('粘贴文章')).toBeNull()
})

it('opens the plan card as a modal that Escape and a backdrop click both close', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    messages: [], ready: true, session: { card: FULL_CARD },
  }))
  renderPage()
  await openCard()
  // 悬浮模态：不是右侧内嵌面板，遮罩盖住整页，焦点落在关闭键上。
  const cardDialog = screen.getByRole('dialog', { name: '方案' })
  expect(cardDialog.getAttribute('aria-modal')).toBe('true')
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '关闭方案卡' }))

  fireEvent.keyDown(document, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  // 关掉之后「开始建书」回来，还能再开一次。
  fireEvent.click(screen.getByRole('button', { name: '开始建书' }))
  expect(await screen.findByRole('dialog')).toBeTruthy()
  // 点卡里的东西不算点遮罩，不该关。
  fireEvent.mouseDown(screen.getByLabelText('暂定名'))
  expect(screen.getByRole('dialog')).toBeTruthy()
  fireEvent.mouseDown(screen.getByRole('dialog').parentElement as HTMLElement)
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

it('grows every field box to its content so the dialog keeps a single scrollbar', async () => {
  vi.mocked(shortCreationApi.get).mockResolvedValue(payload({
    messages: [], ready: true, session: { card: FULL_CARD },
  }))
  // jsdom 量不出真实高度，把 scrollHeight 钉成非零值：接线在，每个框就都该拿到内联高。
  const measured = vi.spyOn(Element.prototype, 'scrollHeight', 'get').mockReturnValue(180)
  try {
    renderPage()
    await openCard()
    const boxes = Array.from(screen.getByRole('dialog').querySelectorAll('textarea'))
    expect(boxes.length).toBeGreaterThan(1)
    // 框自己滚 + 弹窗体也滚 = 「能滚的页面里嵌能滚的小页面」，正是要清掉的那条。
    for (const box of boxes) expect((box as HTMLTextAreaElement).style.height).toBe('180px')
  } finally {
    measured.mockRestore()
  }
})

it('keeps the box editable and says it is replying while a turn is in flight', async () => {
  let release: (value: ShortCreationPayload) => void = () => {}
  vi.mocked(shortCreationApi.send).mockReturnValue(new Promise((resolve) => { release = resolve }))
  renderPage()
  const box = await screen.findByLabelText('对助手说')
  fireEvent.change(box, { target: { value: '渡口的故事' } })
  fireEvent.keyDown(box, { key: 'Enter' })
  // 等回复的这几秒里输入框不能变成死的：想接着打下一句，或者改改再发。
  expect(screen.getByRole('button', { name: '正在回复…' })).toBeTruthy()
  expect((box as HTMLTextAreaElement).disabled).toBe(false)
  release(payload({ messages: [], ready: false }))
  await waitFor(() => expect(screen.getByRole('button', { name: '发送' })).toBeTruthy())
})
