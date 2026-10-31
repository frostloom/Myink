<script setup lang="ts">
import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { ApiError } from '../../../../src/lib/api'
import { formatApiError } from '../../../../src/lib/apiError'
import { piApi, type PiCandidate, type PiDecision, type PiEvent, type PiOperation } from '../../../../src/lib/piApi'
import { useAdminContext } from './context'
import { useResource } from './shared'
import NativeDialog from '../../components/NativeDialog.vue'
import base from '../../../../src/pages/AdminPage.module.css'
import styles from './PiConsolePage.module.css'

const context=useAdminContext()
const accessLost=ref(false)
function forbidden(){accessLost.value=true;context.onForbidden()}
const status=useResource(signal=>piApi.status(context.token,signal),forbidden)
const today=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())
const day=ref(today());const runOffset=ref(0);const eventOffset=ref(0);const selectedRun=ref('')
const daily=useResource(signal=>status.data ? piApi.daily(context.token,day.value,signal) : Promise.resolve(null),forbidden)
const runs=useResource(signal=>status.data ? piApi.runs(context.token,{day:day.value,limit:25,offset:runOffset.value},signal) : Promise.resolve(null),forbidden)
const runId=computed(()=>selectedRun.value||status.data?.task_id||runs.data?.items[0]?.run_id||'')
const events=useResource(signal=>status.data&&runId.value ? piApi.events(context.token,{runId:runId.value,limit:25,offset:eventOffset.value},signal) : Promise.resolve(null),forbidden)
const observations=useResource(async signal=>{
 if(!status.data||!runId.value)return null
 const first=await piApi.events(context.token,{runId:runId.value,kind:'observation',limit:1},signal)
 return first.total>1?piApi.events(context.token,{runId:runId.value,kind:'observation',limit:1,offset:first.total-1},signal):first
},forbidden)
const phases={idle:'等待下一轮',preparing:'准备本轮产物',awaiting_approval:'等待发布确认',awaiting_deployment:'已批准，等待部署核验',observing:'观察已部署版本',blocked:'需要人工处理'}
const labels:Record<string,string>={observation:'指标观察',analysis:'分析',plan:'计划与决定',review:'独立评审',tool:'工具调用',development:'隔离开发',test:'测试',deployment:'部署',rollback:'回退',followup:'次日计划',version:'版本',enhancement:'工具与边界',memory:'记忆',passed:'通过',failed:'失败',blocked:'待人工处理',uncertain:'未确认',insufficient_evidence:'证据不足',planned:'已计划',running:'处理中',no_change:'无新变更',no_release:'未发布',candidate_ready:'候选已准备',rolled_back:'已回退',skipped:'未执行'}
const toolLabels:Record<string,string>={observe_metrics:'读取冻结指标',read_source:'读取允许源码',propose_plan:'提出修复计划',apply_patch:'修改隔离候选',run_check:'执行固定检查',candidate_status:'核对候选状态'}
const domainLabels:Record<string,string>={online_business:'线上业务记录',real_provider_fixed_input:'真实模型固定输入',offline:'离线验证',synthetic:'合成或模拟证据',unknown:'证据来源未确定'}
const operation=shallowRef<PiOperation|null>(null)
const activeOperation=computed(()=>{
 const value=status.data
 if(!value?.cycle_id)return null
 if(operation.value?.cycle_id===value.cycle_id)return operation.value
 return value.latest_operation?.cycle_id===value.cycle_id?value.latest_operation:null
})
const busyStatuses=new Set(['recording','queued','running','uncertain'])
const sending=ref(false);const actionMessage=ref('');const actionError=ref('');let actionController:AbortController|undefined
let pollTimer:ReturnType<typeof setTimeout>|undefined;let pollController:AbortController|undefined
const busy=computed(()=>status.loading||!status.data||sending.value||!!activeOperation.value&&(busyStatuses.has(activeOperation.value.status)||activeOperation.value.decision==='publish'&&activeOperation.value.status==='succeeded'))
const modal=shallowRef<{cycle:string;candidate:PiCandidate}|null>(null)
const latestObservation=computed(()=>observations.data?.items.filter(e=>e.kind==='observation').at(-1))
const sampleLabel=computed(()=>{
 const details=latestObservation.value?.details
 if(typeof details?.observed_samples==='number'&&typeof details.minimum_samples==='number')return `${details.observed_samples} / ${details.minimum_samples}`
 const count=daily.data?.sample_windows.find(window=>window.run_id===runId.value)?.observed_samples
 return count===null||count===undefined?'未知':`${count} 个有效样本`
})
const observedStatus=computed(()=>latestObservation.value?.status==='insufficient_evidence'?'证据不足':latestObservation.value?labels[latestObservation.value.status]??latestObservation.value.status:'查看观察记录')
const formatCount=(value:number|null|undefined)=>value===null||value===undefined?'未知':value.toLocaleString('zh-CN')
const cost=(value:number|null|undefined)=>value===null||value===undefined?'未知':new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY',minimumFractionDigits:2,maximumFractionDigits:6}).format(value/1000000)
function time(value:string|null|undefined){if(!value)return '未知';const result=new Date(value);return Number.isNaN(result.getTime())?'未知':new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(result)}
function refresh(){status.retry();actionError.value=''}
watch(day,()=>{runOffset.value=0;eventOffset.value=0;selectedRun.value=''})
watch(runId,()=>{eventOffset.value=0})
watch(()=>status.data?.package_sha256,value=>{
 if(value&&modal.value&&value!==modal.value.candidate.package_sha256){modal.value=null;actionError.value='候选已变化，请重新核对后再发布。'}
})
function stopPoll(){if(pollTimer)clearTimeout(pollTimer);pollController?.abort();pollTimer=undefined}
async function poll(id:string){
 stopPoll();pollController=new AbortController();const controller=pollController
 try{
  const value=await piApi.operation(context.token,id,controller.signal)
  if(controller.signal.aborted)return
  operation.value=value
  if(['recording','queued','running'].includes(value.status))pollTimer=setTimeout(()=>{void poll(id)},2000)
  else {actionMessage.value='';status.retry();daily.retry();runs.retry();events.retry();observations.retry()}
 }catch(error){
  if(controller.signal.aborted)return
  if(error instanceof ApiError&&(error.status===401||error.status===403)){forbidden();return}
  actionError.value='发布状态暂时无法读取，请刷新查看；不会自动重复提交。'
 }
}
watch(()=>status.data,value=>{
 if(!value)return
 if(operation.value?.cycle_id!==value.cycle_id){operation.value=null;stopPoll()}
 const latest=value.latest_operation
 if(!latest||latest.cycle_id!==value.cycle_id)return
 if(operation.value&&operation.value.request_id!==latest.request_id&&latest.created_at<operation.value.created_at)return
 operation.value=latest;stopPoll()
 if(['recording','queued','running'].includes(latest.status))void poll(latest.request_id)
})
function openConfirmation(){const value=status.data;if(value?.cycle_id&&value.candidate)modal.value={cycle:value.cycle_id,candidate:structuredClone(value.candidate)}}
async function decide(decision:'publish'|'defer'){
 const current=status.data;const frozen=decision==='publish'?modal.value:current?.cycle_id&&current.candidate?{cycle:current.cycle_id,candidate:current.candidate}:null
 if(!frozen||busy.value||current?.phase!=='awaiting_approval')return
 if(current.cycle_id!==frozen.cycle||current.package_sha256!==frozen.candidate.package_sha256){modal.value=null;actionError.value='候选已变化，请重新核对后再发布。';return}
 const candidate=frozen.candidate
 const body:PiDecision={request_id:crypto.randomUUID(),cycle_id:frozen.cycle,package_sha256:candidate.package_sha256,image_id:candidate.image_id,source_sha256:candidate.source_sha256,comparison_sha256:candidate.comparison_sha256,decision}
 modal.value=null;sending.value=true;actionMessage.value='';actionError.value='';actionController?.abort();actionController=new AbortController();const controller=actionController
 try{
  const result=await piApi.decide(context.token,body,controller.signal)
  if(controller.signal.aborted)return
  operation.value=result
  if(result.status==='deferred')actionMessage.value='已记录暂不发布，Pi 继续等待确认。'
  else if(['recording','queued','running'].includes(result.status)){actionMessage.value='发布请求已受理，等待宿主处理。';void poll(result.request_id)}
  else {actionMessage.value='';status.retry();daily.retry();runs.retry();events.retry();observations.retry()}
 }catch(error){
  if(controller.signal.aborted)return
  if(error instanceof ApiError&&(error.status===401||error.status===403)){forbidden();return}
  actionError.value=formatApiError(error,'请求状态未确认，请刷新查看；不会自动重复提交。');status.retry()
 }finally{if(!controller.signal.aborted)sending.value=false}
}
function operationLabel(value:PiOperation){return {recording:'正在记录发布决定',queued:'等待宿主处理',running:'正在发布',deferred:'暂不发布',succeeded:'发布已核验',failed:'发布前检查失败',uncertain:'发布状态未确认，需要人工检查'}[value.status]}
const detailLabels:Record<string,string>={decision:'决定',next_action:'下一步',request_summary:'工具输入摘要',result_summary:'工具结果',availability:'可用情况',test_id:'测试标识',reference:'证据引用',change_summary:'变更说明',operation_id:'操作标识',model_requests:'模型请求',tool_calls:'工具调用',input_tokens:'输入 Token',output_tokens:'输出 Token',known_cost_microyuan:'原已知费用',reserved_microyuan:'保留费用',test_total:'检查总数',test_failures:'检查失败',test_errors:'检查错误',test_skipped:'检查跳过',baseline_failures:'基线失败',minimum_samples:'最低样本',observed_samples:'观察样本'}
function auditDetails(event:PiEvent){return Object.entries(event.details).filter(([key])=>key in detailLabels).map(([key,value])=>({key,label:detailLabels[key],value:value===null?'未知':key.endsWith('microyuan')?cost(typeof value==='number'?value:null):String(value)}))}
function textDetail(event:PiEvent,key:string){const value=event.details[key];return typeof value==='string'?value:null}
onScopeDispose(()=>{stopPoll();actionController?.abort()})
</script>

