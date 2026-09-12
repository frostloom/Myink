// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { CandidatePanel } from './CandidatePanel'
import { AuditPanel } from './AuditPanel'
import { RunNodeCard } from './RunNodeCard'
import { TaskTimeline } from './TaskTimeline'
import { api } from '../lib/api'
import type { AgentRun, MemoryCandidate, TaskSummary } from '../types'
vi.mock('../lib/api', () => ({ api: { rejectCandidate: vi.fn().mockResolvedValue({}), confirmCandidate: vi.fn().mockResolvedValue({}), resumeBatch: vi.fn().mockResolvedValue({}), listTasks: vi.fn(), getTask: vi.fn() } }))

const candidate: MemoryCandidate = {candidate_id:'c',kind:'fact',source_chapter:1,payload:{content:'伤势痊愈'},confidence:1,status:'pending',created_at:null}
const task: TaskSummary = {task_id:'t',task_type:'chapter_generate',status:'awaiting_review',chapter_seq:1,batch_size:null,batch_current:null,cost_total:0,error:null,created_at:null}
afterEach(() => {cleanup();vi.clearAllMocks()})
it('opens confirmation in a modal while the sidebar keeps only its entry and history', () => {
 render(<CandidatePanel projectId="p" chapterSeq={1} candidates={[candidate]} onChanged={()=>{}} />)
 const dialog=screen.getByRole('dialog',{name:'设定确认'})
 expect(within(dialog).getByRole('button',{name:'接受'})).toBeTruthy()
 const sidebar=screen.getByRole('region',{name:'设定评审侧栏'})
 expect(within(sidebar).queryByRole('button',{name:'接受'})).toBeNull()
 expect(within(sidebar).getByRole('button',{name:'处理 1 项设定'})).toBeTruthy()
})
it('one rejection saves the reason and starts revision without another click', async () => {
 vi.mocked(api.listTasks).mockResolvedValue([task])
 const released = vi.fn()
 render(<CandidatePanel projectId="p" chapterSeq={1} candidates={[candidate]} onChanged={()=>{}} onReleased={released} releaseTarget={{taskId:'other',chapterSeq:2}} />)
 expect(screen.queryByRole('button',{name:'仅不入库'})).toBeNull()
 fireEvent.change(screen.getByLabelText('修改意见（可选）'), {target:{value:'需要治疗'}})
 fireEvent.click(screen.getByRole('button',{name:'不接受，自动修改'}))
 await waitFor(()=>expect(api.rejectCandidate).toHaveBeenCalledWith('p','c','需要治疗','revise'))
 await waitFor(()=>expect(released).toHaveBeenCalledWith('t',1,undefined))
 expect(api.listTasks).toHaveBeenCalledWith('p',1)
 expect(api.resumeBatch).toHaveBeenCalledWith('t')
 expect(screen.getByRole('status').textContent).toContain('已提交自动修改')
 expect(screen.queryByRole('button',{name:'不接受，自动修改'})).toBeNull()
})

it('keeps saved rejection retryable when resume fails without rejecting twice', async () => {
 vi.mocked(api.listTasks).mockResolvedValue([task])
 vi.mocked(api.resumeBatch).mockRejectedValueOnce(new Error('network'))
 render(<CandidatePanel projectId="p" candidates={[candidate]} onChanged={()=>{}} />)
 fireEvent.click(screen.getByRole('button',{name:'不接受，自动修改'}))
 await screen.findByText(/意见已保存，但自动修改未能启动/)
 fireEvent.click(screen.getByRole('button',{name:'重试修改第 1 章'}))
 await screen.findByText(/已提交自动修改/)
 expect(api.rejectCandidate).toHaveBeenCalledTimes(1)
 expect(api.resumeBatch).toHaveBeenCalledTimes(2)
})

it('recovers an unapplied rejection after reloading the page', async () => {
 vi.mocked(api.listTasks).mockResolvedValue([task])
 render(<CandidatePanel projectId="p" candidates={[{...candidate,status:'rejected',review:{mode:'revise',reason:'需要治疗',applied:false}}]} onChanged={()=>{}} />)
 fireEvent.click(screen.getByRole('button',{name:/设定确认/}))
 fireEvent.click(screen.getByRole('button',{name:'重试修改第 1 章'}))
 await screen.findByText(/已提交自动修改/)
 expect(api.rejectCandidate).not.toHaveBeenCalled()
 expect(api.resumeBatch).toHaveBeenCalledWith('t')
})

