// @vitest-environment jsdom
import { cleanup, createEvent, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { shortCreationApi, type ShortCreationPayload } from '../lib/shortCreationApi'
import { styleLibraryApi } from '../lib/styleLibraryApi'
import { useAuth } from '../context/AuthContext'
import ShortCreationPage from './ShortCreationPage'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../lib/shortCreationApi', () => ({
  shortCreationApi: { open: vi.fn(), create: vi.fn(), openSession: vi.fn(), send: vi.fn(),
                      commit: vi.fn(), remove: vi.fn() },
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
// 会话列表默认跟着当前会话走——选择器是受控的，列表里没有当前 id 它就会显示空。
function payload(over: {
  session?: Partial<ShortCreationPayload['session']>
  messages?: ShortCreationPayload['messages']
  sessions?: ShortCreationPayload['sessions']
  ready?: boolean
} = {}): ShortCreationPayload {
  const current = { ...session, ...over.session }
  return {
    session: current,
    messages: over.messages ?? [{ id: 1, role: 'assistant', content: '想写个什么样的短篇？', card: null, model_id: null, cost_est: 0, error: null, created_at: '2026-01-01T00:00:00Z' }],
    sessions: over.sessions ?? [{
      id: current.id, title: '新的短篇', status: current.status,
      book_id: current.book_id, updated_at: '2026-01-01T00:00:00Z',
    }],
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
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload())
  vi.mocked(styleLibraryApi.list).mockResolvedValue({ items: [] })
})

afterEach(() => { cleanup(); vi.clearAllMocks() })

it('keeps the card hidden until the server says it is ready', async () => {
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({ messages: [], ready: false }))
  renderPage()
  // 第一段只有聊天：能说话，但既没有「开始建书」也没有方案卡。
  expect(await screen.findByLabelText('对助手说')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '开始建书' })).toBeNull()
  expect(screen.queryByLabelText('暂定名')).toBeNull()
})

it('shows the start option once ready, then the card, then commits and hands off to the workspace', async () => {
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({
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
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({
    messages: [], ready: true, session: { card: { working_title: '渡口' } },
  }))
  renderPage()
  await openCard()
  expect((screen.getByLabelText('章数') as HTMLInputElement).value).toBe('5')
})

it('disables confirm until every required field is filled', async () => {
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({
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
  await waitFor(() => expect(shortCreationApi.send).toHaveBeenCalledWith('t', 's1', '一个渡口的故事', {}))
  fireEvent.change(box, { target: { value: '第二句' } })
  fireEvent.keyDown(box, { key: 'Enter', shiftKey: true })
  expect(shortCreationApi.send).toHaveBeenCalledTimes(1)
})

it('shows the user turn as soon as Enter is pressed, before the reply lands', async () => {
  let release: (value: ShortCreationPayload) => void = () => {}
  vi.mocked(shortCreationApi.send).mockReturnValue(new Promise((resolve) => { release = resolve }))
  renderPage()
  const box = await screen.findByLabelText('对助手说') as HTMLTextAreaElement
  fireEvent.change(box, { target: { value: '一个渡口的故事' } })
  fireEvent.keyDown(box, { key: 'Enter' })

  // 服务端还没回话：自己的话已经在流里，输入框已经空了。
  expect(screen.getByText('一个渡口的故事')).toBeTruthy()
  expect(box.value).toBe('')

  release(payload({
    messages: payload().messages.concat([
      { id: 2, role: 'user', content: '一个渡口的故事', card: null, model_id: null, cost_est: 0, error: null, created_at: '2026-01-01T00:00:01Z' },
      { id: 3, role: 'assistant', content: '主角的压力是什么？', card: null, model_id: 'm', cost_est: 0.002, error: null, created_at: '2026-01-01T00:00:02Z' },
    ]),
  }))
  expect(await screen.findByText('主角的压力是什么？')).toBeTruthy()
  // 服务端的真消息接管之后，先前那句临时挂在流里的不能重复出现。
  expect(screen.getAllByText('一个渡口的故事')).toHaveLength(1)
})

it('puts the message back in the composer when the send fails', async () => {
  vi.mocked(shortCreationApi.send).mockRejectedValue(new Error('boom'))
  renderPage()
  const box = await screen.findByLabelText('对助手说') as HTMLTextAreaElement
  fireEvent.change(box, { target: { value: '一个渡口的故事' } })
  fireEvent.keyDown(box, { key: 'Enter' })
  expect(box.value).toBe('')

  await waitFor(() => expect(box.value).toBe('一个渡口的故事'))
  // 发送失败：输入框拿回原话，对话流里不留那条临时消息。
  expect(within(screen.getByLabelText('建书对话')).queryByText('一个渡口的故事')).toBeNull()
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
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({
    messages: [], ready: true,
    session: { status: 'committed', book_id: 'p1', card: FULL_CARD },
  }))
  renderPage()
  // 已经开写过的会话：既不给方案卡，也不给确认——只留指路的那一条。
  expect(await screen.findByRole('status')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '开始建书' })).toBeNull()
  expect(screen.queryByRole('button', { name: '确认，开写' })).toBeNull()
  const notice = screen.getByRole('status')
  expect(notice.textContent).toContain('新建会话')
  expect(screen.getByRole('link', { name: '这里' }).getAttribute('href')).toBe('/projects/p1')
})

