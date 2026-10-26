import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { ref } from 'vue'
import { createMemoryHistory, createRouter, type HistoryState } from 'vue-router'
import { api } from '../../../src/lib/api'
import SettingsPage from './SettingsPage.vue'
vi.mock('../authContext',()=>({useAuth:()=>({session:ref(null),status:ref('anonymous'),logout:vi.fn()})}))
vi.mock('../components/WritingResourcePicker.vue',()=>({default:{props:['projectId'],template:'<section>本书写作资源 {{projectId}}</section>'}}))
const settings={style_profile:{},skill_pack:null,genre_pack:{},model_routes:{},model_connections:[],version:1}
async function page(state?: HistoryState){vi.spyOn(api,'listProjects').mockResolvedValue([{id:'a',title:'A',target_words:1500},{id:'b',title:'B',target_words:6000}] as never);const router=createRouter({history:createMemoryHistory(),routes:[{path:'/projects/:projectId/settings',component:{template:'<div/>'}},{path:'/projects/:projectId',component:{template:'<div/>'}},{path:'/:pathMatch(.*)*',component:{template:'<div/>'}}]});await router.push({path:'/projects/a/settings',state});return{...render(SettingsPage,{global:{plugins:[router]}}),router}}
afterEach(()=>{cleanup();vi.restoreAllMocks()})
it('keeps genre snapshots read only and validates and saves only target words',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue({...settings,genre_pack:{source_id:'fantasy',source_name:'奇幻',selling_point:'已发布卖点'}} as never);const save=vi.spyOn(api,'updateProject').mockResolvedValue({} as never);await page();expect(await screen.findByText('已发布卖点')).toBeTruthy();expect(screen.queryByRole('textbox')).toBeNull();expect(screen.getByText('本书题材')).toBeTruthy();expect(screen.queryByText('文风档案')).toBeNull()
 await fireEvent.update(screen.getByRole('spinbutton'),'200');await fireEvent.click(screen.getByRole('button',{name:'保存目标字数'}));expect(await screen.findByText('目标字数需为 500–20000 的整数')).toBeTruthy();expect(save).not.toHaveBeenCalled()
 await fireEvent.update(screen.getByRole('spinbutton'),'3000');await fireEvent.click(screen.getByRole('button',{name:'保存目标字数'}));expect(save).toHaveBeenCalledWith('a',{target_words:3000});expect(await screen.findByText('目标字数已保存，对新生成章节生效')).toBeTruthy()
})
it.each(['success','failure'])('ignores late A load %s after B navigation',async outcome=>{
 let finish!:(s:typeof settings)=>void,fail!:(e:Error)=>void;vi.spyOn(api,'getSettings').mockImplementation(id=>id==='a'?new Promise((res,rej)=>{finish=res;fail=rej}):Promise.resolve(settings));const save=vi.spyOn(api,'updateProject').mockResolvedValue({} as never)
 const {router}=await page();await router.push('/projects/b/settings');await vi.waitFor(()=>expect((screen.getByRole('spinbutton') as HTMLInputElement).value).toBe('6000'));if(outcome==='success')finish(settings);else fail(new Error('old load failure'));await fireEvent.click(screen.getByRole('button',{name:'保存目标字数'}));expect(save).toHaveBeenCalledWith('b',{target_words:6000});expect(screen.queryByText('old load failure')).toBeNull()
})
it('isolates old save rejection from B busy state',async()=>{
 let fail!:(e:Error)=>void;vi.spyOn(api,'getSettings').mockResolvedValue(settings);vi.spyOn(api,'updateProject').mockImplementation(id=>id==='a'?new Promise((_res,rej)=>{fail=rej}):new Promise(()=>{}));const{router}=await page();await vi.waitFor(()=>expect((screen.getByRole('spinbutton') as HTMLInputElement).value).toBe('1500'));await fireEvent.click(screen.getByRole('button',{name:'保存目标字数'}));await router.push('/projects/b/settings');await vi.waitFor(()=>expect((screen.getByRole('spinbutton') as HTMLInputElement).value).toBe('6000'));await fireEvent.click(screen.getByRole('button',{name:'保存目标字数'}));fail(new Error('old save failure'));await vi.waitFor(()=>expect((screen.getByRole('button',{name:'保存中…'}) as HTMLButtonElement).disabled).toBe(true));expect(screen.queryByText('old save failure')).toBeNull()
})

it('keeps the plan warning in actual return navigation history and requires manual writing start',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue(settings)
 const {router}=await page({configureBeforeWriting:true,planWarning:'计划需要人工检查'})
 expect(screen.getByText(/正文尚未开始生成/)).toBeTruthy()
 await fireEvent.click(screen.getByRole('link',{name:'选好后返回工作台开写'}))
 await vi.waitFor(()=>expect(router.currentRoute.value.path).toBe('/projects/a'))
 expect(router.options.history.state.planWarning).toBe('计划需要人工检查')
 expect(router.options.history.state.beginShortWriting).toBeUndefined()
})
it('refreshes return warning and configure message when the same settings instance changes project',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue(settings)
 const {router}=await page({configureBeforeWriting:true,planWarning:'A的警告'})
 expect(screen.getByText('A的警告')).toBeTruthy()
 await router.push({path:'/projects/b/settings',state:{configureBeforeWriting:false,planWarning:'B的警告'}})
 await vi.waitFor(()=>expect(screen.queryByText(/正文尚未开始生成/)).toBeNull())
 await fireEvent.click(screen.getByRole('link',{name:'返回工作台'}))
 await vi.waitFor(()=>expect(router.currentRoute.value.path).toBe('/projects/b'))
 expect(router.options.history.state.planWarning).toBe('B的警告')
})
