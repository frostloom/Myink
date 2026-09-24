// 文风库调用层的请求形状。路径是契约的一部分（spec/api-openapi.json 里那几条），
// 组件测试都会 mock 掉 api，所以只有这里能拦住「路径写错」。
// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest'
import { styleLibraryApi } from './styleLibraryApi'

beforeEach(() => {
  localStorage.clear()
  // request() 在「传入 token 与 localStorage 会话不一致」时会抛 request_aborted，
  // 所以调用点传的 token 必须与存票一致（同 adminApi.test.ts 的做法）。
  localStorage.setItem('myink.session', JSON.stringify({
    token: 't', userId: 'u1', username: 'bob', tier: 'normal', role: 'user',
    roleVerified: false, expiresAt: null,
  }))
  vi.restoreAllMocks()
})

function stubJson(body: unknown) {
  // 每个调用都新建一个 Response：mockResolvedValue 会复用同一个实例，
  // 而它的 body 被第一次 res.json() 读掉后就不能再读（删除那条用例连发两次请求）。
  const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

it('lists the library from the owner-scoped endpoint', async () => {
  const fetchMock = stubJson({ items: [] })
  await expect(styleLibraryApi.list('t')).resolves.toEqual({ items: [] })
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/style-library',
    expect.objectContaining({ method: 'GET' }))
})

it('extracts samples without saving anything', async () => {
  const fetchMock = stubJson({ draft: {} })
  await styleLibraryApi.extract('t', ['正文一段'])
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/style-library/samples',
    expect.objectContaining({ method: 'POST', body: JSON.stringify({ samples: ['正文一段'] }) }))
})

it('saves a named item and deletes by id', async () => {
  const fetchMock = stubJson({ ok: true })
  await styleLibraryApi.save('t', { name: '渡口', profile: {}, note: '冷白描', sample_chars: 10 })
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/style-library',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ name: '渡口', profile: {}, note: '冷白描', sample_chars: 10 }),
    }))
  await styleLibraryApi.remove('t', 'item-1')
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/style-library/item-1',
    expect.objectContaining({ method: 'DELETE' }))
})

it('renames through PATCH on the item path', async () => {
  const fetchMock = stubJson({ id: 'item-1', name: '渡口白描', builtin: false })
  await expect(styleLibraryApi.patch('t', 'item-1', { name: '渡口白描' })).resolves.toMatchObject({
    id: 'item-1', name: '渡口白描',
  })
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/style-library/item-1',
    expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ name: '渡口白描' }) }))
})

it('sends only the field being patched', async () => {
  // 后端是「没传的字段不动」，所以 body 里多带一个 undefined 或空串都会改变语义。
  const fetchMock = stubJson({ id: 'item-1', name: '渡口', note: '冷白描' })
  await styleLibraryApi.patch('t', 'item-1', { note: '冷白描' })
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/style-library/item-1',
    expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ note: '冷白描' }) }))
})
