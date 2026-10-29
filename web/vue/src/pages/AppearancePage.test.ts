import { render, fireEvent, screen, cleanup } from '@testing-library/vue'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import AppearancePage from './AppearancePage.vue'
import { createThemeScope, themeKey } from '../themeContext'
import { authKey } from '../authContext'
import { ref } from 'vue'
vi.mock('../../../src/lib/api', () => ({ api: { listProjects: vi.fn(async () => []) } }))
afterEach(cleanup)
beforeEach(() => localStorage.clear())
async function mountPage() { const theme = createThemeScope(); const router = createRouter({ history:createMemoryHistory(), routes:[{path:'/appearance', component:AppearancePage},{path:'/long',component:{template:'<div />'}}] }); await router.push('/appearance'); await router.isReady(); render({template:'<router-view />'}, { global: { plugins:[router], provide: { [themeKey as symbol]:theme, [authKey as symbol]:{session:ref(null),status:ref('anonymous'),logout:vi.fn()} }, stubs:{ProjectRail:true} } }); return theme }
it('offers official themes and only applies a selected theme after confirmation', async () => { const theme=await mountPage(); const buttons=screen.getAllByRole('button'); expect(buttons.length).toBeGreaterThan(4); await fireEvent.click(screen.getByRole('button',{name:'新建自定义'})); expect(screen.getByRole('textbox',{name:'名称'})).toBeTruthy(); expect(theme.presets.value).toHaveLength(0) })
it('keeps a changed preset as a draft until 保存这套', async () => { const theme=await mountPage(); await fireEvent.click(screen.getByRole('button',{name:'新建自定义'})); await fireEvent.update(screen.getByRole('textbox',{name:'名称'}),'测试配色'); expect(theme.presets.value).toHaveLength(0); await fireEvent.click(screen.getByRole('button',{name:'保存这套'})); expect(theme.presets.value[0]?.name).toBe('测试配色') })
it('asks before dropping dirty drafts and cancel preserves the name', async () => { await mountPage(); await fireEvent.click(screen.getByRole('button',{name:'新建自定义'})); await fireEvent.update(screen.getByRole('textbox',{name:'名称'}),'未保存'); await fireEvent.click(screen.getByRole('button',{name:'收起'})); expect(screen.getByRole('dialog')).toBeTruthy(); await fireEvent.click(screen.getByRole('button',{name:'取消'})); expect((screen.getByRole('textbox',{name:'名称'}) as HTMLInputElement).value).toBe('未保存') })
it('fits each workspace preview after its DOM frame has mounted', async () => {
 const observe=vi.fn();const disconnect=vi.fn()
 vi.stubGlobal('ResizeObserver',class {observe=observe;disconnect=disconnect})
 await mountPage()
 expect(observe).toHaveBeenCalledTimes(3)
 cleanup();expect(disconnect).toHaveBeenCalledTimes(3)
 vi.unstubAllGlobals()
})
it('protects unsaved theme changes against browser unload',async()=>{
 await mountPage();await fireEvent.click(screen.getByRole('button',{name:'楷体'}))
 const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event)
 expect(event.defaultPrevented).toBe(true)
})
it('keeps edits made while a wallpaper save is pending',async()=>{
 const media=await import('../../../src/lib/themeImage');let finish!:()=>void
 vi.spyOn(media,'writeWallpaper').mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 URL.createObjectURL=vi.fn(()=> 'blob:draft');URL.revokeObjectURL=vi.fn()
 await mountPage();await fireEvent.click(screen.getByRole('button',{name:'新建自定义'}))
 await fireEvent.update(screen.getByRole('textbox',{name:'名称'}),'已提交的名字')
 await fireEvent.change(screen.getByLabelText('上传背景'),{target:{files:[new File(['x'],'x.png',{type:'image/png'})]}})
 await fireEvent.click(screen.getByRole('button',{name:'保存这套'}))
 await fireEvent.update(screen.getByRole('textbox',{name:'名称'}),'保存中新增的名字');finish()
 await new Promise(resolve=>setTimeout(resolve,0))
 expect((screen.getByRole('textbox',{name:'名称'}) as HTMLInputElement).value).toBe('保存中新增的名字')
})
