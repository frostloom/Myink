import type { AgentRun, TaskStatus } from '../types'

export interface DisplayRun extends AgentRun {
  /** 旧记录没有独立 route 节点时，由其实际后继步骤推导，仅用于界面展示。 */
  derived?: boolean
}

/**
 * 一次完整生成从 load_state 开始。恢复、重写或再次写作复用 task_id 时会留下新的
 * load_state；按此切组，避免把多次生成画成一条连续长流程。
 */
export function groupFlowAttempts<T extends { node: string }>(runs: T[]): T[][] {
  const groups: T[][] = []
  let current: T[] = []
  let hasLoadState = false
  for (const run of runs) {
    if (run.node === 'load_state' && hasLoadState) {
      groups.push(current)
      current = []
      hasLoadState = false
    }
    current.push(run)
    if (run.node === 'load_state') hasLoadState = true
  }
  if (current.length > 0) groups.push(current)
  return groups
}

/**
 * 同一逻辑阶段可能同时留下节点包装和模型调用两条相邻记录。
 * 界面将它们合并并汇总计量，保留最新的详情和错误。
 */
export function compactFlowRuns(runs: AgentRun[], status: TaskStatus | null): DisplayRun[] {
  const compact: DisplayRun[] = []
  for (const run of runs) {
    const previous = compact.at(-1)
    if (previous?.node === run.node) {
      previous.input_tokens += run.input_tokens
      previous.output_tokens += run.output_tokens
      previous.duration_ms += run.duration_ms
      previous.cost_est += run.cost_est
      previous.retry_count += run.retry_count
      previous.cache_hit = previous.cache_hit || run.cache_hit
      previous.degraded = previous.degraded || run.degraded
      previous.error = run.error ?? previous.error
      if (run.model_id) previous.model_id = run.model_id
      if (run.detail) previous.detail = { ...(previous.detail ?? {}), ...run.detail }
      continue
    }
    compact.push({ ...run, detail: run.detail ? { ...run.detail } : run.detail })
  }

  const result: DisplayRun[] = []
  for (let index = 0; index < compact.length; index += 1) {
    const run = compact[index]
    const next = compact[index + 1]
    result.push(run)
    if (run.node !== 'audit' || next?.node === 'route') continue
    const route = deriveHistoricalRoute(run, next, status)
    if (!route) continue
    result.push({
      task_id: run.task_id,
      node: 'route',
      model_id: null,
      input_tokens: 0,
      output_tokens: 0,
      cache_hit: false,
      duration_ms: 0,
      cost_est: 0,
      retry_count: 0,
      degraded: false,
      error: null,
      detail: { route },
      derived: true,
    })
  }
  return result
}

/**
 * 进行中的阶段（Plan/正文已开始流式、节点尚未落库）先于 agent_runs 到达：产物既未 complete
 * 也未 failed 即表示该节点仍在执行。右栏据此补一条「正在执行」步骤——否则计划跑完后、写作
 * 完成前，右栏只能显示最后一次落库结果，看起来一直停在 plan。
 *
 * 写作阶段（stage=write）同时被 write 与 revise 复用：此前已落库过 write 说明本轮是重写。
 */
export function liveStageNode(
  runs: Array<{ node: string }>,
  plan: { complete: boolean; failed: boolean } | null,
  write: { complete: boolean; failed: boolean } | null,
): string | null {
  if (write && !write.complete && !write.failed) {
    return runs.some((run) => run.node === 'write') ? 'revise' : 'write'
  }
  if (plan && !plan.complete && !plan.failed) return 'plan_chapter'
  return null
}

/**
 * 短篇四步在环形进度上的位置。权重不等：成稿是整篇一次写，占大头；审稿是小调用；
 * 改稿只在审稿要求时才发生。补写常常根本不跑（成稿没缺章就跳过），跳过就不进这张表——
 * 前端只认后端报的阶段名，不按「上一步完了该轮到谁」推。阶段名本身走 `nodeLabel`，
 * 这里不另立一套说法。
 */
const SHORT_STAGES: Record<string, { from: number; to: number }> = {
  short_write: { from: 0, to: 70 },
  short_continue: { from: 70, to: 80 },
  short_review: { from: 80, to: 92 },
  short_revise: { from: 92, to: 100 },
}

export interface ShortStageProgress {
  /** 0–1，直接喂 RingProgress。 */
  value: number
  /** 此刻在哪一步（`nodeLabel` 可直接渲染）。 */
  stage: string
  /** 这一步没有字数可报（审稿/补写）：环只转，不指刻度。 */
  indeterminate: boolean
}

/**
 * 短篇的实时阶段进度（`short_runner._Progress` 那条 event=progress）。
 *
 * 每一步开始都会报一条，成稿/改稿随后按累计字数续报。没有字数的那几步停在阶段起点——
 * 刻度会停，但阶段名是对的，环在转，用户看得出是在审稿而不是卡死。
 */
export function shortStageProgress(
  state: { stage: string; current: number; total: number } | null | undefined,
): ShortStageProgress | null {
  const stage = state ? SHORT_STAGES[state.stage] : undefined
  if (!state || !stage) return null
  const ratio = state.total > 0 ? Math.min(state.current / state.total, 1) : 0
  return {
    value: (stage.from + (stage.to - stage.from) * ratio) / 100,
    stage: state.stage,
    indeterminate: state.total <= 0,
  }
}

function deriveHistoricalRoute(run: AgentRun, next: AgentRun | undefined, status: TaskStatus | null): string | null {
  if (next?.node === 'persist' || next?.node === 'summarize') return 'persist'
  if (next?.node === 'revise') return 'revise'
  if (next?.node === 'patch') return 'patch'
  if (next?.node === 'reset_replan' || next?.node === 'plan_chapter') return 'replan_chapter'
  if (next?.node === 'batch_plan') return 'replan_batch'
  if (status === 'awaiting_plan') return 'plan_review'
  if (status === 'awaiting_review') return 'needs_review'
  if (status === 'failed') return 'fail'
  const verdict = run.detail?.audit_verdict?.verdict
  return verdict === 'pass' ? 'persist' : verdict === 'rewrite' ? 'revise' : verdict === 'replan' ? 'replan_chapter' : null
}
