import { h, ref } from 'vue'

// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '../workspaceTestUtils';
import { createMemoryRouter, RouterProvider } from '../workspaceRouterTestUtils';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../../../src/lib/api';
import { openSSE, type SSEEvent } from '../../../src/lib/sse';
import type { ChapterMeta, TaskDetail, TaskSummary } from '../../../src/types';
import WorkspacePage from './WorkspacePage.vue';
vi.mock('../../../src/lib/writingResources', async (original) => ({
    ...await original<typeof import('../../../src/lib/writingResources')>(),
    writingResources: {
        updates: async () => ({ items: [] }),
        snapshot: async () => ({ revision: 0, configured: false, selections: [] }),
    },
}));
vi.mock('../authContext', () => ({
    useAuth: () => ({ logout: vi.fn(), session: ref(null) }),
}));
vi.mock('../components/ProjectRail.vue', () => ({ default: () => h("div", {}, []) }));
vi.mock('../components/LessonsPanel.vue', () => ({ default: () => h("div", {}, []) }));
vi.mock('../components/AuditPanel.vue', () => ({ default: () => h("div", {}, []) }));
vi.mock('../components/CandidatePanel.vue', () => ({ default: (props: {onReleased:(id:string,seq:number,batch:undefined,action:'revise')=>void}) => h('button',{onClick:()=>props.onReleased('t',1,undefined,'revise')},'开始修订') }));
vi.mock('../components/GenerationPanel.vue', () => ({ default: (props:{onTaskStart:(id:string,total:undefined,seq:number,mode?:'auto',intent?:'rewrite')=>void}) => h('div',{},[h('button',{onClick:()=>props.onTaskStart('new-task',undefined,1)},'启动新任务'),h('button',{onClick:()=>props.onTaskStart('new-task',undefined,1,'auto','rewrite')},'重写保留计划')]) }));
vi.mock('../components/TaskTimeline.vue', () => ({ default: () => h("div", {}, []) }));
vi.mock('../../../src/lib/sse', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../../../src/lib/sse')>()),
    openSSE: vi.fn(),
}));
vi.mock('../../../src/lib/api', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../../src/lib/api')>();
    return {
        ...actual,
        api: {
            ...actual.api,
            listProjects: vi.fn(),
            listChapters: vi.fn(),
            listCandidates: vi.fn(),
            listGraph: vi.fn(),
            listForeshadows: vi.fn(),
            listTasks: vi.fn(),
            getTask: vi.fn(),
            getChapter: vi.fn(),
        },
    };
});
afterEach(() => {
    cleanup();
    vi.clearAllMocks();
});
it.each(['plan', 'write', 'resume', 'failed-plan', 'new-task', 'writing-replan', 'rewrite-task'] as const)('replaces %s output live and loads the saved replacement automatically',async stage=>{
 const chapter:ChapterMeta={id:'c',chapter_seq:1,title:null,status:'awaiting_review',word_count:3,summary:null}
 if(stage==='writing-replan')chapter.status='writing'
 const summary:TaskSummary={task_id:'t',task_type:'chapter_generate',status:'awaiting_review',chapter_seq:1,batch_size:null,batch_current:null,cost_total:0,error:null,created_at:null}
 const detail:TaskDetail={...summary,payload:{seq:1},retry_count:0,trace_id:null,batch_task_id:null,runs:[]}
 vi.mocked(api.listProjects).mockResolvedValue([]);vi.mocked(api.listChapters).mockResolvedValue([chapter]);vi.mocked(api.listTasks).mockResolvedValue([summary]);vi.mocked(api.getTask).mockResolvedValue(detail)
 vi.mocked(api.listCandidates).mockResolvedValue([]);vi.mocked(api.listGraph).mockResolvedValue({nodes:[],edges:[]});vi.mocked(api.listForeshadows).mockResolvedValue([])
 vi.mocked(api.getChapter).mockResolvedValue({...chapter,version:1,content:'已保存旧正文'})
 let receive!:(event:SSEEvent)=>void,finish!:()=>void
 const event=(patch:Partial<SSEEvent>):SSEEvent=>({type:'artifact_delta',task_id:'t',node:'',status:'',message:'',stage:'write',chapter_seq:1,attempt:1,offset:0,done:0,total:0,artifact_id:'old',content:'',artifact:'',...patch})
 vi.mocked(openSSE).mockImplementation((_url,onEvent)=>{receive=onEvent;return new Promise(resolve=>{finish=()=>resolve({reason:'terminal'})})})
 const router=createMemoryRouter([{path:'/projects/:projectId',element:h(WorkspacePage)}],{initialEntries:['/projects/p']});render(h(RouterProvider,{router}))
 if(stage==='writing-replan')await fireEvent.click(await screen.findByRole('button',{name:/正文 Write/}))
 expect((await screen.findByLabelText('章节正文') as HTMLTextAreaElement).value).toBe('已保存旧正文')
 if(stage==='rewrite-task'){
  const plan={project_id:'p',chapter_seq:1,goals:['保留的计划'],scenes:[],characters:[],hooks_to_plant:[],hooks_to_resolve:[],expected_events:['保留的情节'],hard_constraints:[]}
  await act(async()=>receive(event({type:'artifact_complete',stage:'plan',artifact_id:'saved-plan',artifact:JSON.stringify(plan)})))
  vi.mocked(api.getTask).mockImplementation(()=>new Promise(()=>{}))
  await fireEvent.click(screen.getByText('重写保留计划'))
  expect(screen.getByRole('region',{name:'正文实时预览'})).toBeTruthy()
  expect(screen.queryByLabelText('章节正文')).toBeNull()
  await fireEvent.click(screen.getByRole('button',{name:/Plan 章节计划/}))
  expect(screen.getByText('保留的计划')).toBeTruthy()
  return
 }
 if(stage==='new-task'){
  vi.mocked(api.getTask).mockImplementation(()=>new Promise(()=>{}))
  await fireEvent.click(screen.getByText('启动新任务'))
  expect(screen.queryByLabelText('章节正文')).toBeNull()
  return
 }
 if(stage==='resume'){
  await fireEvent.click(screen.getByText('开始修订'))
  expect(screen.queryByLabelText('章节正文')).toBeNull()
 }
 await act(async()=>{
 receive(event({type:'artifact_delta',content:'旧流正文'}))
 receive(event({type:'status',status:'running'}))
 receive(event({type:'artifact_reset',stage:stage==='plan'||stage==='writing-replan'?'plan':'write',artifact_id:'new',attempt:2}))
 })
 expect(screen.queryByLabelText('章节正文')).toBeNull()
 if(stage==='plan'||stage==='writing-replan'){
  expect(screen.getByText('AI 正在规划')).toBeTruthy()
  expect((screen.getByRole('button',{name:/正文 Write/}) as HTMLButtonElement).disabled).toBe(true)
 }
 expect(screen.queryByText('旧流正文')).toBeNull()
 if(stage==='failed-plan'){
  await act(async()=>{receive(event({type:'artifact_reset',stage:'plan',artifact_id:'failed-plan',attempt:3}))})
  vi.mocked(api.getTask).mockResolvedValue({...detail,status:'failed'})
  await act(async()=>{receive(event({type:'status',status:'failed'}));finish()})
  await waitFor(()=>expect((screen.getByLabelText('章节正文') as HTMLTextAreaElement).value).toBe('已保存旧正文'))
  return
 }
 await act(async()=>{receive(event({type:'artifact_reset',artifact_id:'new-body'}));receive(event({artifact_id:'new-body',content:'替换正文第一段'}))})
 expect(await screen.findByText('替换正文第一段')).toBeTruthy()
 await act(async()=>{receive(event({artifact_id:'new-body',offset:8,content:'后续内容'}))})
 expect(await screen.findByText('替换正文第一段后续内容')).toBeTruthy()
 vi.mocked(api.getTask).mockResolvedValue({...detail,status:'done'});vi.mocked(api.getChapter).mockResolvedValue({...chapter,status:'confirmed',version:2,content:'最终保存正文'})
 await act(async()=>{receive(event({type:'artifact_complete',artifact_id:'new-body'}));receive(event({type:'status',status:'done'}));finish()})
 await waitFor(()=>expect((screen.getByLabelText('章节正文') as HTMLTextAreaElement).value).toBe('最终保存正文'))
})
