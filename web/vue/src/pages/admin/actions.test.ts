import WritingResources from './WritingResources'
import { afterEach,describe,expect,it,vi } from 'vitest'
import { defineComponent,h,ref } from 'vue'
import { RouterView,createMemoryHistory,createRouter } from 'vue-router'
import { flushPromises,mount } from '@vue/test-utils'
import AdminPage from '../AdminPage.vue'
import { AdminConsole } from './AdminConsole'
import { authKey } from '../../authContext'
import type { SessionScope } from '../../session'
const wrappers:ReturnType<typeof mount>[]=[]
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers.length=0;vi.unstubAllGlobals()})
async function setup(tab:string, deniedRead=false){
 const revalidate=vi.fn()
 vi.stubGlobal('fetch',async(_input:string,init?:RequestInit)=>new Response(JSON.stringify(init?.method&&init.method!=='GET'?{detail:'forbidden'}:{items:tab==='feedback'?[{id:'f',username:'作者',category:'bug',description:'机密反馈',status:'open',attachments:[],created_at:'2026-10-25'}]:[],total:tab==='feedback'?1:0,offset:0,limit:25}),{status:deniedRead||init?.method&&init.method!=='GET'?403:200}))
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/admin',component:AdminPage,children:[{path:'',component:deniedRead?WritingResources:AdminConsole}]}]})
 await router.push('/admin?tab='+tab);await router.isReady()
 const wrapper=mount(defineComponent({render:()=>h(RouterView)}),{global:{plugins:[router],provide:{[authKey as symbol]:{session:ref({token:'token',userId:'u',username:'a',role:'admin',roleVerified:true}),status:ref('authenticated'),revalidate,logout:vi.fn()} as unknown as SessionScope},stubs:{AdminRail:true}}});wrappers.push(wrapper);await flushPromises();return {wrapper,revalidate}
}
describe('administrator mutations reject revoked authority',()=>{
 it('clears protected resource views when their initial catalog returns 403',async()=>{const {wrapper,revalidate}=await setup('overview',true);expect(wrapper.text()).toContain('管理员权限已变化');expect(revalidate).toHaveBeenCalledOnce()})
 it('revalidates and removes the console after an invitation mutation returns 403',async()=>{const {wrapper,revalidate}=await setup('invites');await wrapper.find('form').trigger('submit');await flushPromises();expect(wrapper.text()).toContain('管理员权限已变化');expect(revalidate).toHaveBeenCalledOnce()})
 it('removes feedback contents after a status mutation returns 403',async()=>{const {wrapper,revalidate}=await setup('feedback');await wrapper.findAll('button').find(b=>b.text()==='标记已解决')!.trigger('click');await flushPromises();expect(wrapper.text()).not.toContain('机密反馈');expect(revalidate).toHaveBeenCalledOnce()})
})
