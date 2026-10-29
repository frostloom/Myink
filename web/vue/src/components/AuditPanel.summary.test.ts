import {h} from 'vue'
import {afterEach,it,expect} from 'vitest'
import {render,screen,cleanup} from '@testing-library/vue'
import type {AgentRun} from '../../../src/types'
import AuditPanel from './AuditPanel.vue'
afterEach(cleanup)
it('keeps the user summary on the latest conclusion and actionable warnings',async()=>{
 const base:AgentRun={node:'audit',model_id:'internal',input_tokens:0,output_tokens:0,cache_hit:false,duration_ms:0,cost_est:0,retry_count:0,degraded:false,error:null,detail:{audit_verdict:{verdict:'rewrite',reasons:['历史内部判断'],findings:[],confidence:.91}}}
 const latest:AgentRun={...base,detail:{audit_verdict:{verdict:'pass',reasons:['内部审稿依据'],confidence:.97,findings:[{conflict_key:'private-key',conflict_type:'style',severity:'major',scope:'local',source:'L1',evidence:[{chapter:1,quote:'内部原文长段'}],suggestion:'补充伤势恢复过程'}]}}}
 render(h(AuditPanel,{runs:[base,latest],onNavigateChapter:()=>{},concise:true}))
 expect(await screen.findByText('补充伤势恢复过程')).toBeTruthy()
 expect(screen.queryByText('历史内部判断')).toBeNull()
 expect(screen.queryByText('内部审稿依据')).toBeNull()
 expect(screen.queryByText(/置信/)).toBeNull()
 expect(screen.queryByText('内部原文长段')).toBeNull()
})