<template>
  <div v-if="accessLost" role="alert" class="empty">管理员权限已变化，受保护记录已清除。</div>
  <section v-else :class="base.view" aria-labelledby="pi-heading">
    <header :class="base.viewHead"><div><h1 id="pi-heading">Pi 管理</h1><p>查看维护过程，在候选准备完成后决定是否发布。</p></div><button class="btn btn-quiet" aria-label="刷新 Pi 状态" @click="refresh">刷新</button></header>
    <div v-if="status.error" role="alert" :class="styles.notice">Pi 宿主控制台暂时不可用。{{ status.error }} <button class="btn btn-quiet" @click="refresh">重新读取</button></div>
    <p v-else-if="status.loading" class="empty">正在读取 Pi 状态…</p>
    <template v-if="status.data">
      <section :class="styles.state" aria-label="Pi 当前阶段"><div><span :class="styles.eyebrow">{{ status.data.mode==='SIMULATED'?'模拟控制台':'宿主运行记录' }}</span><h2>{{ phases[status.data.phase] }}</h2><p v-if="status.data.phase==='awaiting_approval'">未发布期间，Pi 保持等待，不进入新一轮模型迭代。</p><p v-else-if="status.data.phase==='observing'">正在等待或观察已核验版本的真实指标，下一候选仍需人工确认。</p><p v-else-if="status.data.phase==='blocked'">请先检查失败与审计记录，系统不会自动重放未确认操作。</p><p v-else>每轮产物、决定与执行结果分别保留。</p></div><dl :class="styles.facts"><div><dt>状态读取</dt><dd>{{ time(status.data.observed_at) }} · 北京时间</dd></div><div><dt>夜间调度</dt><dd>{{ status.data.executor.timer_state==='active/waiting'?'等待夜间检查':status.data.executor.timer_state }}</dd></div><div><dt>次日评测</dt><dd>{{ status.data.next_assessment_at?`${time(status.data.next_assessment_at)} · 北京时间`:'实际部署核验后安排' }}</dd></div></dl></section>
      <section v-if="status.data.deployment" :class="styles.section" aria-labelledby="deployed-heading"><h2 id="deployed-heading">本轮已核验部署</h2><dl :class="styles.identity"><div><dt>部署标识</dt><dd>{{ status.data.deployment.deployment_id }}</dd></div><div><dt>实际部署时间</dt><dd>{{ time(status.data.deployment.deployed_at) }} · 北京时间</dd></div><div><dt>已核验镜像</dt><dd>{{ status.data.deployment.image_id }}</dd></div></dl></section>
      <p v-if="actionError" role="alert" :class="styles.notice">{{ actionError }}</p><p v-if="actionMessage" role="status">{{ actionMessage }}</p>
      <section v-if="activeOperation" :class="styles.notice" aria-label="发布操作"><strong>{{ operationLabel(activeOperation) }}</strong><p>操作 {{ activeOperation.request_id }} · {{ time(activeOperation.created_at) }}</p><p v-if="activeOperation.status==='uncertain'">请核对实际运行版本与审计后再处理，不会自动再次部署。</p></section>
      <section v-if="status.data.candidate" :class="styles.section" aria-labelledby="candidate-heading">
