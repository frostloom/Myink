import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import FeedbackWidget from './components/FeedbackWidget.vue'
import AttachmentChip from './components/AttachmentChip.vue'
import { fetchFeedbackAttachment } from '../../src/lib/api'
import StyleLibraryPage from './pages/StyleLibraryPage.vue'
import { authKey } from './authContext'
import { createThemeScope, themeKey } from './themeContext'
import { LAMP_HANG } from '../../src/lib/theme'
import { styleLibraryApi } from '../../src/lib/styleLibraryApi'
vi.mock('../../src/lib/api', () => ({ api: { listProjects: vi.fn(async () => []), listFeedback: vi.fn(async () => ({items:[]})), submitFeedback: vi.fn() }, fetchFeedbackAttachment: vi.fn() }))
vi.mock('../../src/lib/styleLibraryApi', () => ({styleLibraryApi:{list:vi.fn(async()=>({items:[]}))}}))
afterEach(() => { cleanup(); vi.clearAllMocks(); document.body.style.overflow=''; localStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
async function mount(component: typeof FeedbackWidget | typeof StyleLibraryPage, guest=false) {
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div />'}}]});await router.push('/styles')
 const session=ref<{userId:string;token:string;roleVerified:boolean}|null>(guest ? null : {userId:'a',token:'old-token',roleVerified:true});const theme=createThemeScope()
 const view=render(component,{global:{plugins:[router],provide:{[authKey as symbol]:{session,status:ref(guest?'anonymous':'authenticated'),logout:vi.fn()},[themeKey as symbol]:theme},stubs:{ProjectRail:true}}})
 return {view,session,theme}
}
it('restores scrolling after closing feedback', async()=>{
 const removed=vi.spyOn(document,'removeEventListener');const added=vi.spyOn(document,'addEventListener')
 document.body.style.overflow='auto';const {view}=await mount(FeedbackWidget)
 window.dispatchEvent(new Event('myink:feedback'));await screen.findByRole('dialog')
 expect(document.body.style.overflow).toBe('hidden')
 expect(document.activeElement).toBe(screen.getByRole('button',{name:'关闭'}))
 await fireEvent.click(screen.getByRole('button',{name:'关闭'}))
 expect(document.body.style.overflow).toBe('auto')
 expect(document.activeElement).toBe(screen.getByRole('button',{name:'问题反馈'}))
 const keyHandler=added.mock.calls.find(([type])=>type==='keydown')?.[1]
 expect(removed).toHaveBeenCalledWith('keydown',keyHandler)
 window.dispatchEvent(new Event('myink:feedback'));await screen.findByRole('dialog')
 expect(document.body.style.overflow).toBe('hidden');view.unmount()
 expect(document.body.style.overflow).toBe('auto')
 expect(removed.mock.calls.filter(([type])=>type==='keydown')).toHaveLength(2)
})
it('updates lamp beam when theme preview changes', async()=>{
 const {theme}=await mount(FeedbackWidget)
 const button=screen.getByRole('button',{name:'问题反馈'})
 expect(button.parentElement!.style.getPropertyValue('--beam')).toBe('58%')
 for (const lamp of ['cone','shade','globe','cube'] as const) {
  theme.setLampPreview({lamp,light:true})
  await vi.waitFor(()=>expect(button.getAttribute('data-lamp')).toBe(lamp))
  const dock=button.parentElement!
  expect(dock.style.getPropertyValue('--beam')).toBe(LAMP_HANG[lamp].beam)
  expect(dock.style.getPropertyValue('--cord')).toBe(LAMP_HANG[lamp].cord)
  expect(dock.style.getPropertyValue('--span')).toBe(String(300-LAMP_HANG[lamp].top))
 }

})
it('uses a rotated same-account token for style retries', async()=>{
 vi.mocked(styleLibraryApi.list).mockRejectedValueOnce(new Error('offline')).mockResolvedValue({items:[]})
 const {session}=await mount(StyleLibraryPage)
 await screen.findByRole('button',{name:'重新加载'})
 session.value={...session.value!,token:'new-token'}
 await fireEvent.click(screen.getByRole('button',{name:'重新加载'}))
 expect(vi.mocked(styleLibraryApi.list).mock.lastCall?.[0]).toBe('new-token')
})
it('does not load protected style library for guests', async()=>{
 await mount(StyleLibraryPage,true)
 await Promise.resolve()
 expect(styleLibraryApi.list).not.toHaveBeenCalled()
})

it('does not publish an attachment response after its account UI unmounts',async()=>{
 let finish!:(blob:Blob)=>void
 vi.mocked(fetchFeedbackAttachment).mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 const tab={closed:false,opener:{},location:{href:''},close:vi.fn()}
 vi.spyOn(window,'open').mockReturnValue(tab as unknown as Window)
 const create=vi.fn(()=> 'blob:private-A');vi.stubGlobal('URL',{createObjectURL:create,revokeObjectURL:vi.fn()})
 const view=render(AttachmentChip,{props:{feedbackId:'a-private',attachment:{index:0,name:'private.png',mime:'image/png',bytes:10}}})
 await fireEvent.click(screen.getByRole('button',{name:/private.png/}))
 const signal=vi.mocked(fetchFeedbackAttachment).mock.lastCall?.[2]
 view.unmount();expect(signal?.aborted).toBe(true);expect(tab.close).toHaveBeenCalledTimes(1)
 finish(new Blob(['private account A bytes']))
 await vi.waitFor(()=>expect(tab.close).toHaveBeenCalled())
 expect(create).not.toHaveBeenCalled()
})

it('keeps a completed attachment tab usable after its UI is disposed',async()=>{
 vi.mocked(fetchFeedbackAttachment).mockResolvedValue(new Blob(['complete']))
 const tab={closed:false,opener:{},location:{href:''},close:vi.fn()}
 vi.spyOn(window,'open').mockReturnValue(tab as unknown as Window)
 const revoke=vi.fn();vi.stubGlobal('URL',{createObjectURL:vi.fn(()=> 'blob:complete'),revokeObjectURL:revoke})
 const view=render(AttachmentChip,{props:{feedbackId:'f',attachment:{index:0,name:'complete.png',mime:'image/png',bytes:10}}})
 await fireEvent.click(screen.getByRole('button',{name:/complete.png/}))
 expect(tab.location.href).toBe('blob:complete')
 view.unmount();expect(tab.close).not.toHaveBeenCalled();expect(revoke).not.toHaveBeenCalled()
})
