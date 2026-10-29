import { flushPromises,mount } from '@vue/test-utils'
import { afterEach,beforeEach,describe,expect,it,vi } from 'vitest'
import { clearSession,setSession } from '../../../../src/lib/token'
import WritingResourcePicker from '../../components/WritingResourcePicker.vue'
const wrappers:ReturnType<typeof mount>[]=[]
const item={id:'rule',kind:'writing_rule',name:'创作规则',source:'内置',status:'published',generation:3,current_version:1,body:{roles:{writer:'保留悬念'},future_field:{keep:true}}}
beforeEach(()=>setSession({token:'test-token',userId:'u',username:'user',tier:'normal',role:'user',roleVerified:true,expiresAt:null}))
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers.length=0;clearSession();vi.unstubAllGlobals()})
async function setup(conflict=false){
 const requests:Array<{url:string;method:string;body:unknown}>=[]
 vi.stubGlobal('fetch',async(input:string,init?:RequestInit)=>{
  const url=String(input),method=init?.method??'GET';requests.push({url,method,body:init?.body?JSON.parse(String(init.body)):undefined})
  let body:unknown={revision:5,configured:true,selections:[]};let status=200
  if(url.endsWith('/updates'))body={items:[]}
  else if(url.endsWith('/my-writing-resources'))body=method==='POST'?{...item,id:'own',name:'我的规则'}:{items:[]}
  else if(url.endsWith('/writing-resources')&&!url.includes('/projects/'))body={items:[item]}
  else if(method==='PUT'&&conflict){status=409;body={detail:'conflict'}}
  return new Response(JSON.stringify(body),{status})
 })
 const wrapper=mount(WritingResourcePicker,{props:{projectId:'book'}});wrappers.push(wrapper);await flushPromises();return {wrapper,requests}
}
describe('project resource picker through real API wrappers',()=>{
 it('saves the selected identities with expected snapshot revision',async()=>{
  const {wrapper,requests}=await setup();await wrapper.find('input[type=checkbox]').setValue(true)
  await wrapper.findAll('button').find(b=>b.text()==='保存本书资源选择')!.trigger('click');await flushPromises()
  expect(requests.find(r=>r.method==='PUT')?.body).toEqual({expected_revision:5,selections:[{origin:'platform',resource_id:'rule'}]})
 })
 it('keeps the selected draft when the server rejects an atomic save',async()=>{
  const {wrapper}=await setup(true);await wrapper.find('input[type=checkbox]').setValue(true)
  await wrapper.findAll('button').find(b=>b.text()==='保存本书资源选择')!.trigger('click');await flushPromises()
  expect(wrapper.text()).toContain('草稿已保留');expect(wrapper.find('input[type=checkbox]').element).toHaveProperty('checked',true)
 })
 it('copies creative changes to the personal library while preserving unknown fields',async()=>{
  const {wrapper,requests}=await setup();await wrapper.findAll('button').find(b=>b.text()==='复制到个人资源 创作规则')!.trigger('click')
  await wrapper.find('dialog textarea').setValue('新规则')
  await wrapper.findAll('button').find(b=>b.text()==='保存个人资源')!.trigger('click');await flushPromises()
  const saved=requests.find(r=>r.method==='POST'&&r.url.endsWith('/my-writing-resources'))
  expect(saved?.body).toEqual({kind:'writing_rule',name:'创作规则',source:'内置',body:{...item.body,roles:{writer:'新规则'}}})
  expect(requests.some(r=>r.url.includes('/admin/'))).toBe(false)
 })
})
