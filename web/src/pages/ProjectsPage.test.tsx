// @vitest-environment jsdom
// 长短篇各是一张列表：同一形态的书与草稿才出现在自己的分区里，入口也各指各的建书动线。
import { cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import ProjectsPage from './ProjectsPage'

vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ logout: vi.fn(), session: { username: 'tester' } }) }))
vi.mock('../lib/api', async (original) => ({
  ...await original<typeof import('../lib/api')>(),
  api: { listProjects: vi.fn().mockResolvedValue([
    { id: 'long-ready', title: '长篇正式书', genre: '仙侠', current_chapter: 12, creation_status: 'ready', form: 'long' },
    { id: 'short-ready', title: '短篇正式书', genre: '悬疑', current_chapter: 1, creation_status: 'ready', form: 'short' },
    { id: 'long-draft', title: '长篇草稿', genre: '仙侠', current_chapter: 0, creation_status: 'draft', form: 'long' },
    { id: 'short-draft', title: '短篇草稿', genre: '悬疑', current_chapter: 0, creation_status: 'draft', form: 'short' },
  ]) },
}))
afterEach(cleanup)

function renderPage(form: 'long' | 'short') {
  return render(<MemoryRouter><ProjectsPage form={form} /></MemoryRouter>)
}

it('shows only long-form work on the long page and routes its new-book entry to /long/new', async () => {
  renderPage('long')
  const main = await screen.findByRole('main')
  expect(await within(main).findByText('长篇正式书')).toBeTruthy()
  expect(within(main).queryByText('短篇正式书')).toBeNull()
  const drafts = within(main).getByRole('region', { name: '待完成作品' })
  expect(within(drafts).getByRole('link').getAttribute('href')).toBe('/long/new?draft=long-draft')
  expect(within(drafts).queryByText('短篇草稿')).toBeNull()
  expect(within(main).getByRole('link', { name: '新建长篇' }).getAttribute('href')).toBe('/long/new')
  expect(within(main).getByRole('heading', { level: 1 }).textContent).toBe('长篇')
})

it('shows only short-form work on the short page and routes its new-book entry to /short/new', async () => {
  renderPage('short')
  const main = await screen.findByRole('main')
  expect(await within(main).findByText('短篇正式书')).toBeTruthy()
  expect(within(main).queryByText('长篇正式书')).toBeNull()
  const drafts = within(main).getByRole('region', { name: '待完成作品' })
  expect(within(drafts).getByRole('link').getAttribute('href')).toBe('/short/new?draft=short-draft')
  expect(within(drafts).queryByText('长篇草稿')).toBeNull()
  expect(within(main).getByRole('link', { name: '新建短篇' }).getAttribute('href')).toBe('/short/new')
  expect(within(main).getByRole('heading', { level: 1 }).textContent).toBe('短篇')
})

it('keeps unfinished books out of the writing rail', async () => {
  renderPage('long')
  await screen.findAllByText('长篇正式书')
  const rail = screen.getByRole('navigation', { name: '作品列表' })
  expect(within(rail).queryByText('长篇草稿')).toBeNull()
  expect(within(rail).getByText('长篇正式书')).toBeTruthy()
})
