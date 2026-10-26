import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { ref } from 'vue'
import RankingsPanel from './RankingsPanel.vue'
import { api } from '../../../src/lib/api'
import { useAuth } from '../authContext'
import type { RankingsResponse } from '../../../src/types'
vi.mock('../authContext', () => ({ useAuth: vi.fn() }))
vi.mock('../../../src/lib/api', () => ({ api: { listRankings: vi.fn() } }))
const remote: RankingsResponse = { source: 'remote', tool: 'rankings', fetched_at: '2026-10-25T12:00:00Z', items: [{ rank: 1, title: '渡船', author: '甲', tags: ['悬疑'], hot: '1万' }], error: null }
beforeEach(() => { vi.mocked(useAuth).mockReturnValue({ status: ref('authenticated') } as unknown as ReturnType<typeof useAuth>); vi.mocked(api.listRankings).mockResolvedValue(remote) })
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('prewarms once and opens cached inspiration without another request', async () => {
 render(RankingsPanel)
 await waitFor(() => expect(api.listRankings).toHaveBeenCalledTimes(1))
 expect(screen.queryByText('渡船')).toBeNull()
 await fireEvent.click(screen.getByRole('button', { name: /扫榜灵感/ }))
 expect(await screen.findByText('渡船')).toBeTruthy()
 expect(screen.getByText('实时榜单')).toBeTruthy()
 expect(screen.getByText('悬疑')).toBeTruthy()
 await fireEvent.click(screen.getByRole('button', { name: /扫榜灵感/ }))
 await fireEvent.click(screen.getByRole('button', { name: /扫榜灵感/ }))
 expect(api.listRankings).toHaveBeenCalledTimes(1)
})
it('shows degraded sample metadata and forces a refresh', async () => {
 vi.mocked(api.listRankings).mockResolvedValue({ ...remote, source: 'sample', error: 'disabled' })
 render(RankingsPanel); await fireEvent.click(screen.getByRole('button', { name: /扫榜灵感/ }))
 expect(await screen.findByText(/外部榜单不可用/)).toBeTruthy()
 expect(screen.getByText('样例数据')).toBeTruthy()
 await fireEvent.click(screen.getByRole('button', { name: '刷新' }))
 expect(api.listRankings).toHaveBeenLastCalledWith(true)
})
it('does not prewarm for guests', async () => {
 vi.mocked(useAuth).mockReturnValue({ status: ref('anonymous') } as unknown as ReturnType<typeof useAuth>)
 render(RankingsPanel); await Promise.resolve()
 expect(api.listRankings).not.toHaveBeenCalled()
})
it('shows a retryable refresh failure', async () => {
 render(RankingsPanel); await waitFor(() => expect(api.listRankings).toHaveBeenCalled())
 vi.mocked(api.listRankings).mockRejectedValue(new Error('offline'))
 await fireEvent.click(screen.getByRole('button', { name: '刷新' }))
 expect(await screen.findByText('榜单加载失败')).toBeTruthy()
 expect((screen.getByRole('button', { name: '刷新' }) as HTMLButtonElement).disabled).toBe(false)
})

it('clears authenticated data on logout and ignores an old refresh reply', async () => {
 const status=ref('authenticated')
 vi.mocked(useAuth).mockReturnValue({status} as unknown as ReturnType<typeof useAuth>)
 render(RankingsPanel); await fireEvent.click(screen.getByRole('button',{name:/扫榜灵感/}))
 await screen.findByText('渡船')
 let finish!:(value:RankingsResponse)=>void
 vi.mocked(api.listRankings).mockReturnValue(new Promise(resolve=>{finish=resolve}))
 await fireEvent.click(screen.getByRole('button',{name:'刷新'}))
 status.value='anonymous'
 finish({...remote,items:[{...remote.items[0],title:'旧榜单'}]})
 await waitFor(()=>expect(screen.queryByText('旧榜单')).toBeNull())
 await new Promise(resolve=>setTimeout(resolve,0))
 expect(screen.queryByText('渡船')).toBeNull()
 expect(screen.queryByText('旧榜单')).toBeNull()
})
