// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { flushPromises } from '@vue/test-utils'
const waitFor = vi.waitFor
async function act(run: () => unknown) { await run(); await flushPromises() }
import { defineComponent, h, ref } from 'vue'
import { createMemoryHistory, createRouter, RouterView, useRoute } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ChapterEditor from './ChapterEditor.vue'
import { api, ApiError } from '../../../src/lib/api'
import { liveDrafts } from '../../../src/lib/chapterDraft'
import type { ChapterDetail, ContentUpdateResponse } from '../../../src/types'

vi.mock('../../../src/lib/api', async (original) => {
  const actual = await original<typeof import('../../../src/lib/api')>()
  return { ...actual, api: { ...actual.api, getChapter: vi.fn(), updateContent: vi.fn() } }
})

const chapter = (id = 'one', version = 1): ChapterDetail => ({
  id, chapter_seq: id === 'one' ? 1 : 2, title: id, status: 'confirmed',
  word_count: 2, content: `${id}正文`, summary: null, version,
})
const callbacks = { onNotFound: vi.fn(), onSaved: vi.fn(), onMemoryChanged: vi.fn() }

async function mount(allowMemoryCorrection = true) {
  const Host = defineComponent({ setup: function ChapterEditorHost() {
    const route = useRoute(); const refreshTick = ref(0)
    return () => h('div', [h('button', { onClick: () => refreshTick.value++ }, '模拟生成完成'),
      h(ChapterEditor, { ...callbacks, projectId: 'project', chapter: chapter(String(route.params.cid)), refreshTick: refreshTick.value, allowMemoryCorrection })])
  } })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:cid', component: Host }] })
  await router.push('/one'); await router.isReady()
  render(RouterView, { global: { plugins: [router] } })
  return { navigate: (path: string) => router.push(path), state: { location: { get pathname() { return router.currentRoute.value.path } } } }
}
const text = () => screen.getByRole('textbox', { name: '章节正文' }) as HTMLTextAreaElement
const change = (value: string) => fireEvent.update(text(), value)
const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
const response = (version: number): ContentUpdateResponse => ({
  chapter_id: 'one', chapter_seq: 1, status: 'confirmed', version,
})

