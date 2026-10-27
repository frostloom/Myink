import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/vue'
import {createRouter,createMemoryHistory} from 'vue-router'
import {api} from '../../../src/lib/api'
import {writingResources} from '../../../src/lib/writingResources'
import ResourcesPage from './ResourcesPage.vue'
afterEach(()=>{cleanup();vi.restoreAllMocks()})
async function page(){
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/projects/:projectId/resources',component:{template:'<div />'}},{path:'/:pathMatch(.*)*',component:{template:'<div />'}}]})
 await router.push({path:'/projects/a/resources',state:{planWarning:'请核对方案'}})
 render(ResourcesPage,{global:{plugins:[router]}});return router
}
it.each(['short','long'])('redirects legacy %s resources URLs without reading a resource snapshot',async form=>{
 vi.spyOn(api,'listProjects').mockResolvedValue([{id:'a',form}] as never)
 const snapshot=vi.spyOn(writingResources,'snapshot')
 const router=await page()
 await vi.waitFor(()=>expect(router.currentRoute.value.path).toBe(form==='short'?'/projects/a':'/projects/a/settings'))
 expect(snapshot).not.toHaveBeenCalled()
 expect(screen.queryByText('本书资源快照')).toBeNull()
 expect(router.options.history.state.beginShortWriting).toBeUndefined()
})
it('shows a retry instead of resource content if project lookup fails',async()=>{
 vi.spyOn(api,'listProjects').mockRejectedValueOnce(new Error('不可用')).mockResolvedValue([{id:'a',form:'short'}] as never)
 const router=await page();await screen.findByRole('alert')
 await fireEvent.click(screen.getByRole('button',{name:'重新加载'}))
 await vi.waitFor(()=>expect(router.currentRoute.value.path).toBe('/projects/a'))
})
