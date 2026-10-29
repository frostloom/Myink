import { flushPromises,mount } from '@vue/test-utils'
import { afterEach,beforeEach,describe,expect,it,vi } from 'vitest'
import { clearSession,setSession } from '../../../../src/lib/token'
import { ResourceUpdates,type ResourceUpdateGate } from './ResourceUpdates'
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => { sessionStorage.clear();setSession({ token:'test-token', userId:'u', username:'user', tier:'normal', role:'user', roleVerified:true, expiresAt:null }) })
afterEach(() => { wrappers.forEach(w=>w.unmount()); wrappers.length=0;clearSession();vi.unstubAllGlobals() })
const update = { resource_id:'r',name:'章节规则',kind:'writing_rule',current_version:1,target_version:2,target_generation:8,action:'publish',note:'更新',dismissed:false }
function setup(overridden=false, conflict=false) {
 const requests: Array<{url:string;body:unknown}> = []
 vi.stubGlobal('fetch', async (input: string, init?: RequestInit) => {
  const url=String(input);requests.push({url,body:init?.body?JSON.parse(String(init.body)):undefined})
  if(url.endsWith('/updates'))return new Response(JSON.stringify({items:[update]}),{status:200})
  if(url.endsWith('/adopt'))return new Response(JSON.stringify(conflict?{detail:'conflict'}:{revision:4,configured:true,selections:[]}),{status:conflict?409:200})
  return new Response(JSON.stringify({revision:3,configured:true,selections:[{origin:'platform',resource_id:'r',generation:7,personal_override:overridden}]}),{status:200})
 })
 const wrapper=mount(ResourceUpdates,{props:{projectId:'p',autoOpen:false}});wrappers.push(wrapper)
 return {wrapper,requests,gate:wrapper.vm as unknown as ResourceUpdateGate}
}
describe('resource generation gate',()=>{
 it('offers platform updates for personal overrides without preselecting or replacing them',async()=>{
  const {wrapper,gate,requests}=setup(true);await flushPromises()
  const waiting=gate.beforeGenerate();await flushPromises()
  expect(wrapper.find('dialog').exists()).toBe(true)
  expect(wrapper.text()).toContain('采用将覆盖本书个人修改')
  expect(wrapper.find('input[type=checkbox]').element).toHaveProperty('checked',false)
  expect(requests.some(request=>request.url.endsWith('/adopt'))).toBe(false)
  await wrapper.find('input[type=checkbox]').setValue(true)
  await wrapper.findAll('button').find(b=>b.text()==='采用勾选更新')!.trigger('click');await flushPromises()
  expect(await waiting).toBe(true)
  expect(requests.find(request=>request.url.endsWith('/adopt'))?.body).toEqual({expected_revision:3,updates:[{resource_id:'r',target_generation:8}]})
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

it('automatically checks without a manual entry and only prompts for real versions',async()=>{
 const {wrapper}=setup();await wrapper.setProps({autoOpen:true});await flushPromises()
 expect(wrapper.text()).not.toContain('查看资源更新')
 expect(wrapper.find('dialog').exists()).toBe(true)
})
it('keeps declined generations quiet even when dismissal fails',async()=>{
 const {wrapper,gate}=setup();await wrapper.setProps({autoOpen:true});await flushPromises()
 const original=globalThis.fetch
 vi.stubGlobal('fetch',(input:string,init?:RequestInit)=>String(input).endsWith('/dismiss')?Promise.reject(new Error('offline')):original(input,init))
 await wrapper.findAll('button').find(b=>b.text()==='暂不更新')!.trigger('click');await flushPromises()
 expect(wrapper.find('dialog').exists()).toBe(false)
 const next=gate.beforeGenerate();await flushPromises()
 expect(wrapper.find('dialog').exists()).toBe(false)
 expect(await next).toBe(true)
})
it('does not open an update prompt on a failed automatic check',async()=>{
 vi.stubGlobal('fetch',async()=>{throw new Error('offline')})
 const wrapper=mount(ResourceUpdates,{props:{projectId:'offline'}});wrappers.push(wrapper);await flushPromises()
 expect(wrapper.find('dialog').exists()).toBe(false)
})
it('does not prompt for a publication already present in the snapshot',async()=>{
 const {wrapper}=setup();await flushPromises()
 const original=globalThis.fetch
 vi.stubGlobal('fetch',(input:string,init?:RequestInit)=>String(input).endsWith('/updates')?Promise.resolve(new Response(JSON.stringify({items:[{...update,target_generation:7}]}))):original(input,init))
 await wrapper.setProps({autoOpen:true});await flushPromises()
 expect(wrapper.find('dialog').exists()).toBe(false)
})
it('prompts again for a newer generation after declining the prior one, including rollback',async()=>{
 const {wrapper,gate}=setup();await wrapper.setProps({autoOpen:true});await flushPromises()
 await wrapper.findAll('button').find(b=>b.text()==='暂不更新')!.trigger('click');await flushPromises()
 const original=globalThis.fetch
 vi.stubGlobal('fetch',(input:string,init?:RequestInit)=>String(input).endsWith('/updates')?Promise.resolve(new Response(JSON.stringify({items:[{...update,target_version:1,target_generation:9,action:'rollback'}]}))):original(input,init))
 const waiting=gate.beforeGenerate();await flushPromises()
 expect(wrapper.find('dialog').exists()).toBe(true)
 expect(wrapper.text()).toContain('管理员回退')
 await wrapper.findAll('button').find(b=>b.text()==='继续使用当前快照')!.trigger('click')
 expect(await waiting).toBe(true)
})
it('remembers a declined generation across component remounts in the same session',async()=>{
 const first=setup();await first.wrapper.setProps({autoOpen:true});await flushPromises()
 await first.wrapper.findAll('button').find(b=>b.text()==='暂不更新')!.trigger('click');await flushPromises();first.wrapper.unmount()
 const second=setup();await second.wrapper.setProps({autoOpen:true});await flushPromises()
 expect(second.wrapper.find('dialog').exists()).toBe(false)
})

it('waits for the initial automatic check before allowing the first generation',async()=>{
 let finish!:(value:Response)=>void
 vi.stubGlobal('fetch',(input:string)=>String(input).endsWith('/updates')?new Promise<Response>(resolve=>{finish=resolve}):Promise.resolve(new Response(JSON.stringify({revision:1,configured:true,selections:[]}))))
 const wrapper=mount(ResourceUpdates,{props:{projectId:'initial'}});wrappers.push(wrapper)
 const gate=wrapper.vm as unknown as ResourceUpdateGate
 let result:boolean|undefined
 const first=gate.beforeGenerate().then(value=>{result=value;return value})
 await flushPromises()
 expect(result).toBeUndefined()
 expect(await gate.beforeGenerate()).toBe(false)
 finish(new Response(JSON.stringify({items:[]})));await flushPromises()
 expect(await first).toBe(true)
})
it('offers updates to selected personal resources using personal-source wording',async()=>{
 const {wrapper,gate,requests}=setup();await flushPromises()
 const original=globalThis.fetch
 vi.stubGlobal('fetch',(input:string,init?:RequestInit)=>String(input).endsWith('/writing-resources')?Promise.resolve(new Response(JSON.stringify({revision:3,configured:true,selections:[{origin:'personal',resource_id:'r',generation:7,personal_override:false}]}))):original(input,init))
 const waiting=gate.beforeGenerate();await flushPromises()
 expect(wrapper.find('dialog').exists()).toBe(true)
 expect(wrapper.text()).toContain('个人资源更新')
 expect(wrapper.text()).not.toContain('管理员发布了资源更新')
 await wrapper.findAll('button').find(b=>b.text()==='采用勾选更新')!.trigger('click');await flushPromises()
 expect(await waiting).toBe(true)
 expect(requests.find(request=>request.url.endsWith('/adopt'))?.body).toEqual({expected_revision:3,updates:[{resource_id:'r',target_generation:8}]})
})
