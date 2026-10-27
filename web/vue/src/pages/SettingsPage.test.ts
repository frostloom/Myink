import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/vue'
import { ref } from 'vue'
import { createMemoryHistory, createRouter, type HistoryState } from 'vue-router'
import { api } from '../../../src/lib/api'
import { writingResources, type ResourceSnapshot } from '../../../src/lib/writingResources'
import SettingsPage from './SettingsPage.vue'
vi.mock('../authContext',()=>({useAuth:()=>({session:ref(null),status:ref('anonymous'),logout:vi.fn()})}))
vi.mock('../components/WritingResourcePicker.vue',()=>({default:{props:['projectId'],template:'<section>本书写作资源 {{projectId}}</section>'}}))
const settings={style_profile:{},skill_pack:null,genre_pack:{},model_routes:{},model_connections:[],version:1}
async function page(state?: HistoryState){vi.spyOn(api,'listProjects').mockResolvedValue([{id:'a',title:'A',target_words:1500},{id:'b',title:'B',target_words:6000}] as never);const router=createRouter({history:createMemoryHistory(),routes:[{path:'/projects/:projectId/settings',component:{template:'<div/>'}},{path:'/projects/:projectId',component:{template:'<div/>'}},{path:'/:pathMatch(.*)*',component:{template:'<div/>'}}]});await router.push({path:'/projects/a/settings',state});return{...render(SettingsPage,{global:{plugins:[router]}}),router}}
beforeEach(()=>{vi.spyOn(writingResources,'updates').mockResolvedValue({items:[]});vi.spyOn(writingResources,'snapshot').mockResolvedValue({revision:0,configured:false,selections:[]})})
afterEach(()=>{cleanup();vi.restoreAllMocks()})
it('keeps genre snapshots read only and validates and saves only target words',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue({...settings,genre_pack:{source_id:'fantasy',source_name:'奇幻',selling_point:'已发布卖点'}} as never);const save=vi.spyOn(api,'updateProject').mockResolvedValue({} as never);await page();await fireEvent.click(await screen.findByRole('button',{name:'查看 奇幻'}));expect(await within(screen.getByRole('dialog')).findByText('已发布卖点')).toBeTruthy();await fireEvent.click(screen.getByRole('button',{name:'关闭'}));expect(screen.queryByRole('textbox')).toBeNull();expect(screen.getByText('本书题材')).toBeTruthy();expect(screen.queryByText('文风档案')).toBeNull()
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

it('offers writing resources directly in creation settings', async () => {
 vi.spyOn(api,'getSettings').mockResolvedValue(settings)
 await page()
 expect(await screen.findByRole('heading',{name:'写作资源'})).toBeTruthy()
 expect(screen.queryByRole('link',{name:'查看本书写作资源'})).toBeNull()
})

const current:ResourceSnapshot={revision:7,configured:true,selections:[
 {origin:'platform',resource_id:'genre:g',kind:'genre',name:'当前奇幻',version:2,generation:3,personal_override:false,body:{catalog_id:'g',fields:{selling_point:'当前卖点',pacing:'缓急交错',subgenres:[{name:'迷城',hook:'失踪之谜'}],taboos:['不许机械降神'],satisfaction:['守护家园'],mechanics:['契约魔法'],world_hints:['古城生态']}}},
 {origin:'platform',resource_id:'style:s',kind:'style',name:'克制文风',version:1,generation:2,personal_override:false,body:{profile:{pov:'第三人称'}}},
 {origin:'platform',resource_id:'rule:r',kind:'writing_rule',name:'叙事规则',version:1,generation:2,personal_override:true,body:{roles:{writer:'保持因果'}}},
]}
it('shows all current genre details read only instead of the old creation genre',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue({...settings,genre_pack:{source_id:'old',source_name:'旧题材',selling_point:'旧卖点'}} as never)
 vi.mocked(writingResources.snapshot).mockResolvedValue(current)
 await page()
 expect(await screen.findByRole('heading',{name:'文风'})).toBeTruthy()
 expect(screen.queryByText('失踪之谜')).toBeNull()
 await fireEvent.click(screen.getByRole('button',{name:'查看 当前奇幻'}))
 expect(await within(screen.getByRole('dialog')).findByText('当前卖点')).toBeTruthy()
 for(const text of ['缓急交错','迷城','失踪之谜','不许机械降神','守护家园','契约魔法','古城生态'])expect(screen.getByText(text)).toBeTruthy()
 expect(screen.queryByText('旧卖点')).toBeNull()
 expect(screen.queryByRole('button',{name:'编辑 当前奇幻'})).toBeNull()
})
it('saves edited project content with revision CAS while preserving the other optional resources',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue(settings);vi.mocked(writingResources.snapshot).mockResolvedValue(current)
 const save=vi.spyOn(writingResources,'select').mockResolvedValue({...current,revision:8})
 await page();await fireEvent.click(await screen.findByRole('button',{name:'编辑 克制文风'}))
 await fireEvent.update(screen.getByLabelText('视角'),'第一人称')
 await fireEvent.click(screen.getByRole('button',{name:'保存本书资源'}))
 await vi.waitFor(()=>expect(save).toHaveBeenCalledWith('a',7,[
  {origin:'platform',resource_id:'style:s',personal_override:true,body:{profile:{pov:'第一人称'}}},
  {origin:'platform',resource_id:'rule:r',personal_override:true,body:{roles:{writer:'保持因果'}}},
 ]))
 expect(await screen.findByText('资源已保存，对后续新任务生效；历史章节和运行中的任务保持不变。')).toBeTruthy()
 expect(screen.queryByRole('dialog')).toBeNull()
})
it('retains edited content on revision conflict and keeps the dialog open',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue(settings);vi.mocked(writingResources.snapshot).mockResolvedValue(current)
 vi.spyOn(writingResources,'select').mockRejectedValue(Object.assign(new Error('SNAPSHOT_CHANGED'),{status:409}))
 await page();await fireEvent.click(await screen.findByRole('button',{name:'编辑 克制文风'}))
 await fireEvent.update(screen.getByLabelText('视角'),'我的未保存修改')
 await fireEvent.click(screen.getByRole('button',{name:'保存本书资源'}))
 expect(await within(screen.getByRole('dialog')).findByRole('alert')).toBeTruthy()
 expect((screen.getByLabelText('视角') as HTMLTextAreaElement).value).toBe('我的未保存修改')
})

