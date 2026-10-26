import { afterEach, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { api } from '../../../src/lib/api'
import { openSSE, type SSEEvent } from '../../../src/lib/sse'
import type { TaskDetail } from '../../../src/types'
import { useTaskEvents } from './useTaskEvents'
vi.mock('../../../src/lib/api',()=>({api:{getTask:vi.fn()}}))
vi.mock('../../../src/lib/sse',()=>({openSSE:vi.fn()}))
const scopes:ReturnType<typeof effectScope>[]=[]
function start(id=ref<string|null>('a'),resumeKey=ref(0)) { const scope=effectScope();scopes.push(scope);return {state:scope.run(()=>useTaskEvents(id,{resumeKey}))!,id,resumeKey} }
const detail=(id='a',status:TaskDetail['status']='running'):TaskDetail=>({task_id:id,task_type:'chapter_generate',status,payload:{seq:1},error:null,retry_count:0,trace_id:null,chapter_seq:1,batch_task_id:null,created_at:null,cost_total:0,runs:[]})
const event=(patch:Partial<SSEEvent>):SSEEvent=>({type:'node',task_id:'a',node:'',status:'',message:'',stage:'',chapter_seq:0,attempt:1,offset:0,done:0,total:0,artifact_id:'',content:'',artifact:'',...patch})
afterEach(()=>{scopes.splice(0).forEach(s=>s.stop());vi.clearAllMocks();vi.useRealTimers()})
it('loads archived snapshots while the stream stays open',async()=>{
 vi.mocked(api.getTask).mockResolvedValue({...detail('a','done'),runs:[{task_id:'a',node:'write',model_id:'test',input_tokens:1,output_tokens:2,cost_est:0,duration_ms:1,retry_count:0,cache_hit:false,degraded:false,error:null,detail:null}]})
 vi.mocked(openSSE).mockImplementation(()=>new Promise(()=>{}));const {state}=start();await flushPromises();expect(state.runs[0]?.node).toBe('write');expect(state.status).toBe('done')
})
it('shows partial Unicode artifact data before completion and replaces overlapping offsets',async()=>{
 vi.mocked(api.getTask).mockResolvedValue(detail());vi.mocked(openSSE).mockImplementation(async(_u,on)=>{on(event({type:'artifact_reset',stage:'write',chapter_seq:1,artifact_id:'x'}));on(event({type:'artifact_delta',stage:'write',chapter_seq:1,artifact_id:'x',content:'甲😀乙'}));on(event({type:'artifact_delta',stage:'write',chapter_seq:1,artifact_id:'x',offset:2,content:'丙'}));return new Promise(()=>{})})
 const {state}=start();await flushPromises();expect(state.artifacts[0]?.content).toBe('甲😀丙');expect(state.artifacts[0]?.complete).toBe(false)
})
it('does not let a slow snapshot override a newer SSE status',async()=>{
 let finish!:(v:TaskDetail)=>void;vi.mocked(api.getTask).mockImplementation(()=>new Promise(r=>{finish=r}));vi.mocked(openSSE).mockImplementation(async(_u,on)=>{on(event({type:'status',status:'awaiting_plan'}));return new Promise(()=>{})});const {state}=start();finish(detail());await flushPromises();expect(state.status).toBe('awaiting_plan')
})
it('ignores old snapshots and events after a task switch',async()=>{
 let old!:(e:SSEEvent)=>void;let finish!:(d:TaskDetail)=>void;vi.mocked(api.getTask).mockImplementationOnce(()=>new Promise(r=>{finish=r})).mockResolvedValue(detail('b','done'));vi.mocked(openSSE).mockImplementationOnce(async(_u,on)=>{old=on;return new Promise(()=>{})}).mockImplementation(()=>new Promise(()=>{}));const {state,id}=start();id.value='b';await flushPromises();finish(detail('a','failed'));old(event({type:'status',status:'failed'}));await flushPromises();expect(state.status).toBe('done')
})
it('keeps reconnecting after 410 when the task is still running',async()=>{
 vi.useFakeTimers();vi.mocked(api.getTask).mockResolvedValue(detail());vi.mocked(openSSE).mockResolvedValue({reason:'expired'});const {state}=start();await vi.advanceTimersByTimeAsync(0);expect(state.phase).toBe('reconnecting');await vi.advanceTimersByTimeAsync(1000);expect(openSSE).toHaveBeenCalledTimes(2);expect(state.phase).toBe('reconnecting')
})
it.each(['expired', 'terminal'] as const)('retries an unconfirmed %s stream ending when task snapshots are unavailable', async reason => {
 vi.useFakeTimers()
 vi.mocked(api.getTask).mockRejectedValueOnce(new Error('offline')).mockRejectedValueOnce(new Error('offline')).mockResolvedValue(detail())
 vi.mocked(openSSE).mockImplementation(async (_url, onEvent) => {
   if (reason === 'terminal') onEvent(event({ type: 'status', status: 'awaiting_review' }))
   return { reason }
 })
 const { state } = start()
 await vi.advanceTimersByTimeAsync(0)
 expect(state.phase).toBe('reconnecting')
 await vi.advanceTimersByTimeAsync(1000)
 expect(state.status).toBe('running')
 expect(state.phase).toBe('reconnecting')
})
it('accepts EOF only after snapshot confirms a terminal task',async()=>{
 vi.mocked(api.getTask).mockResolvedValue(detail('a','done'));vi.mocked(openSSE).mockResolvedValue({reason:'eof'});const{state}=start();await flushPromises();expect(state.phase).toBe('terminal')
})
it('does not let a delayed manual refresh terminate a newer SSE state', async () => {
 let receive!: (value: SSEEvent) => void
 let finish!: (value: TaskDetail) => void
 let signal!: AbortSignal
 vi.mocked(api.getTask).mockResolvedValueOnce(detail()).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
 vi.mocked(openSSE).mockImplementation((_url, onEvent, options) => {
   receive = onEvent; signal = options!.signal!
   return new Promise(() => {})
 })
 const { state } = start(); await flushPromises()
 state.refresh()
 receive(event({ type: 'status', status: 'running' }))
 finish(detail('a', 'awaiting_review')); await flushPromises()
 expect(state.status).toBe('running')
 expect(state.phase).toBe('live')
 expect(signal.aborted).toBe(false)
})
it('stores short progress separately and resumes the same task when resumeKey changes',async()=>{
 vi.mocked(api.getTask).mockResolvedValue(detail());vi.mocked(openSSE).mockImplementation(async(_u,on)=>{on(event({type:'progress',stage:'short_write',done:4400,total:20000}));return new Promise(()=>{})});const{state,resumeKey}=start();await flushPromises();expect(state.shortProgress).toEqual({stage:'short_write',current:4400,total:20000});expect(state.progress).toBeNull();resumeKey.value++;await flushPromises();expect(openSSE).toHaveBeenCalledTimes(2)
})
