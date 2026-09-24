// 短篇端点的请求形状（§13 三层闸门扣章数那条路由）。
// 路径是契约的一部分（spec/api-openapi.json 里那条 /projects/{pid}/short/generate），
// 组件测试都会 mock 掉 api，所以只有这里能拦住「路径写错」。
// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from './api'

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

function stubJson(body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

it('posts the short story generation to the project short route', async () => {
  const fetchMock = stubJson({ task_id: 'task-1', trace_id: 'task-1', status: 'queued' })

  const response = await api.generateShort('pid-1')

  expect(fetchMock).toHaveBeenCalledWith('/api/v1/projects/pid-1/short/generate',
    expect.objectContaining({ method: 'POST' }))
  expect(response.task_id).toBe('task-1')
})

it('sends the form and the per-chapter length when creating a short book', async () => {
  const fetchMock = stubJson({ id: 'pid-2', title: '渡口', genre: '悬疑', current_chapter: 0,
    target_words: 3000, creation_status: 'draft', form: 'short' })

  const project = await api.createProject({
    title: '渡口', premise: '最后一班船', chapter_count: 5, storyline: '',
    form: 'short', chars_per_chapter: 2000,
  })

  expect(project.form).toBe('short')
  expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toMatchObject({
    form: 'short', chars_per_chapter: 2000, chapter_count: 5,
  })
})