<header :class="styles.sectionHead"><div><h2 id="candidate-heading">{{ status.data.phase==='awaiting_approval'?'待发布候选':'本轮产物' }}</h2><p>固定输入评测与线上观察分别展示。</p></div><div v-if="status.data.phase==='awaiting_approval'" :class="styles.actions"><button class="btn btn-quiet" :disabled="busy" @click="decide('defer')">暂不发布</button><button class="btn btn-primary" :disabled="busy||!status.data.candidate.publication_available" @click="openConfirmation">查看并发布</button></div></header>
        <p v-if="status.data.phase==='awaiting_approval'&&!status.data.candidate.publication_available" :class="styles.muted">宿主发布通道尚未配置或材料不可用，当前不能发布。</p>
        <dl :class="styles.metrics"><div><dt>冻结检查</dt><dd>{{ status.data.candidate.evaluation.checker.passed?'通过':'未通过' }} · {{ formatCount(status.data.candidate.evaluation.checker.tests) }} 项</dd></div><div><dt>原模型请求</dt><dd>{{ formatCount(status.data.candidate.evaluation.model_requests) }}</dd></div><div><dt>原工具调用</dt><dd>{{ formatCount(status.data.candidate.evaluation.tool_count) }}</dd></div><div><dt>原已知费用</dt><dd>{{ cost(status.data.candidate.evaluation.known_cost_microyuan) }}</dd></div></dl>
        <p :class="styles.muted">{{ domainLabels[status.data.candidate.evaluation.evidence_domain]??'证据来源未确定' }} · <span>线上效果尚未验证</span></p>
        <details :class="styles.identity"><summary>查看精确版本与比较参数</summary><dl><div><dt>镜像</dt><dd>{{ status.data.candidate.image_id }}</dd></div><div><dt>产物摘要</dt><dd>{{ status.data.candidate.package_sha256 }}</dd></div><div><dt>源码摘要</dt><dd>{{ status.data.candidate.source_sha256 }}</dd></div><div><dt>比较参数</dt><dd>{{ status.data.candidate.comparison_sha256 }}</dd></div></dl></details>
        <div :class="base.tableWrap"><table><caption :class="styles.caption">候选变更范围</caption><thead><tr><th>文件</th><th>新增</th><th>删除</th></tr></thead><tbody><tr v-for="change in status.data.candidate.changes" :key="change.path"><td :class="styles.code">{{ change.path }}</td><td>{{ formatCount(change.added) }}</td><td>{{ formatCount(change.deleted) }}</td></tr></tbody></table></div>
      </section>
      <section :class="styles.section" aria-labelledby="report-heading">