it('does not reject or restart an older task when the latest chapter task is running', async () => {
 vi.mocked(api.listTasks).mockResolvedValue([{...task,task_id:'new',status:'running'},task])
 render(<CandidatePanel projectId="p" candidates={[candidate]} onChanged={()=>{}} releaseTarget={{taskId:'t',chapterSeq:1}} />)
 fireEvent.click(screen.getByRole('button',{name:'不接受，自动修改'}))
 await screen.findByText(/当前没有可修改的待评审任务/)
 expect(api.rejectCandidate).not.toHaveBeenCalled()
 expect(api.resumeBatch).not.toHaveBeenCalled()
})

it('leaves the candidate pending when saving the rejection fails', async () => {
 vi.mocked(api.listTasks).mockResolvedValue([task])
 vi.mocked(api.rejectCandidate).mockRejectedValueOnce(new Error('保存失败'))
 render(<CandidatePanel projectId="p" candidates={[candidate]} onChanged={()=>{}} />)
 fireEvent.click(screen.getByRole('button',{name:'不接受，自动修改'}))
 await screen.findByText('保存失败')
 expect(api.resumeBatch).not.toHaveBeenCalled()
 expect(screen.queryByRole('button',{name:'重试修改第 1 章'})).toBeNull()
})

it('checks the actual paused chapter before resuming a batch', async () => {
 vi.mocked(api.listTasks).mockResolvedValue([{...task,task_type:'batch_generate',batch_size:3}])
 vi.mocked(api.getTask).mockResolvedValue({task_id:'t',task_type:'batch_generate',status:'awaiting_review',payload:{start:1,size:3},progress:{current:1,total:3},runs:[],error:null,retry_count:0,trace_id:null,chapter_seq:null,batch_task_id:null,created_at:null,cost_total:0})
 render(<CandidatePanel projectId="p" candidates={[candidate]} onChanged={()=>{}} />)
 fireEvent.click(screen.getByRole('button',{name:'不接受，自动修改'}))
 await screen.findByText(/不属于批次当前待处理章节/)
 expect(api.rejectCandidate).not.toHaveBeenCalled()
 expect(api.resumeBatch).not.toHaveBeenCalled()
})

it('resumes the matching batch and preserves its progress display', async () => {
 vi.mocked(api.listTasks).mockResolvedValue([{...task,task_type:'batch_generate',batch_size:3}])
 vi.mocked(api.getTask).mockResolvedValue({task_id:'t',task_type:'batch_generate',status:'awaiting_review',payload:{start:1,size:3},progress:{current:0,total:3},runs:[],error:null,retry_count:0,trace_id:null,chapter_seq:null,batch_task_id:null,created_at:null,cost_total:0})
 const released = vi.fn()
 render(<CandidatePanel projectId="p" candidates={[candidate]} onChanged={()=>{}} onReleased={released} />)
 fireEvent.click(screen.getByRole('button',{name:'不接受，自动修改'}))
 await waitFor(()=>expect(released).toHaveBeenCalledWith('t',1,3))
 expect(api.rejectCandidate).toHaveBeenCalledWith('p','c','','revise')
})

it('accepts the last setting and continues the chapter without another confirmation click', async () => {
 render(<CandidatePanel projectId="p" candidates={[candidate]} onChanged={()=>{}} releaseTarget={{taskId:'t',chapterSeq:1}} />)
 expect(screen.queryByRole('button',{name:'重试完成确认'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'接受'}))
 await waitFor(()=>expect(api.confirmCandidate).toHaveBeenCalledWith('p','c'))
 expect(api.rejectCandidate).not.toHaveBeenCalled()
 await waitFor(()=>expect(api.resumeBatch).toHaveBeenCalledWith('t'))
 expect((await screen.findByRole('status')).textContent).toContain('设定已确认，任务正在继续')
 expect(screen.queryByRole('button',{name:'接受'})).toBeNull()
})

