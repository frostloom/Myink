import { render, fireEvent, screen, cleanup } from '@testing-library/vue'
import { afterEach, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import FeedbackWidget from './FeedbackWidget.vue'
import { createThemeScope, themeKey } from '../themeContext'
import { authKey } from '../authContext'
vi.mock('../../../src/lib/api',()=>({api:{submitFeedback:vi.fn(async()=>{throw new Error('offline')}),listFeedback:vi.fn(async()=>({items:[]}))},fetchFeedbackAttachment:vi.fn()}))
afterEach(cleanup)
it('opens from the shared feedback event and preserves a failed submission',async()=>{const router=createRouter({history:createMemoryHistory(),routes:[{path:'/long',component:{template:'<div />'}}]});await router.push('/long');render(FeedbackWidget,{global:{plugins:[router],provide:{[themeKey as symbol]:createThemeScope(),[authKey as symbol]:{session:ref({userId:'a',roleVerified:true}),status:ref('authenticated')}}}});window.dispatchEvent(new Event('myink:feedback'));const input=await screen.findByRole('textbox',{name:'问题描述'});await fireEvent.update(input,'保留这段反馈');await fireEvent.click(screen.getByRole('button',{name:'提交'}));expect(await screen.findByRole('alert')).toBeTruthy();expect((input as HTMLTextAreaElement).value).toBe('保留这段反馈')})
it('retains feedback typed while a previous submission is in flight',async()=>{
 const {api}=await import('../../../src/lib/api')
 let finish!:(result: Awaited<ReturnType<typeof api.submitFeedback>>)=>void
 vi.mocked(api.submitFeedback).mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/long',component:{template:'<div />'}}]});await router.push('/long')
 render(FeedbackWidget,{global:{plugins:[router],provide:{[themeKey as symbol]:createThemeScope(),[authKey as symbol]:{session:ref({userId:'a',roleVerified:true}),status:ref('authenticated')}}}})
 window.dispatchEvent(new Event('myink:feedback'))
 const input=await screen.findByRole('textbox',{name:'问题描述'})
 await fireEvent.update(input,'第一条反馈');await fireEvent.click(screen.getByRole('button',{name:'提交'}))
 await fireEvent.update(input,'提交中新增的内容')
 finish({id:'f',username:'a',category:'bug',description:'第一条反馈',contact:'',page_url:'/long',status:'open',attachments:[],created_at:''})
 await new Promise(resolve=>setTimeout(resolve,0))
 expect((screen.getByRole('textbox',{name:'问题描述'}) as HTMLTextAreaElement).value).toBe('提交中新增的内容')
})
it('protects in-memory feedback on browser unload',async()=>{
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/long',component:{template:'<div />'}}]});await router.push('/long')
 render(FeedbackWidget,{global:{plugins:[router],provide:{[themeKey as symbol]:createThemeScope(),[authKey as symbol]:{session:ref({userId:'a',roleVerified:true}),status:ref('authenticated')}}}})
 window.dispatchEvent(new Event('myink:feedback'));await fireEvent.update(await screen.findByRole('textbox',{name:'问题描述'}),'还没提交')
 const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event)
 expect(event.defaultPrevented).toBe(true)
})
