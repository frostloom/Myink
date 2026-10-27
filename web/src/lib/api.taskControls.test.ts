// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { api } from './api'

afterEach(() => vi.unstubAllGlobals())
it.each(['pause', 'resume', 'cancel'] as const)('routes legacy batch %s control to the current task API', async action => {
  const fetcher = vi.fn().mockResolvedValue(new Response('{"task_id":"batch","status":"queued"}'))
  vi.stubGlobal('fetch', fetcher)
  await ({ pause: api.pauseBatch, resume: api.resumeBatch, cancel: api.cancelBatch })[action]('batch')
  expect(fetcher).toHaveBeenCalledWith(`/api/v1/tasks/batch/${action}`, expect.objectContaining({ method: 'POST' }))
})