it('clears the continuing notice and collapses into completed history after the task is released', async () => {
 const {rerender}=render(<CandidatePanel projectId="p" chapterSeq={1} candidates={[candidate]} onChanged={()=>{}} releaseTarget={{taskId:'t',chapterSeq:1}} />)
 fireEvent.click(screen.getByRole('button',{name:'接受'}))
 await screen.findByText(/设定已确认，任务正在继续/)
 rerender(<CandidatePanel projectId="p" chapterSeq={1} chapterStatus="confirmed" candidates={[{...candidate,status:'confirmed'}]} onChanged={()=>{}} releaseTarget={null} />)
 await waitFor(()=>expect(screen.queryByText(/任务正在继续/)).toBeNull())
 expect(screen.getByRole('button',{name:/设定记录 第 1 章 已完成/}).getAttribute('aria-expanded')).toBe('false')
})

it('keeps the accepted result and offers one retry when automatic continuation fails', async () => {
 vi.mocked(api.resumeBatch).mockRejectedValueOnce(new Error('network'))
 render(<CandidatePanel projectId="p" candidates={[candidate]} onChanged={()=>{}} releaseTarget={{taskId:'t',chapterSeq:1}} />)
 fireEvent.click(screen.getByRole('button',{name:'接受'}))
 await screen.findByText(/设定已接受，但任务未能继续/)
 expect(api.confirmCandidate).toHaveBeenCalledTimes(1)
 fireEvent.click(screen.getByRole('button',{name:'重试完成确认'}))
 await waitFor(()=>expect(api.resumeBatch).toHaveBeenCalledTimes(2))
 expect(api.confirmCandidate).toHaveBeenCalledTimes(1)
})
it('shows one chapter flow with cost and route but keeps audit reasons out', () => {
 const run:AgentRun={node:'route',model_id:null,input_tokens:0,output_tokens:0,cache_hit:false,duration_ms:0,cost_est:0,retry_count:0,degraded:false,error:null,
  detail:{route:'needs_review',revision_count:2,replan_count:1,audit_verdict:{verdict:'rewrite',reasons:['伤势恢复缺少过程'],findings:[],confidence:.9}}}
 render(<TaskTimeline taskId="t" phase="terminal" status="awaiting_review" nodes={[]} runs={[run]} progress={null} error={null} onRetry={()=>{}} refresh={()=>{}} />)
 expect(screen.getByRole('region',{name:'章节状态流转'})).toBeTruthy()
 expect(screen.getByText('转人工确认')).toBeTruthy()
 expect(screen.queryByText('伤势恢复缺少过程')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:/章节流转/}))
 expect(screen.queryByText('转人工确认')).toBeNull()
})

it('separates repeated writing cycles into independently numbered generation attempts', () => {
 const base:AgentRun={node:'load_state',model_id:null,input_tokens:0,output_tokens:0,cache_hit:false,duration_ms:0,cost_est:0,retry_count:0,degraded:false,error:null,detail:null}
 const runs:AgentRun[]=[
  base,{...base,node:'write',duration_ms:100,cost_est:.01,output_tokens:100},{...base,node:'audit'},
  {...base,node:'load_state'},{...base,node:'write',duration_ms:200,cost_est:.02,output_tokens:200},{...base,node:'audit'},
 ]
 render(<TaskTimeline taskId="t" phase="terminal" status="done" nodes={[]} runs={runs} progress={null} error={null} onRetry={()=>{}} refresh={()=>{}} />)
 expect(screen.getByText('2 次生成 · 6 个阶段')).toBeTruthy()
 expect(screen.getByRole('region',{name:'第 1 次生成'})).toBeTruthy()
 expect(screen.getByRole('region',{name:'第 2 次生成'})).toBeTruthy()
})

it('keeps the timeline on writing while the write node has not been recorded yet', () => {
 const nodes=[{taskId:'t',node:'load_state',seenAt:1},{taskId:'t',node:'plan_chapter',seenAt:2}]
 render(<TaskTimeline taskId="t" phase="live" status="running" nodes={nodes} runs={[]} liveNode="write" progress={null} error={null} onRetry={()=>{}} refresh={()=>{}} />)
 expect(screen.getByText('写作')).toBeTruthy()
 expect(screen.getByText('正在执行')).toBeTruthy()
 // 已落库节点全部标为已完成，不再被最后一项误标成「正在执行」
 expect(screen.getAllByText('已完成')).toHaveLength(2)
})