it('selects optional resources in settings without sending automatic genre resources',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue(settings);vi.mocked(writingResources.snapshot).mockResolvedValue(current)
 vi.spyOn(writingResources,'catalogAll').mockResolvedValue({items:current.selections.map(item=>({id:item.resource_id,name:item.name,kind:item.kind,source:'platform',status:'published',generation:item.generation,current_version:item.version,body:item.body}))})
 vi.spyOn(writingResources,'personal').mockResolvedValue({items:[]})
 const save=vi.spyOn(writingResources,'select').mockResolvedValue({...current,revision:8})
 await page();await fireEvent.click(await screen.findByRole('button',{name:'调整资源选择'}))
 const checkbox=await screen.findByRole('checkbox',{name:'选用 克制文风'})
 expect((checkbox as HTMLInputElement).checked).toBe(true)
 expect(screen.queryByRole('checkbox',{name:'选用 当前奇幻'})).toBeNull()
 await fireEvent.click(checkbox)
 await fireEvent.click(screen.getByRole('button',{name:'保存资源选择'}))
 await vi.waitFor(()=>expect(save).toHaveBeenCalledWith('a',7,[{origin:'platform',resource_id:'rule:r',personal_override:true,body:{roles:{writer:'保持因果'}}}]))
})

it('does not apply a completed old-project resource save after switching books',async()=>{
 vi.spyOn(window,'confirm').mockReturnValue(true)
 vi.spyOn(api,'getSettings').mockResolvedValue(settings)
 vi.mocked(writingResources.snapshot).mockImplementation(id=>Promise.resolve(id==='a'?current:{revision:0,configured:false,selections:[]}))
 let finish!:(value:ResourceSnapshot)=>void
 vi.spyOn(writingResources,'select').mockReturnValue(new Promise(resolve=>{finish=resolve}))
 const {router}=await page();await fireEvent.click(await screen.findByRole('button',{name:'编辑 克制文风'}))
 await fireEvent.update(screen.getByLabelText('视角'),'旧书修改')
 await fireEvent.click(screen.getByRole('button',{name:'保存本书资源'}))
 await router.push('/projects/b/settings')
 await screen.findByText('尚未选用文风，可调整资源选择。')
 finish({...current,revision:8})
 await new Promise(resolve=>setTimeout(resolve,0))
 expect(screen.queryByRole('button',{name:'编辑 克制文风'})).toBeNull()
 expect(screen.queryByText('资源已保存，对后续新任务生效；历史章节和运行中的任务保持不变。')).toBeNull()
})
it('preserves the current platform book override when a different linked personal version exists',async()=>{
 const savedBook={...current,selections:current.selections.map(item=>item.resource_id==='style:s'?{...item,personal_override:true,body:{profile:{pov:'本书A'}}}:item)}
 vi.spyOn(api,'getSettings').mockResolvedValue(settings);vi.mocked(writingResources.snapshot).mockResolvedValue(savedBook)
 vi.spyOn(writingResources,'catalogAll').mockResolvedValue({items:current.selections.map(item=>({id:item.resource_id,name:item.name,kind:item.kind,source:'platform',status:'published',generation:item.generation,current_version:item.version,body:item.body}))})
 vi.spyOn(writingResources,'personal').mockResolvedValue({items:[{id:'personal-style',name:'个人B',kind:'style',source:'platform',status:'published',generation:1,current_version:1,source_resource_id:'style:s',source_generation:2,body:{profile:{pov:'个人B正文'}}}]})
 const save=vi.spyOn(writingResources,'select').mockResolvedValue({...savedBook,revision:8})
 await page();await fireEvent.click(await screen.findByRole('button',{name:'调整资源选择'}))
 await screen.findByRole('checkbox',{name:'选用 个人B'})
 expect((screen.getByRole('checkbox',{name:'选用 叙事规则'}) as HTMLInputElement).disabled).toBe(false)
 await fireEvent.click(screen.getByRole('button',{name:'保存资源选择'}))
 await vi.waitFor(()=>expect(save).toHaveBeenCalledWith('a',7,[{origin:'platform',resource_id:'style:s',personal_override:true,body:{profile:{pov:'本书A'}}},{origin:'platform',resource_id:'rule:r',personal_override:true,body:{roles:{writer:'保持因果'}}}]))
})
it('reloads a conflicted book edit only explicitly and saves again against the displayed new revision',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue(settings);vi.mocked(writingResources.snapshot).mockResolvedValue(current)
 const save=vi.spyOn(writingResources,'select').mockRejectedValueOnce(Object.assign(new Error('SNAPSHOT_CHANGED'),{status:409})).mockResolvedValue({...current,revision:9})
 await page();await fireEvent.click(await screen.findByRole('button',{name:'编辑 克制文风'}))
 await fireEvent.update(screen.getByLabelText('视角'),'未保存草稿')
 await fireEvent.click(screen.getByRole('button',{name:'保存本书资源'}))
 await screen.findByRole('alert')
 await fireEvent.click(screen.getByRole('button',{name:'重新载入最新版本'}))
 await fireEvent.click(screen.getByRole('button',{name:'保留当前修改'}))
 expect((screen.getByLabelText('视角') as HTMLTextAreaElement).value).toBe('未保存草稿')
 expect(writingResources.snapshot).toHaveBeenCalledTimes(2)
 vi.mocked(writingResources.snapshot).mockResolvedValue({...current,revision:8,selections:current.selections.map(item=>item.resource_id==='style:s'?{...item,body:{profile:{pov:'另一页已保存'}}}:item)})
 await fireEvent.click(screen.getByRole('button',{name:'重新载入最新版本'}))
 await fireEvent.click(screen.getByRole('button',{name:'放弃修改并重新载入'}))
 expect(await screen.findByDisplayValue('另一页已保存')).toBeTruthy()
 expect(save).toHaveBeenCalledTimes(1)
 await fireEvent.update(screen.getByLabelText('视角'),'基于最新版本编辑')
 await fireEvent.click(screen.getByRole('button',{name:'保存本书资源'}))
 await vi.waitFor(()=>expect(save).toHaveBeenLastCalledWith('a',8,expect.arrayContaining([{origin:'platform',resource_id:'style:s',personal_override:true,body:{profile:{pov:'基于最新版本编辑'}}}])))
})
it('reloads choice controls after a publication conflict even if the book revision did not change',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue(settings);vi.mocked(writingResources.snapshot).mockResolvedValue(current)
 vi.spyOn(writingResources,'catalogAll').mockResolvedValue({items:current.selections.map(item=>({id:item.resource_id,name:item.name,kind:item.kind,source:'platform',status:'published',generation:item.generation,current_version:item.version,body:item.body}))})
 vi.spyOn(writingResources,'personal').mockResolvedValue({items:[]})
 const save=vi.spyOn(writingResources,'select').mockRejectedValueOnce(Object.assign(new Error('RESOURCE_NOT_PUBLISHED'),{status:409})).mockResolvedValue({...current,revision:8})
 await page();await fireEvent.click(await screen.findByRole('button',{name:'调整资源选择'}))
 await screen.findByRole('checkbox',{name:'选用 克制文风'})
 await fireEvent.click(screen.getByRole('button',{name:'保存资源选择'}));await screen.findByRole('alert')
 await fireEvent.click(screen.getByRole('button',{name:'重新载入最新版本'}))
 await fireEvent.click(screen.getByRole('button',{name:'放弃修改并重新载入'}))
 await vi.waitFor(()=>expect((screen.getByRole('button',{name:'保存资源选择'}) as HTMLButtonElement).disabled).toBe(false))
 expect(save).toHaveBeenCalledTimes(1)
 await fireEvent.click(screen.getByRole('checkbox',{name:'选用 克制文风'}))
 await fireEvent.click(screen.getByRole('button',{name:'保存资源选择'}))
 await vi.waitFor(()=>expect(save).toHaveBeenLastCalledWith('a',7,[{origin:'platform',resource_id:'rule:r',personal_override:true,body:{roles:{writer:'保持因果'}}}]))
})
it('shows empty categories without falsely claiming the platform has no rules',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue(settings)
 await page()
 expect(await screen.findByText('尚未选用创作规则，可调整资源选择。')).toBeTruthy()
 expect(screen.getByText('尚未选用表达规则，可调整资源选择。')).toBeTruthy()
 expect(screen.queryByText('尚未选用可选写作资源，可从资源库添加。')).toBeNull()
})

