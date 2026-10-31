import { authenticatedGet, authenticatedSend } from './api'
import type { AdminPage } from './adminApi'

export interface PiChange { path: string; category: string; added: number | null; deleted: number | null }
export interface PiVersion { source_commit: string | null; candidate_sha256: string | null; image_ids: Record<string,string>; deployment_id?: string | null; controller_sha256?: string | null; sdk_version?: string | null; policy_sha256?: string | null }
export interface PiOperation { request_id:string; actor_id:string; cycle_id:string; package_sha256:string; decision:'publish'|'defer'; status:'recording'|'queued'|'running'|'deferred'|'succeeded'|'failed'|'uncertain'; created_at:string; completed_at:string|null; reason:string|null }
export interface PiCandidate {
 package_sha256:string; image_id:string; source_sha256:string; comparison_sha256:string; baseline_sha256:string; changes:PiChange[]; publication_available:boolean
 evaluation:{sdk_verified:boolean;checker:{passed:boolean;tests:number|null;failures:number|null;errors:number|null;skipped:number|null};independent_review:{kind:string;sha256:string};model_requests:number;known_cost_microyuan:number|null;tool_count:number;evidence_domain:string;online_improvement_proven:boolean}
 comparison:{anchor:string;day_offset:number;status:string;online_improvement_proven:boolean;test_cases:string[]}
}
export interface PiStatus {schema_version:1;mode:'ACTUAL'|'SIMULATED';observed_at:string;phase:'idle'|'preparing'|'awaiting_approval'|'awaiting_deployment'|'observing'|'blocked';cycle_id:string|null;task_id:string|null;package_sha256:string|null;candidate:PiCandidate|null;deployment:{deployment_id:string;deployed_at:string;image_id:string;source_sha256:string;comparison_sha256:string}|null;next_assessment_at:string|null;latest_operation:PiOperation|null;executor:{service_state:string;timer_state:string;last_result:string|null;next_check:string|null}}
export interface PiDecision {request_id:string;cycle_id:string;package_sha256:string;image_id:string;source_sha256:string;comparison_sha256:string;decision:'publish'|'defer'}
export interface PiRun {run_id:string;event_count:number;days:string[]}
export interface PiTestPlan {test_id:string;scheduled_for:string;target_run_id:string;target_version_sha256:string|null;criterion:string;kind:string;status:string;result:{status:string;occurred_at:string;evidence_domain:string}|null}
export interface PiEvent {event_sha256:string;sequence:number;kind:string;status:string;run_id:string;mode:string;evidence_domain:string;occurred_at:string|null;recorded_at:string;summary:string;details:Record<string,string|number|boolean|null>;version:PiVersion;changes:PiChange[];followups:PiTestPlan[]}
export interface PiDaily {schema_version:1;authority:'audit_only';day:string;timezone:string;event_count:number;unknown_occurrence_count:number;release_state:string;versions:PiVersion[];change_scope:Array<PiChange & {candidate_sha256:string|null;source_commit:string|null}>;next_tests:PiTestPlan[];known_cost_microyuan:number|null;observed_samples:number|null;sample_windows:Array<{run_id:string;observed_samples:number|null;window:string|null;event_sha256:string}>}
type Paging={limit?:number;offset?:number}
function query(values:Array<[string,string|number|undefined]>) {const params=new URLSearchParams();for(const [k,v] of values)if(v!==undefined&&v!=='')params.set(k,String(v));return `?${params}`}
export const piApi={
 status:(token:string,signal?:AbortSignal)=>authenticatedGet<PiStatus>('/admin/pi/status',token,signal),
 runs:(token:string,filters:Paging & {day?:string}={},signal?:AbortSignal)=>authenticatedGet<AdminPage<PiRun>>(`/admin/pi/runs${query([['day',filters.day],['limit',filters.limit??25],['offset',filters.offset??0]])}`,token,signal),
 events:(token:string,filters:Paging & {runId:string;kind?:string},signal?:AbortSignal)=>authenticatedGet<AdminPage<PiEvent>>(`/admin/pi/events${query([['run_id',filters.runId],['kind',filters.kind],['limit',filters.limit??25],['offset',filters.offset??0]])}`,token,signal),
 daily:(token:string,day:string,signal?:AbortSignal)=>authenticatedGet<PiDaily>(`/admin/pi/daily${query([['day',day]])}`,token,signal),
 enhancements:(token:string,filters:Paging={},signal?:AbortSignal)=>authenticatedGet<AdminPage<PiEvent>>(`/admin/pi/enhancements${query([['limit',filters.limit??25],['offset',filters.offset??0]])}`,token,signal),
 operation:(token:string,id:string,signal?:AbortSignal)=>authenticatedGet<PiOperation>(`/admin/pi/operations/${encodeURIComponent(id)}`,token,signal),
 decide:(token:string,body:PiDecision,signal?:AbortSignal)=>authenticatedSend<PiOperation>('POST','/admin/pi/decisions',token,body,signal),
}
