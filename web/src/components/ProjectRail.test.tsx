// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import type { Project } from '../types'
import { FEEDBACK_OPEN_EVENT } from './FeedbackWidget'
import { ProjectRail } from './ProjectRail'

const currentSession = vi.hoisted(() => ({ value: {
  username: 'alice', tier: 'normal', role: 'user' as 'user' | 'admin', roleVerified: true,
} }))
// 默认已登录：只有「反馈入口对游客要不要出现」这一条用例需要切走，afterEach 会还原。
const currentStatus = vi.hoisted(() => ({ value: 'authenticated' as 'authenticated' | 'unauthenticated' }))

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ session: currentSession.value, status: currentStatus.value }),
}))

afterEach(() => {
  cleanup()
  currentStatus.value = 'authenticated'
})

function renderRail(path: string, projects: Project[]) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
        <Route path="/long" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
        <Route path="/short" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
        <Route path="/environment" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
        <Route path="/theme" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
        <Route path="/styles" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
        <Route path="/account" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
        <Route path="/admin" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
        <Route path="/appearance" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
        <Route path="/projects/:projectId" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
        <Route path="/projects/:projectId/settings" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
      </Routes>
    </MemoryRouter>,
  )
}

it('shows environment and appearance only on global pages, not inside a book', () => {
  const projects: Project[] = [{ id: 'p1', title: '第一本书', genre: '都市', current_chapter: 1, target_words: 3000 }]

  const { unmount } = renderRail('/projects', projects)
  expect(screen.getByRole('link', { name: '环境配置' })).toBeTruthy()
  expect(screen.getByRole('link', { name: '主题' })).toBeTruthy()
  expect(screen.getByRole('link', { name: '账号' })).toBeTruthy()
  expect(screen.getByText('alice')).toBeTruthy()
  expect(screen.queryByRole('link', { name: '创作设置' })).toBeNull()
  unmount()

  const env = renderRail('/environment', projects)
  expect(screen.getByRole('link', { name: '环境配置' })).toBeTruthy()
  expect(screen.getByRole('link', { name: '主题' })).toBeTruthy()
  env.unmount()

  renderRail('/projects/p1', projects)
  expect(screen.queryByRole('link', { name: '环境配置' })).toBeNull()
  expect(screen.queryByRole('link', { name: '主题' })).toBeNull()
  expect(screen.getByRole('link', { name: '账号' })).toBeTruthy()
  expect(screen.getByRole('link', { name: '创作设置' })).toBeTruthy()
})

it('shows the admin entry only for a server-verified administrator', () => {
  const projects: Project[] = []
  const userView = renderRail('/projects', projects)
  expect(screen.queryByRole('link', { name: '管理后台' })).toBeNull()
  userView.unmount()

  currentSession.value = { ...currentSession.value, role: 'admin', roleVerified: false }
  const cachedView = renderRail('/projects', projects)
  expect(screen.queryByRole('link', { name: '管理后台' })).toBeNull()
  cachedView.unmount()

  currentSession.value = { ...currentSession.value, role: 'admin', roleVerified: true }
  renderRail('/projects', projects)
  expect(screen.getByRole('link', { name: '管理后台' })).toBeTruthy()
})

const twoForms: Project[] = [
  { id: 'l1', title: '长篇一', genre: '仙侠', current_chapter: 3, target_words: 3000, form: 'long' },
  { id: 's1', title: '短篇一', genre: '悬疑', current_chapter: 1, target_words: null, form: 'short' },
]

it('lists long and short as separate sections and filters the books to the one you are in', () => {
  const long = renderRail('/long', twoForms)
  expect(screen.getByRole('link', { name: '长篇' }).getAttribute('href')).toBe('/long')
  expect(screen.getByRole('link', { name: '短篇' }).getAttribute('href')).toBe('/short')
  const longList = within(screen.getByRole('navigation', { name: '作品列表' }))
  expect(longList.getByText('长篇一')).toBeTruthy()
  expect(longList.queryByText('短篇一')).toBeNull()
  long.unmount()

  const short = renderRail('/short', twoForms)
  const shortList = within(screen.getByRole('navigation', { name: '作品列表' }))
  expect(shortList.getByText('短篇一')).toBeTruthy()
  expect(shortList.queryByText('长篇一')).toBeNull()
  short.unmount()

  // 进书之后跟着这本书的形态走，而不是回到某个固定分区。
  renderRail('/projects/s1', twoForms)
  const bookList = within(screen.getByRole('navigation', { name: '作品列表' }))
  expect(bookList.getByText('短篇一')).toBeTruthy()
  expect(bookList.queryByText('长篇一')).toBeNull()
})

