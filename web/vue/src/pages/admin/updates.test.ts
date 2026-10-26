import { flushPromises,mount } from '@vue/test-utils'
import { afterEach,beforeEach,describe,expect,it,vi } from 'vitest'
import { clearSession,setSession } from '../../../../src/lib/token'
import { ResourceUpdates,type ResourceUpdateGate } from './ResourceUpdates'
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => { setSession({ token:'test-token', userId:'u', username:'user', tier:'normal', role:'user', roleVerified:true, expiresAt:null }) })
afterEach(() => { wrappers.forEach(w=>w.unmount()); wrappers.length=0;clearSession();vi.unstubAllGlobals() })
const update = { resource_id:'r',name:'章节规则',kind:'writing_rule',current_version:1,target_version:2,target_generation:8,action:'publish',note:'更新',dismissed:false }
function setup(overridden=false, conflict=false) {
 const requests: Array<{url:string;body:unknown}> = []
 vi.stubGlobal('fetch', async (input: string, init?: RequestInit) => {
  const url=String(input);requests.push({url,body:init?.body?JSON.parse(String(init.body)):undefined})
  if(url.endsWith('/updates'))return new Response(JSON.stringify({items:[update]}),{status:200})
  if(url.endsWith('/adopt'))return new Response(JSON.stringify(conflict?{detail:'conflict'}:{revision:4,configured:true,selections:[]}),{status:conflict?409:200})
  return new Response(JSON.stringify({revision:3,configured:true,selections:overridden?[{resource_id:'r',personal_override:true}]:[]}),{status:200})
 })
 const wrapper=mount(ResourceUpdates,{props:{projectId:'p',autoOpen:false}});wrappers.push(wrapper)
 return {wrapper,requests,gate:wrapper.vm as unknown as ResourceUpdateGate}
}
describe('resource generation gate',()=>{
 it('exposes a generation check and excludes personal overrides',async()=>{
  const {wrapper,gate}=setup(true);await flushPromises()
  expect(typeof gate.beforeGenerate).toBe('function')
  expect(await gate.beforeGenerate()).toBe(true)
  expect(wrapper.find('dialog').exists()).toBe(false)
 })
 it('adopts a batch with snapshot revision and target generation',async()=>{
  const {wrapper,gate,requests}=setup();await flushPromises()
  const waiting=gate.beforeGenerate();await flushPromises()
  await wrapper.findAll('button').find(b=>b.text()==='采用勾选更新')!.trigger('click');await flushPromises()
  expect(await waiting).toBe(true)
  expect(requests.find(r=>r.url.endsWith('/adopt'))?.body).toEqual({expected_revision:3,updates:[{resource_id:'r',target_generation:8}]})
 })
 it('preserves selection and blocks continuation on atomic conflict',async()=>{
  const {wrapper,gate}=setup(false,true);await flushPromises()
  const waiting=gate.beforeGenerate();await flushPromises()
  await wrapper.findAll('button').find(b=>b.text()==='采用勾选更新')!.trigger('click');await flushPromises()
  expect(wrapper.text()).toContain('草稿已保留')
  expect(wrapper.find('input[type=checkbox]').element).toHaveProperty('checked',true)
  await wrapper.findAll('button').find(b=>b.text()==='取消本次生成')!.trigger('click')
  expect(await waiting).toBe(false)
 })
})