it('keeps target words unavailable during initial loading and permits retry after failure', async () => {
 let reject!:(reason:Error)=>void
 vi.spyOn(api,'getSettings').mockImplementationOnce(()=>new Promise((_resolve,fail)=>{reject=fail})).mockResolvedValue(settings)
 await page()
 expect(screen.getByRole('status').textContent).toContain('正在加载创作设置')
 expect((screen.getByRole('spinbutton') as HTMLInputElement).disabled).toBe(true)
 reject(new Error('offline')); await screen.findByRole('alert')
 expect((screen.getByRole('spinbutton') as HTMLInputElement).disabled).toBe(true)
 await fireEvent.click(screen.getByRole('button',{name:'重新加载设置'}))
 await vi.waitFor(()=>expect((screen.getByRole('spinbutton') as HTMLInputElement).value).toBe('1500'))
 expect((screen.getByRole('spinbutton') as HTMLInputElement).disabled).toBe(false)
})

it('defers a late resource update prompt until the current editing dialog closes',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue(settings);vi.mocked(writingResources.snapshot).mockResolvedValue(current)
 let finish!:(value:Awaited<ReturnType<typeof writingResources.updates>>)=>void
 vi.mocked(writingResources.updates).mockReturnValue(new Promise(resolve=>{finish=resolve}))
 await page();await fireEvent.click(await screen.findByRole('button',{name:'编辑 克制文风'}))
 await fireEvent.update(screen.getByLabelText('视角'),'未保存的内容')
 finish({items:[{resource_id:'style:s',name:'克制文风',kind:'style',current_version:1,target_version:2,target_generation:3,action:'publish',note:'更新',dismissed:false}]})
 await vi.waitFor(()=>expect(writingResources.updates).toHaveBeenCalled())
 await new Promise(resolve=>setTimeout(resolve,0))
 expect(screen.getAllByRole('dialog')).toHaveLength(1)
 expect(screen.queryByRole('heading',{name:'写作资源更新'})).toBeNull()
 expect((screen.getByLabelText('视角') as HTMLTextAreaElement).value).toBe('未保存的内容')
 await fireEvent.click(screen.getByRole('button',{name:'取消'}))
 expect(await screen.findByRole('heading',{name:'写作资源更新'})).toBeTruthy()
})
it('applies explicitly edited chooser content over an older book override after fork conflict recovery',async()=>{
 vi.spyOn(api,'getSettings').mockResolvedValue(settings)
 const own={id:'own-rule',name:'我的叙事规则',kind:'writing_rule' as const,source:'platform',status:'published' as const,generation:2,current_version:2,source_resource_id:'rule:r',source_generation:2,body:{roles:{writer:'资源库当前内容'}}}
 const old={origin:'personal' as const,resource_id:own.id,name:own.name,kind:own.kind,version:1,generation:1,personal_override:true,body:{roles:{writer:'本书旧修改'}}}
 vi.mocked(writingResources.snapshot).mockResolvedValue({revision:7,configured:true,selections:[old]})
 vi.spyOn(writingResources,'catalogAll').mockResolvedValue({items:[{id:'rule:r',name:'平台叙事规则',kind:'writing_rule',source:'platform',status:'published',generation:2,current_version:2,body:{roles:{writer:'平台内容'}}}]})
 vi.spyOn(writingResources,'personal').mockResolvedValue({items:[own]})
 vi.spyOn(writingResources,'forkPersonal').mockRejectedValue(Object.assign(new Error('PERSONAL_RESOURCE_EXISTS'),{status:409}))
 vi.spyOn(writingResources,'savePersonal').mockResolvedValue({...own,generation:3,current_version:3,body:{roles:{writer:'本次明确编辑的新内容'}}})
 const save=vi.spyOn(writingResources,'select').mockResolvedValue({revision:8,configured:true,selections:[]})
 await page();await fireEvent.click(await screen.findByRole('button',{name:'调整资源选择'}))
 await fireEvent.click(await screen.findByRole('button',{name:'编辑 平台叙事规则'}))
 await fireEvent.click(screen.getByRole('button',{name:'保存为我的版本'}))
 await screen.findByRole('alert')
 await fireEvent.click(screen.getByRole('button',{name:'重新载入最新版本'}))
 await fireEvent.click(screen.getByRole('button',{name:'放弃修改并重新载入'}))
 await fireEvent.update(await screen.findByDisplayValue('资源库当前内容'),'本次明确编辑的新内容')
 await fireEvent.click(screen.getByRole('button',{name:'保存为我的版本'}))
 await vi.waitFor(()=>expect(screen.queryByRole('button',{name:'保存为我的版本'})).toBeNull())
 await fireEvent.click(screen.getByRole('button',{name:'保存资源选择'}))
 await vi.waitFor(()=>expect(save).toHaveBeenCalledWith('a',7,[{origin:'personal',resource_id:'own-rule',personal_override:true,body:{roles:{writer:'本次明确编辑的新内容'}}}]))
})
