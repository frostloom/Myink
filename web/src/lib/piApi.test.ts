// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest'
import { piApi } from './piApi'
beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('myink.session', JSON.stringify({ token:'token-a',userId:'admin-a',username:'root',tier:'normal',role:'admin',roleVerified:true,expiresAt:Date.now()+60000 }))
  vi.restoreAllMocks()
})
it('reads bounded audit filters through administrator authentication', async () => {
  const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({items:[],total:0,limit:25,offset:0}),{headers:{'Content-Type':'application/json'}}));vi.stubGlobal('fetch',fetcher)
  const controller=new AbortController();await piApi.events('token-a',{runId:'run/一',kind:'analysis',limit:25,offset:0},controller.signal)
  expect(fetcher).toHaveBeenCalledWith('/api/v1/admin/pi/events?run_id=run%2F%E4%B8%80&kind=analysis&limit=25&offset=0',expect.objectContaining({method:'GET',signal:expect.any(AbortSignal),headers:expect.objectContaining({Authorization:'Bearer token-a'})}))
})
it('sends the exact candidate and stable request id without an actor or host command', async () => {
  const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({status:'queued'}),{status:202,headers:{'Content-Type':'application/json'}}));vi.stubGlobal('fetch',fetcher)
  const body={request_id:'10000000-0000-4000-8000-000000000001',cycle_id:'20000000-0000-4000-8000-000000000001',package_sha256:'a'.repeat(64),image_id:`sha256:${'b'.repeat(64)}`,source_sha256:'c'.repeat(64),comparison_sha256:'d'.repeat(64),decision:'publish' as const}
  await piApi.decide('token-a',body)
  expect(fetcher).toHaveBeenCalledWith('/api/v1/admin/pi/decisions',expect.objectContaining({method:'POST',body:JSON.stringify(body),headers:expect.objectContaining({Authorization:'Bearer token-a'})}))
})