it('starts a second conversation without touching the first one', async () => {
  const first = { id: 's1', title: '最后一班渡船', status: 'active' as const, book_id: null, updated_at: '2026-01-01T00:00:00Z' }
  const second = { id: 's2', title: '新的短篇', status: 'active' as const, book_id: null, updated_at: '2026-01-02T00:00:00Z' }
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({ sessions: [first] }))
  vi.mocked(shortCreationApi.create).mockResolvedValue(payload({
    session: { id: 's2' }, messages: [], sessions: [second, first],
  }))
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '新建会话' }))
  await waitFor(() => expect(shortCreationApi.create).toHaveBeenCalled())
  // 两条都在列表里：新的那条是当前打开的，旧的原样留着能切回去。
  await waitFor(() => expect((screen.getByLabelText('建书会话') as HTMLSelectElement).value).toBe('s2'))
  const options = within(screen.getByLabelText('建书会话')).getAllByRole('option')
  expect(options.map((o) => o.textContent)).toEqual(['新的短篇', '最后一班渡船'])
})

it('switches back to an earlier conversation and shows its own transcript', async () => {
  const older = { id: 's0', title: '渡口旧稿', status: 'active' as const, book_id: null, updated_at: '2026-01-01T00:00:00Z' }
  const newer = { id: 's1', title: '新的短篇', status: 'active' as const, book_id: null, updated_at: '2026-01-02T00:00:00Z' }
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({
    messages: [{ id: 9, role: 'assistant', content: '这条是最新的', card: null, model_id: null, cost_est: 0, error: null, created_at: '2026-01-02T00:00:00Z' }],
    sessions: [newer, older],
  }))
  vi.mocked(shortCreationApi.openSession).mockResolvedValue(payload({
    session: { id: 's0', card: { working_title: '渡口旧稿' } }, sessions: [newer, older],
    messages: [{ id: 1, role: 'user', content: '早先说过的渡口', card: null, model_id: null, cost_est: 0, error: null, created_at: '2026-01-01T00:00:00Z' }],
  }))
  renderPage()
  expect(await screen.findByText('这条是最新的')).toBeTruthy()

  fireEvent.change(screen.getByLabelText('建书会话'), { target: { value: 's0' } })
  await waitFor(() => expect(shortCreationApi.openSession).toHaveBeenCalledWith('t', 's0'))
  // 切过去看到的是那条会话自己的记录，不是上一条的。
  expect(await screen.findByText('早先说过的渡口')).toBeTruthy()
  expect(screen.queryByText('这条是最新的')).toBeNull()
})

it('deletes one conversation after confirming, leaving the others alone', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
  try {
    const older = { id: 's0', title: '渡口旧稿', status: 'active' as const, book_id: null, updated_at: '2026-01-01T00:00:00Z' }
    const newer = { id: 's1', title: '最后一班渡船', status: 'active' as const, book_id: null, updated_at: '2026-01-02T00:00:00Z' }
    // 删掉之后重新取最近的一条——剩下的是 older。
    vi.mocked(shortCreationApi.remove).mockResolvedValue({ ok: true })
    vi.mocked(shortCreationApi.open)
      .mockResolvedValueOnce(payload({ sessions: [newer, older] }))
      .mockResolvedValue(payload({ session: { id: 's0' }, sessions: [older] }))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '删除会话' }))
    await waitFor(() => expect(shortCreationApi.remove).toHaveBeenCalledWith('t', 's1'))
    expect(confirmSpy).toHaveBeenCalled()
    await waitFor(() => expect((screen.getByLabelText('建书会话') as HTMLSelectElement).value).toBe('s0'))
  } finally {
    confirmSpy.mockRestore()
  }
})

it('keeps the conversation when the delete confirmation is dismissed', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
  try {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '删除会话' }))
    expect(shortCreationApi.remove).not.toHaveBeenCalled()
  } finally {
    confirmSpy.mockRestore()
  }
})

it('prevents messages from being submitted from a committed session', async () => {
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({
    session: { status: 'committed', book_id: 'p1', card: FULL_CARD }, ready: true,
  }))
  renderPage()
  const box = await screen.findByLabelText('对助手说')
  expect((box as HTMLTextAreaElement).disabled).toBe(true)
  fireEvent.change(box, { target: { value: '继续写' } })
  fireEvent.keyDown(box, { key: 'Enter' })
  expect(shortCreationApi.send).not.toHaveBeenCalled()
  expect((screen.getByRole('button', { name: '已开写' }) as HTMLButtonElement).disabled).toBe(true)
})

