<script lang="ts">
import type { PropType } from 'vue'
import { defineComponent, h, Fragment, ref, computed } from 'vue'

import TaskBudgetPanel from "./TaskBudgetPanel.vue";
import { api } from "../../../src/lib/api";
import { formatApiError, formatErrorText } from "../../../src/lib/apiError";
import { formatDuration } from "../../../src/lib/duration";
import { nodeLabel, taskStatusLabel, taskStatusTone } from "../../../src/lib/labels";
import { compactFlowRuns, groupFlowAttempts } from "../../../src/lib/taskFlow";
import type { TaskPhase } from "../composables/useTaskEvents";
import type { AgentRun, TaskStatus, TaskBudgetView } from "../../../src/types";
import styles from "../../../src/components/TaskTimeline.module.css";
export interface TaskTimelineProps {
    budget?: TaskBudgetView | null;
    taskId: string | null;
    phase: TaskPhase;
    status: TaskStatus | null;
    nodes: Array<{
        taskId: string;
        node: string;
        seenAt: number;
    }>;
    runs: AgentRun[];
    /** 正在执行、尚无 agent_runs 记录的节点（由产物流推导）：补一条实时步骤，避免停在上一节点 */
    liveNode?: string | null;
    progress: {
        current: number;
        total: number;
    } | null;
    chapterSeq?: number | null;
    error: string | null;
    onRetry: () => void;
    canControl?: boolean;
    refresh: () => void;
}
const PHASE_LABEL: Record<TaskPhase, string> = {
    idle: '空闲',
    connecting: '连接中',
    live: '执行中',
    reconnecting: '重连中',
    terminal: '已结束',
    expired: '记录已归档',
    error: '出错',
};
type BatchAction = 'pause' | 'resume' | 'cancel';
const ACTION_LABEL: Record<BatchAction, string> = {
    pause: '暂停',
    resume: '续跑',
    cancel: '取消',
};
const STATUS_ACTIONS: Partial<Record<TaskStatus, BatchAction[]>> = {
    paused: ['resume', 'cancel'],
    queued: ['pause', 'cancel'],
    running: ['pause', 'cancel'],
    awaiting_review: ['resume'],
};
const ROUTE_LABELS: Record<string, string> = {
    plan_review: '等待确认计划',
    persist: '通过，进入落库',
    revise: '重写并复审',
    patch: '局部修订并复审',
    replan_chapter: '重规划本章',
    replan_batch: '重规划批次',
    needs_review: '转人工确认',
    fail: '停止',
};
export const TaskTimeline = defineComponent({
    name: "TaskTimeline",
    props: { budget: { type: Object as PropType<(TaskTimelineProps)["budget"]>, required: false, default: undefined }, taskId: { type: String as PropType<(TaskTimelineProps)["taskId"]>, required: true }, phase: { type: String as PropType<(TaskTimelineProps)["phase"]>, required: true }, status: { type: String as PropType<(TaskTimelineProps)["status"]>, required: true }, nodes: { type: Array as PropType<(TaskTimelineProps)["nodes"]>, required: true }, runs: { type: Array as PropType<(TaskTimelineProps)["runs"]>, required: true }, liveNode: { type: String as PropType<(TaskTimelineProps)["liveNode"]>, required: false, default: undefined }, progress: { type: Object as PropType<(TaskTimelineProps)["progress"]>, required: true }, chapterSeq: { type: Number as PropType<(TaskTimelineProps)["chapterSeq"]>, required: false, default: undefined }, error: { type: String as PropType<(TaskTimelineProps)["error"]>, required: true }, onRetry: { type: Function as PropType<(TaskTimelineProps)["onRetry"]>, required: true }, canControl: { type: Boolean as PropType<(TaskTimelineProps)["canControl"]>, required: false, default: undefined }, refresh: { type: Function as PropType<(TaskTimelineProps)["refresh"]>, required: true } },
    setup(props: TaskTimelineProps) {
        const taskId = computed(() => props.taskId);
        const budget = computed(() => props.budget);
        const phase = computed(() => props.phase);
        const status = computed(() => props.status);
        const nodes = computed(() => props.nodes);
        const runs = computed(() => props.runs);
        const liveNode = computed(() => props.liveNode ?? null);
        const progress = computed(() => props.progress);
        const chapterSeq = computed(() => props.chapterSeq ?? null);
        const error = computed(() => props.error);
        const onRetry = computed(() => props.onRetry);
        const canControl = computed(() => props.canControl ?? false);
        const refresh = computed(() => props.refresh);
        const open = ref(true), setOpen = (next: typeof open.value | ((current: typeof open.value) => typeof open.value)) => open.value = typeof next === "function" ? next(open.value) : next;
        const ctrl = ref<BatchAction | null>(null), setCtrl = (next: typeof ctrl.value | ((current: typeof ctrl.value) => typeof ctrl.value)) => ctrl.value = typeof next === "function" ? next(ctrl.value) : next;
        const ctrlError = ref<string | null>(null), setCtrlError = (next: typeof ctrlError.value | ((current: typeof ctrlError.value) => typeof ctrlError.value)) => ctrlError.value = typeof next === "function" ? next(ctrlError.value) : next;
        const attempts = computed(() => groupFlowAttempts(runs.value).map((attemptRuns) => ({
            rawRuns: attemptRuns,
            displayRuns: compactFlowRuns(attemptRuns, status.value),
        })));
        const displayRunCount = computed(() => attempts.value.reduce((sum, attempt) => sum + attempt.displayRuns.length, 0));
        const displayNodes = computed(() => nodes.value.filter((node, index) => index === 0 || node.node !== nodes.value[index - 1].node));
        const renderedTail = computed(() => attempts.value.length > 0
            ? attempts.value.at(-1)?.displayRuns.at(-1)?.node
            : displayNodes.value.at(-1)?.node);
        const pendingNode = computed(() => liveNode.value && liveNode.value !== renderedTail.value ? liveNode.value : null);
        const totalCost = computed(() => runs.value.reduce((sum, run) => sum + run.cost_est, 0));
        const totalDuration = computed(() => runs.value.reduce((sum, run) => sum + run.duration_ms, 0));
        const actions = computed(() => canControl.value && status.value ? (STATUS_ACTIONS[status.value] ?? []).filter(a => !(a === 'resume' && budget.value?.pause_reason)) : []);
        const tid = computed(() => taskId.value);
        async function control(action: BatchAction) {
            if (!tid.value || ctrl.value)
                return;
            setCtrl(action);
            setCtrlError(null);
            try {
                if (action === 'pause')
                    await api.pauseBatch(tid.value);
                else if (action === 'resume')
                    await api.resumeBatch(tid.value);
                else
                    await api.cancelBatch(tid.value);
            }
            catch (err) {
                setCtrlError(formatApiError(err, '操作失败'));
            }
            finally {
                setCtrl(null);
                refresh.value();
            }
        }
        const tone = computed(() => status.value ? taskStatusTone(status.value) : phaseTone(phase.value));
        const label = computed(() => status.value ? taskStatusLabel(status.value) : PHASE_LABEL[phase.value]);
        return () => {
            return (h("section", { "class": `panel ${styles.panel}`, "aria-label": "章节状态流转" }, [h("header", { "class": styles.head }, [h("button", { "type": "button", "class": styles.toggle, "onClick": () => setOpen((value) => !value), "aria-expanded": open.value }, [h("span", { "class": styles.headingGroup }, [h("span", { "class": styles.title }, ["章节流转"]), chapterSeq.value !== null && h("span", { "class": styles.chapter }, ["第 ", chapterSeq.value, " 章"])]), h("span", { "class": styles.headerMeta }, [h("span", { "class": `badge badge-${tone.value}` }, [label.value]), taskId.value && h("span", { "class": styles.cost }, ["¥", totalCost.value.toFixed(4)]), h("span", { "class": styles.caret }, [open.value ? '▾' : '▸'])])])]), open.value && (h("div", { "class": styles.body }, [taskId.value && status.value && h(TaskBudgetPanel, { "detailsCollapsed": true, "key": taskId.value, "task": { task_id: taskId.value, status: status.value, budget: budget.value }, "onResumed": refresh.value }, () => []), !taskId.value ? (h("p", { "class": "empty" }, ["本章还没有生成记录。"])) : (h(Fragment, null, [h("div", { "class": styles.summary }, [h("span", {}, [attempts.value.length > 0
                                    ? `${attempts.value.length} 次生成 · ${displayRunCount.value} 个阶段`
                                    : `本次 ${displayNodes.value.length + (pendingNode.value ? 1 : 0)} 个阶段`]), totalDuration.value > 0 && h("span", {}, [formatDuration(totalDuration.value)]), progress.value && h("span", {}, ["批次 ", progress.value.current, "/", progress.value.total])]), error.value && h("div", { "class": "banner banner-error" }, [formatErrorText(error.value, undefined, error.value)]), attempts.value.length > 0 ? (h("div", { "class": styles.attemptList }, [attempts.value.map((attempt, attemptIndex) => {
                                const attemptCost = attempt.rawRuns.reduce((sum, run) => sum + run.cost_est, 0);
                                const attemptDuration = attempt.rawRuns.reduce((sum, run) => sum + run.duration_ms, 0);
                                const attemptTokens = attempt.rawRuns.reduce((sum, run) => sum + run.input_tokens + run.output_tokens, 0);
                                return (h("section", { "key": attemptIndex, "class": styles.attempt, "aria-label": `第 ${attemptIndex + 1} 次生成` }, [h("div", { "class": styles.attemptHead }, [h("strong", {}, ["第 ", attemptIndex + 1, " 次生成"]), h("span", {}, [attempt.displayRuns.length, " 个阶段"])]), h("div", { "class": styles.attemptSummary }, [h("span", {}, [formatDuration(attemptDuration)]), h("span", {}, ["¥", attemptCost.toFixed(4)]), h("span", {}, [attemptTokens.toLocaleString('zh-CN'), " Token"])]), h("ol", { "class": styles.flow }, [attempt.displayRuns.map((run, index) => (h("li", { "key": `${run.node}-${index}`, "class": styles.step }, [h("span", { "class": `${styles.dot} ${run.error ? styles.dotError : ''}` }, []), h("div", { "class": styles.stepMain }, [h("div", { "class": styles.stepHead }, [h("strong", {}, [nodeLabel(run.node)]), run.detail?.route && h("span", { "class": styles.route }, [ROUTE_LABELS[run.detail.route] ?? run.detail.route, run.derived ? '（依据结果）' : ''])]), h("dl", { "class": styles.metrics }, [h("div", {}, [h("dt", {}, ["耗时"]), h("dd", {}, [formatDuration(run.duration_ms)])]), h("div", {}, [h("dt", {}, ["费用"]), h("dd", {}, ["¥", run.cost_est.toFixed(4)])]), h("div", {}, [h("dt", {}, ["Token"]), h("dd", {}, [(run.input_tokens + run.output_tokens).toLocaleString('zh-CN')])])]), run.retry_count > 0 && h("span", { "class": styles.retry }, ["重试 ", run.retry_count, " 次"]), run.node === 'patch' && run.detail?.patch_applied !== undefined && (h("span", { "class": styles.retry }, ["应用 ", run.detail.patch_applied, " · 跳过 ", run.detail.patch_skipped ?? 0])), run.detail?.patch_rejected_reason && h("p", { "class": styles.stepError }, [run.detail.patch_rejected_reason]), run.error && h("p", { "class": styles.stepError }, [formatErrorText(run.error, undefined, run.error)])])]))), attemptIndex === attempts.value.length - 1 && pendingNode.value && (h(LiveStep, { "node": pendingNode.value }, () => []))])]));
                            })])) : displayNodes.value.length > 0 || pendingNode.value ? (h("ol", { "class": styles.flow }, [displayNodes.value.map((node, index) => (h("li", { "key": `${node.seenAt}-${index}`, "class": styles.step }, [h("span", { "class": styles.dot }, []), h("div", { "class": styles.stepMain }, [h("div", { "class": styles.stepHead }, [h("strong", {}, [nodeLabel(node.node)])]), h("p", { "class": styles.liveState }, ["已完成"])])]))), pendingNode.value && h(LiveStep, { "node": pendingNode.value }, () => [])])) : (h("p", { "class": "empty" }, [emptyTaskMessage(status.value)])), actions.value.length > 0 && (h("div", { "class": styles.controls }, [actions.value.map((action) => (h("button", { "key": action, "type": "button", "class": "btn btn-quiet", "disabled": ctrl.value !== null, "onClick": () => void control(action) }, [ctrl.value === action ? '处理中…' : ACTION_LABEL[action]]))), ctrlError.value && h("span", { "class": styles.ctrlError }, [ctrlError.value])])), phase.value === 'expired' && h("button", { "type": "button", "class": "btn btn-quiet", "onClick": onRetry.value }, ["重新连接"])]))]))]));
        };
    }
});
function LiveStep({ node }: {
    node: string;
}) {
    return (h("li", { "class": styles.step }, [h("span", { "class": `${styles.dot} ${styles.dotLive}` }, []), h("div", { "class": styles.stepMain }, [h("div", { "class": styles.stepHead }, [h("strong", {}, [nodeLabel(node)])]), h("p", { "class": styles.liveState }, ["正在执行"])])]));
}
function emptyTaskMessage(status: TaskStatus | null): string {
    switch (status) {
        case 'failed': return '本次生成在记录流程前失败，请查看错误信息。';
        case 'cancelled': return '任务已取消，没有可显示的流程记录。';
        case 'done': return '任务已完成，但没有可显示的流程记录。';
        case 'awaiting_plan': return '章节计划正在等待确认。';
        case 'awaiting_review': return '任务正在等待人工处理，但没有可显示的流程记录。';
        case 'paused': return '任务已暂停，尚未记录执行步骤。';
        default: return '任务已创建，等待第一个步骤开始。';
    }
}
function phaseTone(phase: TaskPhase): string {
    switch (phase) {
        case 'live': return 'accent';
        case 'terminal': return 'success';
        case 'connecting':
        case 'reconnecting': return 'warning';
        case 'expired':
        case 'error': return 'error';
        case 'idle': return 'hint';
    }
}

export default TaskTimeline

</script>
