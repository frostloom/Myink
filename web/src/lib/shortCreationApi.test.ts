// 建书对话端点的请求形状。路径是契约的一部分（spec/api-openapi.json 里那几条），
// 组件测试都会 mock 掉 api，所以只有这里能拦住「路径写错」。
// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest'
import { shortCreationApi } from './shortCreationApi'

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  // 用例传的是显式 token，而 request() 发完 fetch 后会核对 localStorage 里的会话归属
  // （api.ts:133、:146）：账号中途被换掉就抛 request_aborted，200 也一样抛。
  // 种下会话让这些用例跑在「请求期间没有换账号」的真实条件下。
  localStorage.setItem('myink.session', JSON.stringify({
    token: 't', userId: 'u1', username: 'alice', tier: 'normal', expiresAt: null,
  }))
})

function stubJson(body: unknown) {
  // 用 mockImplementation 而不是 mockResolvedValue：后者把同一个 Response 实例发给每次调用，
  // 一条用例里发两次请求时，第二次的 body 已经是读空的流，会变成 network_error。
  const fetchMock = vi.fn().mockImplementation(() =>
    Promise.resolve(new Response(JSON.stringify(body), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

it('reads the session list and the latest conversation on load', async () => {
  const fetchMock = stubJson({ session: {}, messages: [], sessions: [], ready: false })
  await shortCreationApi.open('t')
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/short/creation',
    expect.objectContaining({ method: 'GET' }))
})

it('creates an additional conversation', async () => {
  const fetchMock = stubJson({ session: {}, messages: [], sessions: [], ready: false })
  await shortCreationApi.create('t')
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/short/creation/sessions',
    expect.objectContaining({ method: 'POST' }))
})

it('opens one named conversation', async () => {
  const fetchMock = stubJson({ session: {}, messages: [], sessions: [], ready: false })
  await shortCreationApi.openSession('t', 's-2')
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/short/creation/sessions/s-2',
    expect.objectContaining({ method: 'GET' }))
})

it('sends a message to the conversation it belongs to, together with the current card', async () => {
  const fetchMock = stubJson({ session: {}, messages: [], sessions: [], ready: false })
  await shortCreationApi.send('t', 's-2', '我想写渡口', { working_title: '渡船' })
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/short/creation/sessions/s-2/messages',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ content: '我想写渡口', card: { working_title: '渡船' } }),
    }))
})

it('commits the conversation it belongs to with the card and the chosen style', async () => {
  const fetchMock = stubJson({ project_id: 'p1' })
  await shortCreationApi.commit('t', 's-2', { working_title: '渡船' }, 'builtin:xianxia-jiuzhou')
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/short/creation/sessions/s-2/commit',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ card: { working_title: '渡船' },
                             style_item_id: 'builtin:xianxia-jiuzhou' }),
    }))
})

it('deletes a single conversation', async () => {
  const fetchMock = stubJson({ ok: true })
  await shortCreationApi.remove('t', 's-2')
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/short/creation/sessions/s-2',
    expect.objectContaining({ method: 'DELETE' }))
})
