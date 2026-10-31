// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/vue'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { reactive } from 'vue'
import { ApiError } from '../../../../src/lib/api'
import { piApi } from '../../../../src/lib/piApi'
import PiConsolePage from './PiConsolePage.vue'
import { adminContextKey } from './context'
import fixture from './pi-console.fixture.json'
vi.mock('../../../../src/lib/piApi',()=>({piApi:{status:vi.fn(),daily:vi.fn(),runs:vi.fn(),events:vi.fn(),operation:vi.fn(),decide:vi.fn()}}))
const forbidden=vi.fn()
const copy=<T,>(value:T):T=>structuredClone(value)
function setup(){return render(PiConsolePage,{global:{provide:{[adminContextKey as symbol]:reactive({token:'unit-admin',onForbidden:forbidden})}}})}
beforeEach(()=>{
 vi.resetAllMocks()
 vi.mocked(piApi.status).mockResolvedValue(copy(fixture.status) as never)
 vi.mocked(piApi.daily).mockResolvedValue(copy(fixture.daily) as never)
 vi.mocked(piApi.runs).mockResolvedValue(copy(fixture.runs) as never)
 vi.mocked(piApi.events).mockResolvedValue(copy(fixture.events) as never)
 vi.mocked(piApi.operation).mockResolvedValue({...copy(fixture.operation),status:'succeeded'} as never)
 vi.mocked(piApi.decide).mockResolvedValue(copy(fixture.operation) as never)
 vi.spyOn(crypto,'randomUUID').mockReturnValue(fixture.operation.request_id as `${string}-${string}-${string}-${string}-${string}`)
})
afterEach(()=>{cleanup();vi.useRealTimers();vi.restoreAllMocks()})
it('shows evidence gaps, fixed-input results and model hypotheses separately',async()=>{
 setup();await screen.findByRole('heading',{name:'Pi 管理'});await flushPromises()
 expect(screen.getByText('等待发布确认')).toBeTruthy();expect(screen.getByText('证据不足')).toBeTruthy();expect(screen.getByText('0 / 20')).toBeTruthy()
 expect(screen.getByText('线上效果尚未验证')).toBeTruthy();expect(screen.getByText('¥0.052742')).toBeTruthy();expect(screen.getByText('模型建议')).toBeTruthy()
 expect(document.querySelector('img[src="x"]')).toBeNull();expect(screen.getByText(/<img src=x onerror/)).toBeTruthy()
 expect(screen.getAllByText('尚未执行').length).toBeGreaterThan(0);expect(within(screen.getByRole('table',{name:'候选变更范围'})).getByText('src/myink/context_budget.py')).toBeTruthy()
})
it('opens an exact image confirmation and does not send until the final click',async()=>{
 setup();await flushPromises();await fireEvent.click(screen.getByRole('button',{name:'查看并发布'}))
 const dialog=screen.getByRole('dialog',{name:'确认发布镜像'});expect(within(dialog).getByText(fixture.status.candidate.image_id)).toBeTruthy();expect(within(dialog).getByText(fixture.status.candidate.package_sha256)).toBeTruthy();expect(piApi.decide).not.toHaveBeenCalled()
 await fireEvent.click(within(dialog).getByRole('button',{name:'确认发布镜像'}));await flushPromises()
 expect(piApi.decide).toHaveBeenCalledTimes(1);expect(piApi.decide).toHaveBeenCalledWith('unit-admin',expect.objectContaining({request_id:fixture.operation.request_id,cycle_id:fixture.status.cycle_id,package_sha256:fixture.status.candidate.package_sha256,image_id:fixture.status.candidate.image_id,source_sha256:fixture.status.candidate.source_sha256,comparison_sha256:fixture.status.candidate.comparison_sha256,decision:'publish'}),expect.any(AbortSignal))
 expect(screen.getByText(/发布请求已受理|等待宿主处理|正在发布|发布已核验/)).toBeTruthy()
})
it('defer records a hold and never invokes publication confirmation',async()=>{
 vi.mocked(piApi.decide).mockResolvedValue({...copy(fixture.operation),decision:'defer',status:'deferred'} as never)
 setup();await flushPromises();await fireEvent.click(screen.getByRole('button',{name:'暂不发布'}));await flushPromises()
 expect(piApi.decide).toHaveBeenCalledWith('unit-admin',expect.objectContaining({decision:'defer'}),expect.any(AbortSignal));expect(screen.getByText('已记录暂不发布，Pi 继续等待确认。')).toBeTruthy();expect(screen.queryByRole('dialog')).toBeNull()
})
it('a host outage cannot masquerade as no activity or a successful evaluation',async()=>{
 vi.mocked(piApi.status).mockRejectedValue(new ApiError(503,'PI_CONSOLE_UNAVAILABLE',null));setup();await flushPromises();expect(screen.getByRole('alert').textContent).toMatch(/Pi|宿主/);expect(screen.queryByRole('button',{name:'查看并发布'})).toBeNull();expect(screen.queryByText('暂无运行记录')).toBeNull()
})
it('clears protected information immediately when administrator access changes',async()=>{
 setup();await flushPromises();vi.mocked(piApi.status).mockRejectedValue(new ApiError(403,'FORBIDDEN',null));await fireEvent.click(screen.getByRole('button',{name:'刷新 Pi 状态'}));await flushPromises();expect(forbidden).toHaveBeenCalled();expect(screen.queryByText('src/myink/context_budget.py')).toBeNull();expect(screen.queryByRole('button',{name:'查看并发布'})).toBeNull()
})
it('closes an old confirmation when refreshed candidate identity changes',async()=>{
 setup();await flushPromises();await fireEvent.click(screen.getByRole('button',{name:'查看并发布'}));vi.mocked(piApi.status).mockResolvedValue({...copy(fixture.status),package_sha256:'9'.repeat(64),candidate:{...copy(fixture.status.candidate),package_sha256:'9'.repeat(64)}} as never);await fireEvent.click(screen.getByRole('button',{name:'刷新 Pi 状态'}));await flushPromises();expect(screen.queryByRole('dialog')).toBeNull();expect(piApi.decide).not.toHaveBeenCalled();expect(screen.getByText('候选已变化，请重新核对后再发布。')).toBeTruthy()
})
it('does not treat a queued operation as deployed or dispatch another decision',async()=>{
 vi.mocked(piApi.status).mockResolvedValue({...copy(fixture.status),latest_operation:copy(fixture.operation)} as never);vi.mocked(piApi.operation).mockResolvedValue(copy(fixture.operation) as never);setup();await flushPromises();expect(screen.getByText(/等待宿主处理|发布请求已受理/)).toBeTruthy();expect((screen.getByRole('button',{name:'查看并发布'}) as HTMLButtonElement).disabled).toBe(true);expect((screen.getByRole('button',{name:'暂不发布'}) as HTMLButtonElement).disabled).toBe(true);expect(piApi.decide).not.toHaveBeenCalled()
})
it('keeps a completed publication disabled while phase data is still stale',async()=>{
 vi.mocked(piApi.status).mockResolvedValue({...copy(fixture.status),latest_operation:{...copy(fixture.operation),status:'succeeded'}} as never)
 setup();await flushPromises()
 expect((screen.getByRole('button',{name:'查看并发布'}) as HTMLButtonElement).disabled).toBe(true)
 expect((screen.getByRole('button',{name:'暂不发布'}) as HTMLButtonElement).disabled).toBe(true)
})
it('retains a safe disabled confirmation while refreshing after a defer decision',async()=>{
 vi.mocked(piApi.decide).mockResolvedValue({...copy(fixture.operation),decision:'defer',status:'deferred'} as never)
 setup();await flushPromises();await fireEvent.click(screen.getByRole('button',{name:'暂不发布'}));await flushPromises();await fireEvent.click(screen.getByRole('button',{name:'查看并发布'}))
 let resolve:(value:unknown)=>void=()=>{}
 vi.mocked(piApi.status).mockImplementationOnce(()=>new Promise(done=>{resolve=done}) as never)
 await fireEvent.click(screen.getByRole('button',{name:'刷新 Pi 状态'}));await flushPromises()
 const dialog=screen.getByRole('dialog',{name:'确认发布镜像'})
 expect((within(dialog).getByRole('button',{name:'确认发布镜像'}) as HTMLButtonElement).disabled).toBe(true)
 resolve(copy(fixture.status));await flushPromises()
})