it('labels a pending commit as planning and locks the card against further changes', async () => {
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({ ready: true, session: { card: FULL_CARD } }))
  vi.mocked(shortCreationApi.commit).mockReturnValue(new Promise(() => {}))
  renderPage()
  await openCard()
  fireEvent.click(screen.getByRole('button', { name: '确认，开写' }))
  expect(screen.getByRole('button', { name: '正在规划…' })).toBeTruthy()
  expect((screen.getByLabelText('暂定名') as HTMLTextAreaElement).disabled).toBe(true)
  expect(screen.queryByRole('button', { name: '正在回复…' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '关闭方案卡' }))
  expect(screen.getByText('正在规划章节…')).toBeTruthy()
})

it('labels opening a new conversation separately from waiting for an assistant reply', async () => {
  vi.mocked(shortCreationApi.create).mockReturnValue(new Promise(() => {}))
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '新建会话' }))
  expect(screen.getByRole('button', { name: '正在新建…' })).toBeTruthy()
  expect(screen.getByText('正在新建会话…')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '正在回复…' })).toBeNull()
})

it('keeps keyboard focus inside the modal and restores it to the opener', async () => {
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({ ready: true, session: { card: FULL_CARD } }))
  renderPage()
  const opener = await screen.findByRole('button', { name: '开始建书' })
  opener.focus()
  fireEvent.click(opener)
  const close = screen.getByRole('button', { name: '关闭方案卡' })
  const confirm = screen.getByRole('button', { name: '确认，开写' })
  fireEvent.keyDown(close, { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(confirm)
  fireEvent.keyDown(confirm, { key: 'Tab' })
  expect(document.activeElement).toBe(close)
  fireEvent.keyDown(close, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(opener)
})

it('preserves the next draft typed while the previous message is in flight', async () => {
  let release: (value: ShortCreationPayload) => void = () => {}
  vi.mocked(shortCreationApi.send).mockReturnValue(new Promise((resolve) => { release = resolve }))
  renderPage()
  const box = await screen.findByLabelText('对助手说') as HTMLTextAreaElement
  fireEvent.change(box, { target: { value: '先写渡口' } })
  fireEvent.keyDown(box, { key: 'Enter' })
  fireEvent.change(box, { target: { value: '再加一个摆渡人' } })
  release(payload())
  await waitFor(() => expect(screen.getByRole('button', { name: '发送' })).toBeTruthy())
  expect(box.value).toBe('再加一个摆渡人')
})

it('keeps the rail so the creation page is not a dead end', async () => {
  renderPage()
  expect(await screen.findByRole('navigation', { name: '作品分区' })).toBeTruthy()
  expect(await screen.findByRole('link', { name: /短篇/ })).toBeTruthy()
})

it('warns that the per-chapter figure will be compressed before commit', async () => {
  // 5 × 8000 超过全篇 20000 上限，后端会按 20000 // 5 = 4000 生成；卡上必须先说清楚。
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({
    messages: [], ready: true, session: { card: { chapter_count: 5, chars_per_chapter: 8000 } },
  }))
  renderPage()
  await openCard()
  expect(screen.getByText(/归一为每章 4000 字/)).toBeTruthy()
})

it('does not warn when the card fits under the whole-book cap', async () => {
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({
    messages: [], ready: true, session: { card: { chapter_count: 5, chars_per_chapter: 4000 } },
  }))
  renderPage()
  await openCard()
  expect(screen.queryByText(/归一为每章/)).toBeNull()
})

it('does not warn when 章数 is fractional and truncation lands on the cap', async () => {
  // 卡上要是直接乘：5.5 × 4000 = 22000 > 20000 会说归一；后端先把卡片字段 int() 截成 5，
  // 5 × 4000 正好等于上限（不是 >），不压缩——卡上不该说要归一。
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({ messages: [], ready: true }))
  renderPage()
  await openCard()
  fireEvent.change(screen.getByLabelText('章数'), { target: { value: '5.5' } })
  fireEvent.change(screen.getByLabelText('每章字数'), { target: { value: '4000' } })
  expect(screen.queryByText(/归一为每章/)).toBeNull()
})

it('does not warn when 每章字数 is fractional and truncation lands on the cap', async () => {
  // 5 × 4000.5 = 20000.25 > 20000 会说归一；后端 int(4000.5) = 4000，5 × 4000 不超上限。
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({ messages: [], ready: true }))
  renderPage()
  await openCard()
  fireEvent.change(screen.getByLabelText('章数'), { target: { value: '5' } })
  fireEvent.change(screen.getByLabelText('每章字数'), { target: { value: '4000.5' } })
  expect(screen.queryByText(/归一为每章/)).toBeNull()
})

it('offers the style selector and a link to the library, with no inline import', async () => {
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({ messages: [], ready: true }))
  renderPage()
  await openCard()
  expect(screen.getByLabelText('文风')).toBeTruthy()
  expect(screen.getByRole('link', { name: '去文风库添加' }).getAttribute('href')).toBe('/styles')
  // 导入文章那条动线整体搬去文风库页面了，这一页只留一个指路的链接。
  expect(screen.queryByRole('button', { name: '导入文章存成我的文风' })).toBeNull()
  expect(screen.queryByLabelText('粘贴文章')).toBeNull()
})

it('opens the plan card as a modal that Escape and a backdrop click both close', async () => {
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({
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
  vi.mocked(shortCreationApi.open).mockResolvedValue(payload({
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