<header :class="styles.sectionHead"><h2 id="report-heading">指标与每日记录</h2><label :class="styles.date">记录日期<input v-model="day" type="date" class="input" /></label></header>
        <p v-if="daily.error" role="alert">审计报告不可用：{{ daily.error }}</p><p v-else-if="daily.loading">正在读取报告…</p>
        <template v-else-if="daily.data">
<div :class="styles.metrics"><div><span>所选运行的观察</span><strong>{{ sampleLabel }}</strong></div><div><span>主机判断</span><strong>{{ observedStatus }}</strong></div><div><span>本日报告记录</span><strong>{{ daily.data.event_count }}</strong></div></div><p :class="styles.muted">滚动窗口可能重叠，保留各自样本数，不相加为独立样本。未知数值保持未知。</p>
          <ul v-if="daily.data.sample_windows.length" :class="styles.windows"><li v-for="window in daily.data.sample_windows" :key="window.event_sha256"><button class="btn btn-quiet" @click="selectedRun=window.run_id">{{ window.window||window.run_id }} · {{ formatCount(window.observed_samples) }} 个样本</button></li></ul>
          <details><summary>每日版本与变更（{{ daily.data.versions.length }} 个版本上下文）</summary><p v-if="!daily.data.versions.length">本日没有版本记录，当前状态未知。</p><ul :class="styles.versions"><li v-for="(version,index) in daily.data.versions" :key="index"><span>源码 {{ version.source_commit||'未知' }}</span><span>部署 {{ version.deployment_id||'未登记' }}</span><span v-for="(image,role) in version.image_ids" :key="role">{{ role }} · {{ image }}</span></li></ul><div :class="base.tableWrap"><table><caption :class="styles.caption">每日变更范围</caption><thead><tr><th>文件</th><th>新增</th><th>删除</th><th>源码版本</th></tr></thead><tbody><tr v-for="(change,index) in daily.data.change_scope" :key="index"><td :class="styles.code">{{ change.path }}</td><td>{{ formatCount(change.added) }}</td><td>{{ formatCount(change.deleted) }}</td><td :class="styles.code">{{ change.source_commit||'未知' }}</td></tr></tbody></table><p v-if="!daily.data.change_scope.length" :class="styles.muted">本日没有登记变更范围。</p></div></details>
          <section aria-labelledby="next-tests-heading"><h3 id="next-tests-heading">本日报告登记的次日计划</h3><p v-if="!daily.data.next_tests.length" :class="styles.muted">本日报告未登记测试计划；可切换到计划登记日期查看。</p><ul v-else :class="styles.plans"><li v-for="plan in daily.data.next_tests" :key="plan.test_id"><div><strong>{{ plan.kind==='regression'?'冻结回归':plan.kind==='metrics'?'指标观察':plan.kind }}</strong><span>{{ time(plan.scheduled_for) }} · 北京时间</span></div><span>{{ plan.result?(labels[plan.result.status]??plan.result.status):'尚未执行' }}</span></li></ul></section>
        </template>
      </section>
      <section :class="styles.section" aria-labelledby="history-heading">