beforeEach(() => {
  vi.clearAllMocks()
  liveDrafts.clear()
  sessionStorage.clear()
  localStorage.clear()
  vi.mocked(api.getChapter).mockImplementation(async (_pid, cid) => chapter(cid))
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('章节编辑的草稿和版本保护', () => {
  it('切章和页面重挂载后恢复未提交文字', async () => {
    const router = await mount()
    await screen.findByRole('textbox', { name: '章节正文' })
    await change('尚未保存的重要修改')
    await act(() => router.navigate('/two'))
    await waitFor(() => expect(text().value).toBe('two正文'))
    await act(() => router.navigate('/one'))
    await waitFor(() => expect(text().value).toBe('尚未保存的重要修改'))
    cleanup()
    liveDrafts.clear() // 模拟刷新，只有 sessionStorage 留存。
    await mount()
    await waitFor(() => expect(text().value).toBe('尚未保存的重要修改'))
  })

  it('保存过程中继续输入，不会把新文字误标为已保存', async () => {
    const request = deferred<ContentUpdateResponse>()
    vi.mocked(api.updateContent).mockReturnValueOnce(request.promise)
    await mount()
    await screen.findByRole('textbox', { name: '章节正文' })
    await change('第一次提交')
    await fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await change('提交后继续输入')
    await act(async () => request.resolve(response(2)))
    expect(text().value).toBe('提交后继续输入')
    expect(screen.getByText('草稿已备份到本标签页，尚未提交')).toBeTruthy()
    vi.mocked(api.updateContent).mockResolvedValueOnce(response(3))
    await fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(api.updateContent).toHaveBeenLastCalledWith('project', 'one', '提交后继续输入', 2))
    await screen.findByText('已保存')
  })

  it('旧章迟到的保存响应不会覆盖当前章节', async () => {
    const request = deferred<ContentUpdateResponse>()
    vi.mocked(api.updateContent).mockReturnValueOnce(request.promise)
    const router = await mount()
    await screen.findByRole('textbox', { name: '章节正文' })
    await change('第一章修改')
    await fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await act(() => router.navigate('/two'))
    await waitFor(() => expect(text().value).toBe('two正文'))
    await change('第二章草稿')
    await act(async () => request.resolve(response(2)))
    expect(text().value).toBe('第二章草稿')
    expect(screen.getByText('草稿已备份到本标签页，尚未提交')).toBeTruthy()
  })

  it('409 保留草稿并展示服务器正文，未经确认不会覆盖', async () => {
    await mount()
    await screen.findByRole('textbox', { name: '章节正文' })
    await change('我的修改')
    vi.mocked(api.updateContent).mockRejectedValueOnce(new ApiError(409, 'Conflict', null))
    vi.mocked(api.getChapter).mockResolvedValueOnce({ ...chapter('one', 2), content: '另一个页面的修改' })
    await fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await screen.findByText('另一个页面的修改')
    expect(text().value).toBe('我的修改')
    expect((screen.getByRole('button', { name: '保存' }) as HTMLButtonElement).disabled).toBe(true)
    expect(api.updateContent).toHaveBeenCalledTimes(1)
  })

  it('未保存时不能校正记忆或回退版本；离开页面触发保护', async () => {
    await mount()
    await screen.findByRole('textbox', { name: '章节正文' })
    await change('修改了人物设定')
    for (const name of ['校正记忆', '历史版本']) {
      expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true)
    }
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
  })

  it('短篇整篇成稿没有逐章记忆，就不摆那颗校正按钮', async () => {
    await mount(false)
    await screen.findByRole('textbox', { name: '章节正文' })
    // 校正记忆对的是长篇的账本；短篇按它只会白跑一次抽取，所以整颗藏掉。
    expect(screen.queryByRole('button', { name: '校正记忆' })).toBeNull()
    // 藏的是记忆那一颗，不是整排操作：删章与历史版本照旧。
    expect(screen.getByRole('button', { name: '删除本章' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '历史版本' })).toBeTruthy()
  })

  it('生成刷新保留本地修改并提示冲突', async () => {
    await mount()
    await screen.findByRole('textbox', { name: '章节正文' })
    await change('还没提交的手工修订')
    vi.mocked(api.getChapter).mockResolvedValueOnce({ ...chapter('one', 2), content: '新生成正文' })
    await fireEvent.click(screen.getByRole('button', { name: '模拟生成完成' }))
    await screen.findByText('新生成正文')
    expect(text().value).toBe('还没提交的手工修订')
    expect((screen.getByRole('button', { name: '保存' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('切走再返回产生新草稿后，旧请求不能删除新备份', async () => {
    const request = deferred<ContentUpdateResponse>()
    vi.mocked(api.updateContent).mockReturnValueOnce(request.promise)
    const router = await mount()
    await screen.findByRole('textbox', { name: '章节正文' })
    await change('旧提交')
    await fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await act(() => router.navigate('/two'))
    await waitFor(() => expect(text().value).toBe('two正文'))
    await act(() => router.navigate('/one'))
    await waitFor(() => expect(text().value).toBe('旧提交'))
    await change('返回后新草稿')
    await act(async () => request.resolve(response(2)))
    cleanup()
    liveDrafts.clear()
    await mount()
    await waitFor(() => expect(text().value).toBe('返回后新草稿'))
  })

  it('浏览器存储失败时提醒并拦截离开', async () => {
    const router = await mount()
    await screen.findByRole('textbox', { name: '章节正文' })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    await change('必须保留')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await act(() => router.navigate('/two'))
    expect(confirm).toHaveBeenCalled()
    expect(text().value).toBe('必须保留')
    expect(router.state.location.pathname).toBe('/one')
  })
})