it('appends the in-flight writing step after the last recorded node in the flow', () => {
 const base:AgentRun={node:'load_state',model_id:null,input_tokens:0,output_tokens:0,cache_hit:false,duration_ms:0,cost_est:0,retry_count:0,degraded:false,error:null,detail:null}
 render(<TaskTimeline taskId="t" phase="live" status="running" nodes={[]} runs={[base,{...base,node:'plan_chapter'}]} liveNode="write" progress={null} error={null} onRetry={()=>{}} refresh={()=>{}} />)
 expect(screen.getByText('章节规划')).toBeTruthy()
 expect(screen.getByText('写作')).toBeTruthy()
 expect(screen.getByText('正在执行')).toBeTruthy()
})

it('shows every audit round as an independent collapsible report', async () => {
 const oldRun:AgentRun={node:'audit',model_id:'stub',input_tokens:0,output_tokens:0,cache_hit:false,duration_ms:0,cost_est:0,retry_count:0,degraded:false,error:null,detail:{audit_verdict:{verdict:'rewrite',reasons:['旧问题'],findings:[],confidence:.8}}}
 const latestRun:AgentRun={...oldRun,detail:{audit_verdict:{verdict:'replan',replan_target:'chapter',reasons:['本章目标重复'],findings:[],confidence:.9}}}
 const loadRun:AgentRun={...oldRun,node:'load_state',detail:null}
 const persistRun:AgentRun={...oldRun,node:'persist',detail:null}
 render(<AuditPanel runs={[loadRun,oldRun,persistRun,loadRun,latestRun,persistRun]} onNavigateChapter={()=>{}} />)
 await screen.findByText('本章目标重复')
 expect(screen.getByText('旧问题')).toBeTruthy()
 expect(screen.getByText('第 1 次生成 · 第 1 轮审核')).toBeTruthy()
 expect(screen.getByText('第 2 次生成 · 第 1 轮审核')).toBeTruthy()
 expect(screen.getByText('2 次')).toBeTruthy()
 expect(screen.getByText('2 份')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:/未通过报告/}))
 expect(screen.queryByText('本章目标重复')).toBeNull()
 expect(screen.queryByText('旧问题')).toBeNull()
})

it('labels passing audit reasons as evidence and translates finding metadata', async () => {
 const passRun:AgentRun={node:'audit',model_id:'stub',input_tokens:0,output_tokens:0,cache_hit:false,duration_ms:0,cost_est:0,retry_count:0,degraded:false,error:null,detail:{audit_verdict:{verdict:'pass',reasons:['承接上一章目标'],findings:[{conflict_key:'f',conflict_type:'foreshadow',severity:'hint',scope:'local',source:'L1',evidence:[{chapter:17,quote:'一句伏笔'}],suggestion:null}],confidence:.82}}}
 render(<AuditPanel runs={[passRun]} onNavigateChapter={()=>{}} />)
 expect(await screen.findByText('通过依据')).toBeTruthy()
 expect(screen.queryByText('未通过原因')).toBeNull()
 expect(screen.getByText('伏笔')).toBeTruthy()
 expect(screen.getByText('确定性校验')).toBeTruthy()
})

it('scopes setting confirmation to the selected chapter', () => {
 const chapterTwo={...candidate,candidate_id:'c2',source_chapter:2,payload:{content:'第二章设定'}}
 render(<CandidatePanel projectId="p" chapterSeq={2} candidates={[candidate,chapterTwo]} onChanged={()=>{}} />)
 expect(screen.getByText('第二章设定')).toBeTruthy()
 expect(screen.queryByText('伤势痊愈')).toBeNull()
 expect(screen.getByRole('button',{name:/设定确认 第 2 章/})).toBeTruthy()
})

it('historical audit cards show their stored decision', () => {
 render(<RunNodeCard run={{node:'audit',model_id:'stub',input_tokens:0,output_tokens:0,cache_hit:false,duration_ms:0,cost_est:0,retry_count:0,degraded:false,error:null,detail:{audit_verdict:{verdict:'replan',replan_target:'chapter',reasons:['本章目标重复'],findings:[],confidence:.9}}}} />)
 expect(screen.getByText('replan · 重规划')).toBeTruthy()
 expect(screen.getByText('本章目标重复')).toBeTruthy()
})
