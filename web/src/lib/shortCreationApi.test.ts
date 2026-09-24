// 建书对话端点的请求形状。路径是契约的一部分（spec/api-openapi.json 里那几条），
// 组件测试都会 mock 掉 api，所以只有这里能拦住「路径写错」。
// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest'
import { shortCreationApi } from './shortCreationApi'

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  // 用例传的是显式 token，而 request() 在 api.ts:118 发完 fetch 之后会拿它和 getToken() 比
  // （:145），不等就抛 request_aborted —— 200 也一样抛。不种这条会话，四个用例全都断言不到 fetch。
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

it('reads the session from the creation endpoint', async () => {
  const fetchMock = stubJson({ session: {}, messages: [], ready: false })
  await shortCreationApi.get('t')
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/short/creation',
    expect.objectContaining({ method: 'GET' }))
})

it('sends a message together with the current card', async () => {
  const fetchMock = stubJson({ session: {}, messages: [], ready: false })
  await shortCreationApi.send('t', '我想写渡口', { working_title: '渡船' })
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/short/creation/messages',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ content: '我想写渡口', card: { working_title: '渡船' } }),
    }))
})

it('commits with the card and the chosen style', async () => {
  const fetchMock = stubJson({ project_id: 'p1' })
  await shortCreationApi.commit('t', { working_title: '渡船' }, 'builtin:xianxia-jiuzhou')
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/short/creation/commit',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ card: { working_title: '渡船' },
                             style_item_id: 'builtin:xianxia-jiuzhou' }),
    }))
})

it('resets the conversation', async () => {
  const fetchMock = stubJson({ ok: true })
  await shortCreationApi.reset('t')
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/short/creation',
    expect.objectContaining({ method: 'DELETE' }))
})