// 模式与内容分层（§3.7d）：进书之后「当前是哪种模式」必须读得出来，而它不能占用绿色——
// 绿色只表示「你正在读这一项」，一处。断言 aria-current 而不是 class：分段控件的选中态
// 是样式，当前模式是语义，样式会改，语义不该改。
it('marks the current mode from the book you are in, not from the path', () => {
  const long = renderRail('/projects/l1', twoForms)
  expect(screen.getByRole('link', { name: '长篇' }).getAttribute('aria-current')).toBe('true')
  expect(screen.getByRole('link', { name: '短篇' }).getAttribute('aria-current')).toBeNull()
  long.unmount()

  renderRail('/projects/s1', twoForms)
  expect(screen.getByRole('link', { name: '短篇' }).getAttribute('aria-current')).toBe('true')
  expect(screen.getByRole('link', { name: '长篇' }).getAttribute('aria-current')).toBeNull()
})

// 全局页把两种模式的书一起列出来（下面那条用例），所以那时没有「当前模式」可标。
it('leaves both modes unmarked outside any section', () => {
  renderRail('/theme', twoForms)
  for (const name of ['长篇', '短篇']) {
    expect(screen.getByRole('link', { name }).getAttribute('aria-current')).toBeNull()
  }
})

it('lists both forms on pages that have no section context', () => {
  renderRail('/theme', twoForms)
  const list = within(screen.getByRole('navigation', { name: '作品列表' }))
  expect(list.getByText('长篇一')).toBeTruthy()
  expect(list.getByText('短篇一')).toBeTruthy()
})

it('hides the long-form ledger entries inside a short book', () => {
  const shortBook: Project[] = [
    { id: 'p1', title: '渡船', genre: '悬疑', current_chapter: 5, target_words: 2000, form: 'short' },
  ]
  const { unmount } = renderRail('/projects/p1', shortBook)
  expect(screen.queryByRole('link', { name: '设定' })).toBeNull()
  expect(screen.queryByRole('link', { name: '全局审计' })).toBeNull()
  expect(screen.queryByRole('link', { name: '创作设置' })).toBeNull()
  unmount()

  // 反向对照：同一位置的长篇这三个入口都在——判据是形态，不是「不在书里」
  renderRail('/projects/p1', [{ ...shortBook[0], form: 'long' }])
  expect(screen.getByRole('link', { name: '设定' })).toBeTruthy()
  expect(screen.getByRole('link', { name: '全局审计' })).toBeTruthy()
  expect(screen.getByRole('link', { name: '创作设置' })).toBeTruthy()
})

it('links to the style library only on global pages', () => {
  const { unmount } = renderRail('/environment', [])
  expect(screen.getByRole('link', { name: '文风库' }).getAttribute('href')).toBe('/styles')
  unmount()

  // 与「环境配置」「主题」同一条闸：进书之后这三条都不该在。
  renderRail('/projects/p1', [])
  expect(screen.queryByRole('link', { name: '文风库' })).toBeNull()
})

it('puts a labelled feedback entry in the rail, whatever the lamp is doing', () => {
  renderRail('/long', [])
  // 灯只是捷径：手机端整只被藏掉，桌面上它的点击区压住控件时那一下还要让给控件。
  // 这条入口不持有表单状态，点它只派发事件，面板由挂在 <Outlet> 之外的唯一挂件实例接住。
  const entry = screen.getByRole('button', { name: '反馈' })
  const seen = vi.fn()
  window.addEventListener(FEEDBACK_OPEN_EVENT, seen)
  fireEvent.click(entry)
  window.removeEventListener(FEEDBACK_OPEN_EVENT, seen)
  expect(seen).toHaveBeenCalledTimes(1)
})

it('keeps the feedback entry away from guests, who cannot submit', () => {
  currentStatus.value = 'unauthenticated'
  renderRail('/long', [])
  expect(screen.queryByRole('button', { name: '反馈' })).toBeNull()
})
