// 任务进度状态机：SSE 实时节点流（fetch 客户端）→ 终态/410 过期回退 GET /tasks/:id 快照。
// 断线（网络中断 / 网关 30min 硬超时）指数退避重连，带 last_event_id 追平（Redis 流可重放）。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import { openSSE, type SSEEvent } from '../lib/sse'
import type { AgentRun, TaskStatus } from '../types'

export type TaskPhase =
  | 'idle'
  | 'connecting'
  | 'live'
  | 'reconnecting'
  | 'terminal'
  | 'expired'
  | 'error'

export interface NodeEvent {
  taskId: string
  node: string
  seenAt: number
}

export interface TaskEventState {
  phase: TaskPhase
  status: TaskStatus | null
  /** 实时节点流顺序（SSE 只带 node 名，无 token/cost 元数据） */
  nodes: NodeEvent[]
  /** 终态/过期后从 GET /tasks/:id 快照填充（含全部元数据） */
  runs: AgentRun[]
  /** 批次进度 i/N（快照权威值；实时用 nodes 的 persist 去重计数近似） */
  progress: { current: number; total: number } | null
  error: string | null
  lastEventId: string | null
  stop: () => void
  retry: () => void
  /** 外部控制（pause/resume/cancel）后主动拉 GET /tasks/:id 快照刷新状态/进度；
   *  若为终态（如取消成功）→ 停流并切 phase=terminal（外部控制不发 SSE 事件，流不会自终） */
  refresh: () => void
}

export function isTerminalPhase(phase: TaskPhase): boolean {
  return phase === 'terminal' || phase === 'expired' || phase === 'error'
}

export function useTaskEvents(
  taskId: string | null,
  opts?: { batchTotal?: number; resumeKey?: number | null },
): TaskEventState {
  const [phase, setPhase] = useState<TaskPhase>('idle')
  const [status, setStatus] = useState<TaskStatus | null>(null)
  const [nodes, setNodes] = useState<NodeEvent[]>([])
  const [runs, setRuns] = useState<AgentRun[]>([])
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastEventId, setLastEventId] = useState<string | null>(null)

  // 累积态放 ref，重连闭包不读旧值
  const abortRef = useRef<AbortController | null>(null)
  const nodesRef = useRef<NodeEvent[]>([])
  const lastIdRef = useRef<string | null>(null)

  // SSE 终态判定与网关 sse.go 一致（status∈{done,failed,awaiting_review,cancelled} 关流）
  const TERMINAL_STATUS: TaskStatus[] = ['done', 'failed', 'cancelled', 'awaiting_review']

  const fetchSnapshot = useCallback(async (tid: string, forceTerminal = false) => {
    try {
      const detail = await api.getTask(tid)
      setRuns(detail.runs)
      setStatus(detail.status)
      setError(detail.error)
      if (detail.progress) setProgress(detail.progress)
      if (forceTerminal && TERMINAL_STATUS.includes(detail.status)) {
        // 外部取消：流不会自己终态 → 主动停流；connect 循环在 openSSE 返回后先查
        // controller.signal.aborted 早退，不会把 phase 误写成 error
        abortRef.current?.abort()
        setPhase('terminal')
      }
    } catch {
      // 任务在途（入队→DB 物化窗口内 404）时快照失败：保留现场，交手动 retry
    }
  }, [])

  const refresh = useCallback(() => {
    if (taskId) void fetchSnapshot(taskId, true)
  }, [taskId, fetchSnapshot])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    nodesRef.current = []
    lastIdRef.current = null
    setNodes([])
    setStatus(null)
    setRuns([])
    setProgress(null)
    setError(null)
    setLastEventId(null)
    setPhase('idle')
  }, [])

  const connect = useCallback(
    async (tid: string) => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      const onEvent = (ev: SSEEvent) => {
        if (ev.status) {
          setStatus(ev.status as TaskStatus)
        }
        if (ev.node) {
          nodesRef.current = [
            ...nodesRef.current,
            { taskId: ev.task_id, node: ev.node, seenAt: Date.now() },
          ]
          setNodes(nodesRef.current)
        }
      }

      let attempt = 0
      setPhase('connecting')
      for (;;) {
        if (controller.signal.aborted) return
        const result = await openSSE(`/api/v1/tasks/${tid}/events`, onEvent, {
          lastEventId: lastIdRef.current ?? undefined,
          signal: controller.signal,
          onLastId: (id) => {
            lastIdRef.current = id
            setLastEventId(id)
          },
        })
        if (controller.signal.aborted) return

        switch (result.reason) {
          case 'terminal':
            setPhase('terminal')
            void fetchSnapshot(tid)
            return
          case 'expired':
            // 流过期（Redis key 被裁剪）→ 回退 GET 快照
            setPhase('expired')
            void fetchSnapshot(tid)
            return
          case 'unauthorized':
            // token.ts 已派发 401 登出事件，路由守卫自动跳登录
            setPhase('error')
            return
          case 'network':
          case 'eof':
            // 未达终态但流结束 → 指数退避重连（last_event_id 追平）
            setPhase('reconnecting')
            attempt += 1
            const delay = Math.min(8000, 1000 * 2 ** Math.min(attempt - 1, 3))
            await new Promise((r) => setTimeout(r, delay))
            continue
          case 'error':
          case 'aborted':
            setPhase('error')
            return
        }
      }
    },
    [fetchSnapshot],
  )

  const retry = useCallback(() => {
    if (taskId) void connect(taskId)
  }, [taskId, connect])

  // 实时批次 i/N：SSE 只带节点名，用 persist 节点章级 task_id 去重计数（与 Python
  // progress.current 口径一致，§阶段2）；快照到达后以快照为权威。
  const liveCurrent = useMemo(
    () => new Set(nodes.filter((n) => n.node === 'persist').map((n) => n.taskId)).size,
    [nodes],
  )
  const effectiveProgress =
    progress ?? (opts?.batchTotal ? { current: liveCurrent, total: opts.batchTotal } : null)

  useEffect(() => {
    if (!taskId) {
      stop()
      return
    }
    void connect(taskId)
    return () => abortRef.current?.abort()
    // taskId 变化或 resumeKey 变化才重连；stop/connect 闭包捕获最新 ref。
    // resumeKey：awaiting_review 终态关流后「放行本章」复用同一 task_id 续跑，
    // taskId 不变不会触发重连，靠 resumeKey 自增强制重开流（last_event_id 追平）。
  }, [taskId, connect, stop, opts?.resumeKey])

  return {
    phase,
    status,
    nodes,
    runs,
    progress: effectiveProgress,
    error,
    lastEventId,
    stop,
    retry,
    refresh,
  }
}