it('exposes historical changes and tool request/results with their original counters',async()=>{
 const events=copy(fixture.events)
 Object.assign(events.items[2]!.details,{request_summary:'冻结检查输入',result_summary:'18 项无失败',next_action:'等待人工确认'})
 vi.mocked(piApi.events).mockResolvedValue(events as never)
 setup();await flushPromises()
 expect(screen.getByRole('table',{name:'每日变更范围'})).toBeTruthy()
 expect(screen.getByText('冻结检查输入')).toBeTruthy()
 expect(screen.getByText('18 项无失败')).toBeTruthy()
 expect(screen.getByText('等待人工确认')).toBeTruthy()
 expect(screen.getByText('检查总数')).toBeTruthy()
 expect(screen.getByText('检查失败')).toBeTruthy()
})
it('shows the verified deployment receipt separately from the current candidate',async()=>{
 const state=copy(fixture.status)
 vi.mocked(piApi.status).mockResolvedValue({...state,phase:'observing',deployment:{deployment_id:'verified-deploy-fixture',deployed_at:'2026-10-31T00:27:33+00:00',image_id:state.candidate.image_id,source_sha256:state.candidate.source_sha256,comparison_sha256:state.candidate.comparison_sha256}} as never)
 setup();await flushPromises()
 expect(screen.getByRole('region',{name:'本轮已核验部署'})).toBeTruthy()
 expect(screen.getByText('verified-deploy-fixture')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'查看并发布'})).toBeNull()
})
it('does not call an immediate failed receipt an accepted publication',async()=>{
 vi.mocked(piApi.decide).mockResolvedValue({...copy(fixture.operation),status:'failed'} as never)
 setup();await flushPromises();await fireEvent.click(screen.getByRole('button',{name:'查看并发布'}))
 await fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'确认发布镜像'}));await flushPromises()
 expect(screen.getByText('发布前检查失败')).toBeTruthy()
 expect(screen.queryByText('发布请求已受理，等待宿主处理。')).toBeNull()
})
