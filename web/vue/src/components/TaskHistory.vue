<script lang="ts">
import type { PropType } from 'vue'
import { defineComponent, h, Fragment, ref, computed, watch } from 'vue'

import TaskBudgetPanel from "./TaskBudgetPanel.vue";
import { api } from "../../../src/lib/api";
import { formatApiError } from "../../../src/lib/apiError";
import { taskStatusLabel, taskStatusTone, taskTypeLabel } from "../../../src/lib/labels";
import { chapterRunsOf } from "../../../src/lib/taskChapter";
import type { AgentRun, TaskDetail, TaskStatus, TaskSummary } from "../../../src/types";
import RunNodeCard from "./RunNodeCard.vue";
import StatusBadge from "./StatusBadge.vue";
import styles from "../../../src/components/TaskHistory.module.css";
interface Props {
    projectId: string;
    /** 当前活动任务（SSE 实时时间线）；命中该行高亮「进行中」 */
    activeTaskId: string | null;
    /** 右栏按章过滤（§11）：非空时列表只列覆盖该章的任务，展开详情也按章切片 */
    selectedSeq: number | null;
}
type BatchAction = 'pause' | 'resume' | 'cancel';
const ACTION_LABEL: Record<BatchAction, string> = {
    pause: '暂停',
    resume: '续跑',
    cancel: '取消',
};
// 可控制状态（同 TaskTimeline STATUS_ACTIONS 口径；awaiting_review 确认候选后 resume 放行）
const STATUS_ACTIONS: Partial<Record<TaskStatus, BatchAction[]>> = {
    paused: ['resume', 'cancel'],
    queued: ['pause', 'cancel'],
    running: ['pause', 'cancel'],
    awaiting_review: ['resume'],
};
/** 行目标文案：批次 → N 章 + i/N；单章 → 第 N 章 */
function targetLabel(t: TaskSummary): string {
    if (t.task_type === 'batch_generate') {
        const size = t.batch_size ?? 0;
        const current = t.batch_current;
        return `批次${size > 0 ? ` ${size} 章` : ''}${current !== null && size > 0 ? ` · ${current}/${size}` : ''}`;
    }
    return t.chapter_seq !== null ? `第 ${t.chapter_seq} 章` : '';
}
export const TaskHistory = defineComponent({
    name: "TaskHistory",
    props: { projectId: { type: String as PropType<(Props)["projectId"]>, required: true }, activeTaskId: { type: String as PropType<(Props)["activeTaskId"]>, required: true }, selectedSeq: { type: Number as PropType<(Props)["selectedSeq"]>, required: true } },
    setup(props: Props) {
        const projectId = computed(() => props.projectId);
        const activeTaskId = computed(() => props.activeTaskId);
        const selectedSeq = computed(() => props.selectedSeq);
        const open = ref(true), setOpen = (next: typeof open.value | ((current: typeof open.value) => typeof open.value)) => open.value = typeof next === "function" ? next(open.value) : next;
        const tasks = ref<TaskSummary[]>([]), setTasks = (next: typeof tasks.value | ((current: typeof tasks.value) => typeof tasks.value)) => tasks.value = typeof next === "function" ? next(tasks.value) : next;
        const openTaskId = ref<string | null>(null), setOpenTaskId = (next: typeof openTaskId.value | ((current: typeof openTaskId.value) => typeof openTaskId.value)) => openTaskId.value = typeof next === "function" ? next(openTaskId.value) : next;
        const detail = ref<TaskDetail | null>(null), setDetail = (next: typeof detail.value | ((current: typeof detail.value) => typeof detail.value)) => detail.value = typeof next === "function" ? next(detail.value) : next;
        const detailLoading = ref(false), setDetailLoading = (next: typeof detailLoading.value | ((current: typeof detailLoading.value) => typeof detailLoading.value)) => detailLoading.value = typeof next === "function" ? next(detailLoading.value) : next;
        const error = ref<string | null>(null), setError = (next: typeof error.value | ((current: typeof error.value) => typeof error.value)) => error.value = typeof next === "function" ? next(error.value) : next;
        const ctrl = ref<BatchAction | null>(null), setCtrl = (next: typeof ctrl.value | ((current: typeof ctrl.value) => typeof ctrl.value)) => ctrl.value = typeof next === "function" ? next(ctrl.value) : next;
        // 切书：清展开/详情 + 重载历史（新书任务列表自动加载，根因 2 解决）
        watch(() => [projectId.value], (_next, _prev, onCleanup) => {
            let alive = true;
            setTasks([]);
            setOpenTaskId(null);
            setDetail(null);
            api.listTasks(projectId.value, selectedSeq.value ?? undefined)
                .then((list) => { if (alive)
                setTasks(list); })
                .catch(() => { if (alive)
                setTasks([]); });
            onCleanup(() => { alive = false; });
        }, { immediate: true, flush: "post" });
        // 新任务入队/终态 → 历史追加当前任务；选中章变化 → 列表按章重拉（§11 右栏按章过滤）。
        // 实时流转仍走上方 TaskTimeline。
        watch(() => [activeTaskId.value, projectId.value, selectedSeq.value], (_next, _prev, onCleanup) => {
            let alive = true;
            api.listTasks(projectId.value, selectedSeq.value ?? undefined)
                .then((list) => { if (alive)
                setTasks(list); })
                .catch(() => { if (alive)
                setTasks([]); });
            onCleanup(() => { alive = false; });
        }, { immediate: true, flush: "post" });
        // 展开/收起一行：展开时拉任务详情（含 runs 流转记录）
        async function toggleDetail(tid: string) {
            if (openTaskId.value === tid) {
                setOpenTaskId(null);
                setDetail(null);
                return;
            }
            setOpenTaskId(tid);
            setDetail(null);
            setDetailLoading(true);
            setError(null);
            try {
                setDetail(await api.getTask(tid));
            }
            catch (err) {
                setError(formatApiError(err, '详情加载失败'));
            }
            finally {
                setDetailLoading(false);
            }
        }
        // 控制（pause/resume/cancel）：外部控制不发 SSE，成功后主动拉新详情 + 刷新列表
        async function control(action: BatchAction, tid: string) {
            if (ctrl.value)
                return;
            setCtrl(action);
            setError(null);
            try {
                if (action === 'pause')
                    await api.pauseBatch(tid);
                else if (action === 'resume')
                    await api.resumeBatch(tid);
                else
                    await api.cancelBatch(tid);
                setDetail(await api.getTask(tid));
                const list = await api.listTasks(projectId.value, selectedSeq.value ?? undefined).catch(() => []);
                setTasks(list);
            }
            catch (err) {
                setError(formatApiError(err, '操作失败'));
            }
            finally {
                setCtrl(null);
            }
        }
        const detailActions = computed(() => detail.value ? (STATUS_ACTIONS[detail.value.status] ?? []).filter(a => !(a === 'resume' && detail.value?.budget?.pause_reason)) : []);
        return () => {
            return (h("section", { "class": `panel ${styles.panel}` }, [h("header", { "class": styles.head }, [h("button", { "type": "button", "class": styles.toggle, "onClick": () => setOpen((o) => !o) }, [h("span", { "class": styles.title }, ["任务"]), tasks.value.length > 0 && h("span", { "class": "badge badge-hint" }, [tasks.value.length]), h("span", { "class": styles.caret }, [open.value ? '▾' : '▸'])])]), error.value && h("div", { "class": "banner banner-error" }, [error.value]), open.value && tasks.value.length === 0 && (h("p", { "class": "empty" }, ["尚无任务。发起生成后历史会出现在这里。"])), open.value && tasks.value.length > 0 && (h("ul", { "class": styles.list }, [tasks.value.map((t) => {
                        const expanded = openTaskId.value === t.task_id;
                        const active = t.task_id === activeTaskId.value;
                        return (h("li", { "key": t.task_id, "class": styles.item }, [h("button", { "type": "button", "class": styles.row, "onClick": () => void toggleDetail(t.task_id) }, [h(StatusBadge, { "tone": taskStatusTone(t.status) }, () => [taskStatusLabel(t.status)]), h("span", { "class": styles.type }, [taskTypeLabel(t.task_type)]), h("span", { "class": styles.target }, [targetLabel(t)]), t.cost_total > 0 && (h("span", { "class": styles.cost, "title": "任务总花费（节点 cost 合计，§6.8 成本透明）" }, ["总 ¥", t.cost_total.toFixed(2)])), active && h("span", { "class": styles.live }, ["进行中"]), h("span", { "class": styles.date }, [t.created_at ? new Date(t.created_at).toLocaleString('zh-CN') : '']), h("span", { "class": styles.caret }, [expanded ? '▾' : '▸'])]), t.error && h("p", { "class": styles.errorText }, [t.error]), expanded && (h("div", { "class": styles.detail }, [detailLoading.value ? (h("p", { "class": "empty" }, ["加载流转记录…"])) : detail.value ? ((() => {
                                    // 右栏按章过滤：列表已按章拉取，批次展开详情再按 :ch{seq} 切运行（单章全量）
                                    const shownRuns = chapterRunsOf(t.task_type, t.task_id, detail.value.runs, selectedSeq.value);
                                    const shownCost = shownRuns.reduce((s, r) => s + r.cost_est, 0);
                                    return (h(Fragment, null, [h(TaskBudgetPanel, { "key": detail.value!.task_id, "task": detail.value, "onResumed": () => { void api.getTask(detail.value!.task_id).then(setDetail).catch(e => setError(formatApiError(e))); void api.listTasks(projectId.value, selectedSeq.value ?? undefined).then(setTasks).catch(e => setError(formatApiError(e))); } }, () => []), h("div", { "class": styles.detailHead }, [selectedSeq.value !== null ? (shownCost > 0 && (h("span", { "class": styles.cost, "title": "该章运行成本（按选中章过滤，§6.8 成本透明）" }, ["第", selectedSeq.value, " 章 ¥", shownCost.toFixed(2)]))) : (detail.value.cost_total > 0 && (h("span", { "class": styles.cost }, ["总花费 ¥", detail.value.cost_total.toFixed(2)]))), detail.value.progress && (h("span", { "class": styles.progress }, [detail.value.progress.current, "/", detail.value.progress.total])), detailActions.value.length > 0 && (h("div", { "class": styles.controls }, [detailActions.value.map((a) => (h("button", { "key": a, "type": "button", "class": "btn btn-quiet", "disabled": ctrl.value !== null, "onClick": () => void control(a, t.task_id) }, [ctrl.value === a ? '处理中…' : ACTION_LABEL[a]]))), detail.value.status === 'awaiting_review' && (h("span", { "class": styles.hint }, ["候选待确认，处理完点续跑放行"]))]))]), shownRuns.length > 0 ? (h("div", { "class": styles.runs }, [shownRuns.map((r: AgentRun, i) => (h(RunNodeCard, { "key": `${r.node}-${i}`, "run": r }, () => [])))])) : (h("p", { "class": "empty" }, [selectedSeq.value !== null
                                                ? `第 ${selectedSeq.value} 章无流转记录（批次未推进到本章或尚未开始）。`
                                                : '无流转记录（任务未开始或尚未落库）。']))]));
                                })()) : (h("p", { "class": "empty" }, ["详情加载失败。"]))]))]));
                    })]))]));
        };
    }
});

export default TaskHistory

</script>
