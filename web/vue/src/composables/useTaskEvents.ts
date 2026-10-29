import { reactive, watch, toValue, onScopeDispose, type MaybeRefOrGetter } from 'vue'
import { api } from '../../../src/lib/api'
import { openSSE, type SSEEvent } from '../../../src/lib/sse'
import type { AgentRun, TaskBudgetView, TaskStatus } from '../../../src/types'
export type TaskPhase = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'terminal' | 'expired' | 'error'
export interface NodeEvent { taskId: string; node: string; seenAt: number }
export interface ArtifactState { artifactId: string; taskId: string; stage: string; chapterSeq: number; attempt: number; content: string; complete: boolean; failed: boolean; artifact: unknown | null; message: string | null }
export interface TaskEventState { budget: TaskBudgetView | null; phase: TaskPhase; status: TaskStatus | null; nodes: NodeEvent[]; artifacts: ArtifactState[]; runs: AgentRun[]; progress: {current:number;total:number}|null; shortProgress:{stage:string;current:number;total:number}|null;error:string|null;payload:Record<string,unknown>;lastEventId:string|null;stop:()=>void;retry:()=>void;refresh:()=>void;beginReplacement:(chapterSeq:number)=>void }
const terminal = new Set<TaskStatus>(['done','failed','cancelled','awaiting_plan','awaiting_review'])
export function useTaskEvents(taskId: MaybeRefOrGetter<string | null>, opts?: { batchTotal?: MaybeRefOrGetter<number | undefined>; resumeKey?: MaybeRefOrGetter<number | null> }):TaskEventState {
  const state = reactive<TaskEventState>({budget:null,phase:'idle',status:null,nodes:[],artifacts:[],runs:[],progress:null,shortProgress:null,error:null,payload:{},lastEventId:null,stop,retry,refresh,beginReplacement})
  let epoch=0, statusSeq=0, connected:string|null=null, disposed=false, awaitingReplacement=false
  let abort:AbortController|null=null
  let snapTimer:ReturnType<typeof setTimeout>|null=null
  let delayTimer:ReturnType<typeof setTimeout>|null=null
  let wake: (()=>void)|null=null
  let snapshotProgress:{current:number;total:number}|null=null
  const artifacts=new Map<string,ArtifactState>()
  const retiredArtifacts=new Set<string>()
  function removeArtifact(key:string) { const previous=artifacts.get(key);if(previous)retiredArtifacts.add(previous.artifactId);artifacts.delete(key) }
  function beginReplacement(chapterSeq:number) {
    awaitingReplacement=true;removeArtifact(`write:${chapterSeq}`);state.artifacts=Array.from(artifacts.values());state.status='queued';statusSeq++
  }
  function clearConnection() { abort?.abort(); if(snapTimer!==null)clearTimeout(snapTimer);snapTimer=null;if(delayTimer!==null)clearTimeout(delayTimer);delayTimer=null;wake?.();wake=null }
  function stop() {
    epoch++;clearConnection();awaitingReplacement=false;connected=null;statusSeq=0;artifacts.clear();retiredArtifacts.clear();snapshotProgress=null
    Object.assign(state,{budget:null,phase:'idle',status:null,nodes:[],artifacts:[],runs:[],progress:null,shortProgress:null,error:null,payload:{},lastEventId:null})
  }
  function effectiveProgress() {
    const total=opts?.batchTotal===undefined?undefined:toValue(opts.batchTotal)
    state.progress=snapshotProgress??(total?{current:new Set(state.nodes.filter(n=>n.node==='summarize').map(n=>n.taskId)).size,total}:null)
  }
  async function snapshot(tid:string, force=false, version=epoch):Promise<TaskStatus|null> {
    const seq=statusSeq
    try {
      const detail=await api.getTask(tid)
      if(disposed||version!==epoch||connected!==tid)return null
      if(awaitingReplacement && detail.status==='awaiting_review')return state.status
      awaitingReplacement=false
      state.runs=detail.runs;state.budget=detail.budget??null;state.payload=detail.payload;state.error=detail.error
      if(detail.progress)snapshotProgress=detail.progress
      effectiveProgress()
      if(seq===statusSeq){
        state.status=detail.status;statusSeq++
        if(force&&terminal.has(detail.status)){abort?.abort();state.phase='terminal'}
      }
      return state.status
    } catch {return null}
  }
  function schedule(tid:string,version:number) {
    if(snapTimer!==null)return
    snapTimer=setTimeout(()=>{snapTimer=null;void snapshot(tid,false,version)},250)
  }
  async function pause(ms:number) { await new Promise<void>(resolve=>{wake=resolve;delayTimer=setTimeout(()=>{delayTimer=null;wake=null;resolve()},ms)}) }
  async function connect(tid:string) {
    clearConnection();const version=++epoch;const controller=new AbortController();abort=controller
    const current=()=>!disposed&&version===epoch&&!controller.signal.aborted
    state.phase='connecting'
    // Capture this epoch after opening so late snapshots from a previous retry are invalid.
    void snapshot(tid,false,version)
    const receive=(ev:SSEEvent)=>{
      if(!current() || (ev.task_id!==tid && !ev.task_id.startsWith(`${tid}:ch`)))return
      if(ev.type.startsWith('artifact_') && (ev.task_id!==tid && ev.task_id!==`${tid}:ch${ev.chapter_seq}` || retiredArtifacts.has(ev.artifact_id)))return
      state.phase='live'
      if(ev.status){awaitingReplacement=false;statusSeq++;state.status=ev.status as TaskStatus}
      if(ev.node){state.nodes.push({taskId:ev.task_id,node:ev.node,seenAt:Date.now()});effectiveProgress();schedule(tid,version)}
      if(ev.type==='progress'&&ev.stage)state.shortProgress={stage:ev.stage,current:ev.done,total:ev.total}
      if(ev.type.startsWith('artifact_')&&ev.stage&&ev.chapter_seq){
        if(awaitingReplacement && ev.stage==='write'){awaitingReplacement=false;state.status='running';statusSeq++}
        const key=`${ev.stage}:${ev.chapter_seq}`, previous=artifacts.get(key)
        if(previous && previous.artifactId!==ev.artifact_id)retiredArtifacts.add(previous.artifactId)
        if(ev.type==='artifact_reset' && ev.stage==='plan')removeArtifact(`write:${ev.chapter_seq}`)
        const fresh:ArtifactState={artifactId:ev.artifact_id,taskId:ev.task_id,stage:ev.stage,chapterSeq:ev.chapter_seq,attempt:ev.attempt,content:'',complete:false,failed:false,artifact:null,message:null}
        const entry=ev.type==='artifact_reset'||previous?.artifactId!==ev.artifact_id?fresh:{...previous}
        if(ev.type==='artifact_delta'){const points=Array.from(entry.content);entry.content=ev.offset<points.length?points.slice(0,ev.offset).join('')+ev.content:entry.content+ev.content}
        if(ev.artifact){try{entry.artifact=JSON.parse(ev.artifact) as unknown}catch{entry.artifact=null}}
        if(ev.type==='artifact_complete')entry.complete=true
        if(ev.type==='artifact_failed')entry.failed=true
        entry.message=ev.message||entry.message;artifacts.set(key,entry);state.artifacts=Array.from(artifacts.values())
      }
    }
    let attempt=0
    while(current()){
      const result=await openSSE(`/api/v1/tasks/${tid}/events`,receive,{signal:controller.signal,lastEventId:state.lastEventId??undefined,onLastId:id=>{if(current())state.lastEventId=id}})
      if(!current())return
      if(['terminal','expired','eof','network'].includes(result.reason)){
        const actual=await snapshot(tid,false,version)
        if(!current())return
        if(result.reason==='terminal'&&actual&&terminal.has(actual)){state.phase='terminal';return}
        if(result.reason==='expired'&&actual&&terminal.has(actual)){state.phase='expired';return}
        if((result.reason==='eof'||result.reason==='network')&&actual&&terminal.has(actual)){state.phase='terminal';return}
        state.phase='reconnecting';attempt++
        await pause(result.reason==='terminal'?Math.min(4000,500*2**Math.min(attempt-1,3)):Math.min(8000,1000*2**Math.min(attempt-1,3)))
      }else{state.phase='error';return}
    }
  }
  function retry(){const id=toValue(taskId);if(id){connected=id;void connect(id)}}
  function refresh(){if(connected)void snapshot(connected,true)}
  watch(()=>[toValue(taskId),opts?.resumeKey===undefined?null:toValue(opts.resumeKey)] as const,([id])=>{
    if(!id){stop();return}
    if(id!==connected){stop();connected=id}
    void connect(id)
  },{immediate:true})
  if(opts?.batchTotal!==undefined)watch(()=>toValue(opts.batchTotal!),effectiveProgress)
  onScopeDispose(()=>{disposed=true;stop()})
  return state
}