<header :class="styles.sectionHead"><h2 id="history-heading">分析与修复流程</h2><label>选择 Pi 运行<select v-model="selectedRun" class="input"><option v-if="status.data.task_id&&!runs.data?.items.some(run=>run.run_id===status.data?.task_id)" :value="status.data.task_id">当前任务 · {{ status.data.task_id }}</option><option v-for="run in runs.data?.items??[]" :key="run.run_id" :value="run.run_id">{{ run.run_id }} · {{ run.event_count }} 条</option></select></label></header>
        <p v-if="runs.error" role="alert">运行索引不可用：{{ runs.error }}</p><p v-else-if="runs.data?.total===0">暂无运行记录</p>
        <nav v-if="runs.data&&runs.data.total>25" :class="styles.actions" aria-label="Pi 运行分页"><button class="btn btn-quiet" :disabled="runOffset===0" @click="runOffset-=25">上一页运行</button><span>{{ runOffset+1 }}–{{ Math.min(runOffset+25,runs.data.total) }} / {{ runs.data.total }}</span><button class="btn btn-quiet" :disabled="runOffset+25>=runs.data.total" @click="runOffset+=25">下一页运行</button></nav>
        <p v-if="events.error" role="alert">运行审计不可用：{{ events.error }}</p><p v-else-if="events.loading">正在读取运行记录…</p>
        <ol v-else :class="styles.timeline"><li v-for="event in events.data?.items??[]" :key="event.event_sha256"><div :class="styles.eventHead"><strong>{{ labels[event.kind]??event.kind }}</strong><span>{{ labels[event.status]??event.status }} · {{ time(event.occurred_at||event.recorded_at) }}</span></div><p>{{ event.summary }}</p><div v-if="event.kind==='analysis'||textDetail(event,'hypothesis')" :class="styles.hypothesis"><span :class="styles.eyebrow">模型建议</span><p>{{ textDetail(event,'hypothesis')||textDetail(event,'reason')||event.summary }}</p></div><p v-if="textDetail(event,'tool_name')">工具：{{ toolLabels[String(event.details.tool_name)]??event.details.tool_name }}</p><p v-if="textDetail(event,'reason')&&event.kind!=='analysis'" :class="styles.muted">{{ textDetail(event,'reason') }}</p><details v-if="auditDetails(event).length" :class="styles.identity"><summary>工具与判断详情</summary><dl><div v-for="detail in auditDetails(event)" :key="detail.key"><dt>{{ detail.label }}</dt><dd>{{ detail.value }}</dd></div></dl></details><p :class="styles.muted">{{ domainLabels[event.evidence_domain]??'证据来源未知' }}{{ event.occurred_at?'':' · 发生时间未知，按记录时间展示' }}</p></li></ol>
        <nav v-if="events.data&&events.data.total>25" :class="styles.actions" aria-label="Pi 事件分页"><button class="btn btn-quiet" :disabled="eventOffset===0" @click="eventOffset-=25">上一页事件</button><span>{{ eventOffset+1 }}–{{ Math.min(eventOffset+25,events.data.total) }} / {{ events.data.total }}</span><button class="btn btn-quiet" :disabled="eventOffset+25>=events.data.total" @click="eventOffset+=25">下一页事件</button></nav>
      </section>
    </template>
    <NativeDialog v-if="modal" :on-close="()=>{modal=null}" :class="styles.dialog" aria-labelledby="publish-heading"><h2 id="publish-heading">确认发布镜像</h2><p>将发布以下精确产物，并在宿主核验实际运行版本后进入观察。未完成核验时保留未确认状态。</p><dl :class="styles.identity"><div><dt>镜像</dt><dd>{{ modal.candidate.image_id }}</dd></div><div><dt>产物摘要</dt><dd>{{ modal.candidate.package_sha256 }}</dd></div><div><dt>变更文件</dt><dd>{{ modal.candidate.changes.length }} 个</dd></div></dl><p>此操作发布镜像，GitHub 源码同步另行处理。</p><div :class="styles.actions"><button class="btn btn-quiet" autofocus @click="modal=null">返回核对</button><button class="btn btn-primary" :disabled="busy" @click="decide('publish')">确认发布镜像</button></div></NativeDialog>
  </section>
</template>
