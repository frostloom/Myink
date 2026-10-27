// @vitest-environment jsdom
/* eslint-disable vue/one-component-per-file -- test boundary components */
import { defineComponent, h, ref } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '../workspaceTestUtils'
import { createMemoryRouter, RouterProvider } from '../workspaceRouterTestUtils'
import { api } from '../../../src/lib/api'
import { openSSE, type SSEEvent } from '../../../src/lib/sse'
import type { TaskDetail, TaskSummary, ChapterMeta, GenerateResponse } from '../../../src/types'
import WorkspacePage from './WorkspacePage.vue'
vi.mock('../authContext', () => ({ useAuth: () => ({logout: vi.fn(), session: ref({userId:'restore-user'})}) }))
vi.mock('../components/ProjectRail.vue', () => ({default:defineComponent({setup:(_, {slots})=>()=>h('div',slots['resource-actions']?.())})}))
vi.mock('../components/ResourceUpdates.vue', () => ({default:defineComponent({setup:(_, {expose})=>{expose({beforeGenerate:async()=>true});return ()=>h('span','资源版本提示')}})}))
vi.mock('../components/LessonsPanel.vue',()=>({default:()=>null}))
vi.mock('../components/GenerationPanel.vue',()=>({default:()=>null}))
vi.mock('../components/AuditPanel.vue',()=>({default:()=>null}))
vi.mock('../components/CandidatePanel.vue',()=>({default:()=>null}))
vi.mock('../../../src/lib/sse', async original => ({...await original<typeof import('../../../src/lib/sse')>(),openSSE:vi.fn()}))
vi.mock('../../../src/lib/api', async original => ({...await original<typeof import('../../../src/lib/api')>(),api:{listProjects:vi.fn(),listChapters:vi.fn(),listCandidates:vi.fn(),listGraph:vi.fn(),listForeshadows:vi.fn(),listTasks:vi.fn(),getTask:vi.fn(),generateShort:vi.fn(),getChapter:vi.fn()}}))
afterEach(()=>{cleanup();vi.resetAllMocks();sessionStorage.clear()})
const detail:TaskDetail={task_id:'short-live',task_type:'short_generate',status:'running',chapter_seq:null,cost_total:0,error:null,created_at:null,payload:{},retry_count:0,trace_id:null,batch_task_id:null,runs:[]}
const summary:TaskSummary={...detail,batch_size:null,batch_current:null}
function setup(){
 vi.mocked(api.listProjects).mockResolvedValue([{id:'short',title:'短篇',form:'short',genre:'其他',current_chapter:0,target_words:2000}])
 vi.mocked(api.listChapters).mockResolvedValue([]);vi.mocked(api.listCandidates).mockResolvedValue([]);vi.mocked(api.listGraph).mockResolvedValue({nodes:[],edges:[]});vi.mocked(api.listForeshadows).mockResolvedValue([])
 vi.mocked(api.listTasks).mockResolvedValue([]);vi.mocked(api.getTask).mockResolvedValue(detail);vi.mocked(api.generateShort).mockResolvedValue({task_id:'short-live',status:'queued',trace_id:'trace'})
 const streams:Array<{signal?:AbortSignal;receive:(ev:SSEEvent)=>void;finish:()=>void}>=[]
 vi.mocked(openSSE).mockImplementation((_url,receive,options)=>new Promise(resolve=>{streams.push({signal:options?.signal,receive,finish:()=>resolve({reason:'terminal'})})}))
 const router=createMemoryRouter([{path:'/projects/:projectId',element:h(WorkspacePage)},{path:'/away',element:h('p','其他页面')}],{initialEntries:['/projects/short']})
 render(h(RouterProvider,{router}))
 return {router,streams}
}
const progress=(done:number):SSEEvent=>({type:'progress',task_id:'short-live',node:'',status:'running',message:'',stage:'short_write',chapter_seq:0,attempt:0,offset:0,done,total:100,artifact_id:'',content:'',artifact:''})
it('reconnects the accepted short task after leaving before its database history exists and loads completed chapters',async()=>{
 const {router,streams}=setup()
 await fireEvent.click(await screen.findByRole('button',{name:'开始写'}))
 await waitFor(()=>expect(streams.length).toBe(1))
 await act(async()=>streams[0].receive(progress(20)))
 expect(screen.getByRole('progressbar',{name:'短篇写作进度'}).getAttribute('aria-valuenow')).toBe('14')
 await act(async()=>{await router.navigate('/away')})
 expect(streams[0].signal?.aborted).toBe(true)
 await act(async()=>{await router.navigate('/projects/short')})
 await waitFor(()=>expect(streams.length).toBe(2))
 expect(screen.queryByRole('button',{name:'开始写'})).toBeNull()
 await act(async()=>streams[1].receive(progress(65)))
 expect(screen.getByRole('progressbar',{name:'短篇写作进度'}).getAttribute('aria-valuenow')).toBe('46')
 expect(api.generateShort).toHaveBeenCalledTimes(1)
 const chapter:ChapterMeta={id:'finished',chapter_seq:1,title:'完成章节',status:'confirmed',word_count:4,summary:null}
 vi.mocked(api.listChapters).mockResolvedValue([chapter]);vi.mocked(api.getChapter).mockResolvedValue({...chapter,version:1,content:'最终短篇正文'})
 vi.mocked(api.getTask).mockResolvedValue({...detail,status:'done'})
 await act(async()=>streams[1].finish())
 expect((await screen.findByLabelText('章节正文') as HTMLTextAreaElement).value).toBe('最终短篇正文')
})
it('does not mount resource version prompts inside a short book',async()=>{
 setup();await screen.findByRole('button',{name:'开始写'})
 expect(screen.queryByText('资源版本提示')).toBeNull()
})
it('recovers the active server short task instead of a newer completed historical task',async()=>{
 const {streams}=setup()
 vi.mocked(api.listTasks).mockResolvedValue([{...summary,task_id:'old-result',status:'done'},summary])
 await waitFor(()=>expect(streams.length).toBeGreaterThan(0))
 expect(vi.mocked(openSSE).mock.calls.at(-1)?.[0]).toBe('/api/v1/tasks/short-live/events')
})
it('remembers an accepted submission that resolves after the workspace unmounts',async()=>{
 const {router,streams}=setup()
 let accept!:(response:GenerateResponse)=>void
 vi.mocked(api.generateShort).mockImplementation(()=>new Promise(resolve=>{accept=resolve}))
 await fireEvent.click(await screen.findByRole('button',{name:'开始写'}))
 await act(async()=>{await router.navigate('/away')})
 await act(async()=>accept({task_id:'short-live',status:'queued',trace_id:'trace'}))
 await act(async()=>{await router.navigate('/projects/short')})
 await waitFor(()=>expect(streams.length).toBe(1))
 expect(screen.queryByRole('button',{name:'开始写'})).toBeNull()
 expect(api.generateShort).toHaveBeenCalledTimes(1)
})
