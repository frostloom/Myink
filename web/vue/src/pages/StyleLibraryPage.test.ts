import { render, screen, cleanup } from '@testing-library/vue'
import { afterEach, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import StyleLibraryPage from './StyleLibraryPage.vue'
import { authKey } from '../authContext'
import { styleLibraryApi } from '../../../src/lib/styleLibraryApi'
vi.mock('../../../src/lib/api',()=>({api:{listProjects:vi.fn(async()=>[])}}))
vi.mock('../../../src/lib/styleLibraryApi',()=>({styleLibraryApi:{extract:vi.fn(),save:vi.fn(),list:vi.fn(async()=>({items:[{id:'builtin',name:'内置文风',note:'',builtin:true,profile:{pov:'第三人称',unknown_metric:{value:4}}}]}))}}))
afterEach(cleanup)
it('shows the style library catalogue',async()=>{const router=createRouter({history:createMemoryHistory(),routes:[{path:'/styles',component:StyleLibraryPage},{path:'/long',component:{template:'<div />'}}]});await router.push('/styles');render({template:'<router-view />'},{global:{plugins:[router],provide:{[authKey as symbol]:{session:ref({userId:'a',token:'tok'}),status:ref('authenticated'),logout:vi.fn()}},stubs:{ProjectRail:true}}});expect(await screen.findByRole('heading',{name:'文风库'})).toBeTruthy();expect(await screen.findByRole('button',{name:'内置文风'})).toBeTruthy()})
it('protects an unsaved extracted style sample against browser unload',async()=>{
 const {fireEvent}=await import('@testing-library/vue')
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/styles',component:StyleLibraryPage},{path:'/long',component:{template:'<div />'}}]});await router.push('/styles')
 render({template:'<router-view />'},{global:{plugins:[router],provide:{[authKey as symbol]:{session:ref({userId:'a',token:'tok'}),status:ref('authenticated'),logout:vi.fn()}},stubs:{ProjectRail:true}}})
 await fireEvent.click(await screen.findByRole('button',{name:'新建文风'}));await fireEvent.update(screen.getByRole('textbox',{name:'粘贴文章'}),'尚未保存的文风样本')
 const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);expect(event.defaultPrevented).toBe(true)
})

it('preserves extracted style list edits after native change and blur when saving', async()=>{
 const {fireEvent,waitFor}=await import('@testing-library/vue')
 vi.mocked(styleLibraryApi.extract).mockResolvedValue({draft:{pov:'第三人称',forbidden:['旧表达']}})
 vi.mocked(styleLibraryApi.save).mockResolvedValue({id:'saved',name:'修订文风',profile:{pov:'第三人称',forbidden:['第一条','第二条']},note:'',sample_chars:4,created_at:null,builtin:false,removable:true})
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/styles',component:StyleLibraryPage},{path:'/long',component:{template:'<div />'}}]});await router.push('/styles')
 render({template:'<router-view />'},{global:{plugins:[router],provide:{[authKey as symbol]:{session:ref({userId:'a',token:'tok'}),status:ref('authenticated'),logout:vi.fn()}},stubs:{ProjectRail:true}}})
 await fireEvent.click(await screen.findByRole('button',{name:'新建文风'}))
 await fireEvent.input(screen.getByRole('textbox',{name:'粘贴文章'}),{target:{value:'文风样本'}})
 await fireEvent.click(screen.getByRole('button',{name:'提取文风'}))
 const field=await screen.findByRole('textbox',{name:'禁用表达（每行一条）'})
 await fireEvent.input(field,{target:{value:'第一条\n第二条'}})
 await fireEvent.change(field);await fireEvent.blur(field)
 expect((screen.getByRole('textbox',{name:'禁用表达（每行一条）'}) as HTMLTextAreaElement).value).toBe('第一条\n第二条')
 await fireEvent.input(screen.getByRole('textbox',{name:'文风名'}),{target:{value:'修订文风'}})
 await fireEvent.click(screen.getByRole('button',{name:'保存文风'}))
 await waitFor(()=>expect(styleLibraryApi.save).toHaveBeenCalledTimes(1))
 expect(vi.mocked(styleLibraryApi.save).mock.calls[0][1].profile.forbidden).toEqual(['第一条','第二条'])
})
