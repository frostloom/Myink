import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { flushPromises } from '@vue/test-utils'
import ProjectsPage from './ProjectsPage.vue'
import { setSession } from '../../../src/lib/token'

const books = [
  { id: 'long-ready', title: '长篇正式书', genre: '仙侠', current_chapter: 12, target_words: 2000, creation_status: 'ready', form: 'long' },
  { id: 'legacy', title: '旧版作品', genre: '现实', current_chapter: 1, target_words: null },
  { id: 'short-ready', title: '短篇正式书', genre: '悬疑', current_chapter: 1, target_words: 1000, creation_status: 'ready', form: 'short' },
  { id: 'long-draft', title: '长篇草稿', genre: '仙侠', current_chapter: 0, target_words: 2000, creation_status: 'draft', form: 'long' },
  { id: 'short-draft', title: '短篇草稿', genre: '悬疑', current_chapter: 0, target_words: 1000, creation_status: 'draft', form: 'short' },
]
function response(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status }) }
async function page(form: 'long' | 'short' = 'long') {
  setSession({ token: 'test-token', userId: 'tester', username: 'tester', tier: 'pro', role: 'user', roleVerified: true, expiresAt: Date.now() + 3600000 })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
  await router.push(`/${form}`); await router.isReady()
  return render(ProjectsPage, { props: { form, username: 'tester' }, global: { plugins: [router] } })
}
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it.each(['long', 'short'] as const)('keeps %s works and draft links in their own section', async form => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(books)))
  await page(form); const main = screen.getByRole('main'); const own = form === 'long' ? '长篇' : '短篇'; const other = form === 'long' ? '短篇' : '长篇'
  expect(await within(main).findByText(`${own}正式书`)).toBeTruthy()
  expect(within(main).queryByText(`${other}正式书`)).toBeNull()
  const drafts = within(main).getByRole('region', { name: '待完成作品' })
  expect(within(drafts).getByRole('link').getAttribute('href')).toBe(form === 'long' ? '/long/new?draft=long-draft' : '/projects/short-draft')
  expect(within(main).getByRole('link', { name: `新建${own}` }).getAttribute('href')).toBe(`/${form}/new`)
  const rail = screen.getByRole('navigation', { name: '作品列表' })
  expect(within(rail).queryByText(`${own}草稿`)).toBeNull()
  expect(within(rail).getByText(`${own}正式书`)).toBeTruthy()
})

it('treats a missing form as long and does not nest delete controls inside links', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(books))); await page()
  expect(await within(screen.getByRole('main')).findByText('旧版作品')).toBeTruthy()
  for (const button of screen.getAllByRole('button', { name: /^删除《/ })) expect(button.closest('a')).toBeNull()
})

it('shows loading and then an empty result', async () => {
  let finish!: (r: Response) => void; vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(r => { finish = r })))
  await page(); expect(screen.getByText('加载中…')).toBeTruthy(); finish(response([]))
  expect(await screen.findByText(/还没有长篇作品/)).toBeTruthy()
})

it('shows load failure and retries successfully', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new TypeError('offline')).mockResolvedValueOnce(response(books)))
  await page(); await screen.findByRole('alert'); await fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(await within(screen.getByRole('main')).findByText('长篇正式书')).toBeTruthy()
})

it('does not send a delete when confirmation is cancelled', async () => {
  const fetcher = vi.fn().mockResolvedValue(response(books)); vi.stubGlobal('fetch', fetcher); vi.spyOn(window, 'confirm').mockReturnValue(false)
  await page(); await fireEvent.click(await screen.findByRole('button', { name: '删除《长篇正式书》' }))
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('preserves the book and explains a running-task deletion conflict', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(books)).mockResolvedValueOnce(response({ error: 'busy' }, 409))); vi.spyOn(window, 'confirm').mockReturnValue(true)
  await page(); await fireEvent.click(await screen.findByRole('button', { name: '删除《长篇正式书》' }))
  expect((await screen.findByRole('alert')).textContent).toContain('进行中任务')
  expect(within(screen.getByRole('main')).getByText('长篇正式书')).toBeTruthy()
})

it('reloads the list after successful deletion using the shared API', async () => {
  const calls: { path: string; method: string }[] = []
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    calls.push({ path, method: init.method! })
    return response(init.method === 'DELETE' ? { ok: true } : calls.length === 1 ? books : books.filter(b => b.id !== 'long-ready'))
  })); vi.spyOn(window, 'confirm').mockReturnValue(true)
  await page(); await fireEvent.click(await screen.findByRole('button', { name: '删除《长篇正式书》' }))
  await within(screen.getByRole('main')).findByText('旧版作品')
  await vi.waitFor(() => expect(within(screen.getByRole('main')).queryByText('长篇正式书')).toBeNull())
  expect(calls).toContainEqual({ path: '/api/v1/projects/long-ready', method: 'DELETE' })
})

it('does not reload an old page when its delete finishes after unmount', async () => {
  let finish!: (r: Response) => void
  const fetcher = vi.fn().mockResolvedValueOnce(response(books)).mockImplementationOnce(() => new Promise<Response>(r => { finish = r }))
  vi.stubGlobal('fetch', fetcher); vi.spyOn(window, 'confirm').mockReturnValue(true)
  const view = await page(); await fireEvent.click(await screen.findByRole('button', { name: '删除《长篇正式书》' }))
  view.unmount(); finish(response({ ok: true })); await flushPromises()
  expect(fetcher).toHaveBeenCalledTimes(2)
})

it('shows the guest list without requesting protected project data', async () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
  await router.push('/long')
  render(ProjectsPage, { props: { username: '未登录', guest: true }, global: { plugins: [router] } })
  await flushPromises()
  expect(fetcher).not.toHaveBeenCalled()
  expect(screen.getByText(/还没有长篇作品/)).toBeTruthy()
  expect(screen.queryByRole('button', { name: '登出' })).toBeNull()
  expect(screen.getByRole('link', { name: '登录' })).toBeTruthy()
})
