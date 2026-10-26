<script lang="ts">
import { useMemoryFormGuard } from "../composables/useMemoryFormGuard";
import type { PropType } from 'vue'
import { defineComponent, h, Fragment, ref, shallowRef, computed, useId } from 'vue'

import { api } from "../../../src/lib/api";
import { formatApiError } from "../../../src/lib/apiError";
import type { ResumeBudgetBody, TaskBudgetView, TaskStatus } from "../../../src/types";
import styles from "../../../src/components/TaskBudgetPanel.module.css";
const REASONS: Record<string, string> = { request_limit: '请求次数耗尽', cost_limit: '费用额度不足', time_limit: '运行时间耗尽', runtime_limit: '运行时间耗尽' };
export const TaskBudgetPanel = defineComponent({
    name: "TaskBudgetPanel",
    props: { task: { type: Object as PropType<({
        task: {
            task_id: string;
            status: TaskStatus;
            budget?: TaskBudgetView | null;
        };
        onResumed: () => void;
        detailsCollapsed?: boolean;
    })["task"]>, required: true }, onResumed: { type: Function as PropType<({
        task: {
            task_id: string;
            status: TaskStatus;
            budget?: TaskBudgetView | null;
        };
        onResumed: () => void;
        detailsCollapsed?: boolean;
    })["onResumed"]>, required: true }, detailsCollapsed: { type: Boolean as PropType<({
        task: {
            task_id: string;
            status: TaskStatus;
            budget?: TaskBudgetView | null;
        };
        onResumed: () => void;
        detailsCollapsed?: boolean;
    })["detailsCollapsed"]>, required: false, default: undefined } },
    setup(props: {
        task: {
            task_id: string;
            status: TaskStatus;
            budget?: TaskBudgetView | null;
        };
        onResumed: () => void;
        detailsCollapsed?: boolean;
    }) {
        const task = computed(() => props.task);
        const onResumed = computed(() => props.onResumed);
        const detailsCollapsed = computed(() => props.detailsCollapsed ?? false);
        const detailsOpen = ref(false), setDetailsOpen = (next: typeof detailsOpen.value | ((current: typeof detailsOpen.value) => typeof detailsOpen.value)) => detailsOpen.value = typeof next === "function" ? next(detailsOpen.value) : next;
        const detailsId = useId();
        const requests = ref(0), setRequests = (next: typeof requests.value | ((current: typeof requests.value) => typeof requests.value)) => requests.value = typeof next === "function" ? next(requests.value) : next;
        const yuan = ref(0), setYuan = (next: typeof yuan.value | ((current: typeof yuan.value) => typeof yuan.value)) => yuan.value = typeof next === "function" ? next(yuan.value) : next;
        const minutes = ref(0), setMinutes = (next: typeof minutes.value | ((current: typeof minutes.value) => typeof minutes.value)) => minutes.value = typeof next === "function" ? next(minutes.value) : next;
        const busy = ref(false), setBusy = (next: typeof busy.value | ((current: typeof busy.value) => typeof busy.value)) => busy.value = typeof next === "function" ? next(busy.value) : next;
        const error = ref<string | null>(null), setError = (next: typeof error.value | ((current: typeof error.value) => typeof error.value)) => error.value = typeof next === "function" ? next(error.value) : next;
        const pending = shallowRef<(ResumeBudgetBody | null) | null>(null);
        const inFlight = shallowRef(false);
        useMemoryFormGuard(() => requests.value !== 0 || yuan.value !== 0 || minutes.value !== 0 || pending.value !== null);
        const b = computed(() => task.value.budget);
        const uncertain = computed(() => task.value.status === 'queued' && b.value?.resume_publication === 'uncertain');
        const canExtend = computed(() => task.value.status === 'paused' && !!b.value?.pause_reason);
        const limit = (value: number, suffix = '') => value === 0 ? '不限' : `${value}${suffix}`;
        async function resume(repair = false) {
            if (inFlight.value)
                return;
            if (!pending.value) {
                if (!repair && (!Number.isSafeInteger(requests.value) || requests.value < 0 || requests.value > 2000000000 || !Number.isFinite(yuan.value) || yuan.value < 0 || yuan.value > 9000000000000 || Math.abs(yuan.value * 1e6 - Math.round(yuan.value * 1e6)) > 0.0001 || !Number.isSafeInteger(minutes.value * 60) || minutes.value < 0 || minutes.value * 60 > 9000000000000)) {
                    setError('请输入非负预算；请求次数和秒数必须为整数，费用最多六位小数。');
                    return;
                }
                pending.value = { operation_id: crypto.randomUUID(), add_requests: repair ? 0 : requests.value, add_cost_yuan: repair ? 0 : yuan.value, add_runtime_seconds: repair ? 0 : minutes.value * 60 };
            }
            inFlight.value = true;
            setBusy(true);
            setError(null);
            try {
                await api.resumeTask(task.value.task_id, pending.value);
                pending.value = null;
                onResumed.value();
            }
            catch (e) {
                setError(formatApiError(e));
                onResumed.value();
            }
            finally {
                inFlight.value = false;
                setBusy(false);
            }
        }
        return () => {
            if (!b.value)
                return null;
            return h("section", { "class": styles.panel, "aria-label": "任务预算" }, [detailsCollapsed.value && h("button", { "type": "button", "class": "btn btn-quiet", "aria-expanded": detailsOpen.value, "aria-controls": detailsId, "onClick": () => setDetailsOpen((open) => !open) }, [detailsOpen.value ? '收起预算详情' : '展开预算详情']), (!detailsCollapsed.value || detailsOpen.value) && h("div", { "id": detailsId }, [h("h3", {}, ["任务总预算"]), h("p", {}, ["请求 ", b.value.requests_used, " / ", limit(b.value.limits.max_requests), " · 费用 ¥", b.value.cost_used_yuan.toFixed(4), " / ", limit(b.value.limits.max_cost_yuan, ' 元'), " · 运行 ", Math.round(b.value.runtime_used_seconds), " 秒 / ", limit(b.value.limits.max_runtime_seconds, ' 秒')]), h("p", {}, ["未确认预留：¥", b.value.cost_reserved_yuan.toFixed(4), "。队列和暂停等待不计运行时间。"]), b.value.stage && h("p", {}, ["当前阶段：", b.value.stage])]), canExtend.value && h(Fragment, null, [h("p", {}, ["预算暂停：", REASONS[b.value?.pause_reason ?? ''] ?? b.value?.pause_reason, "。追加后从保存的位置继续，累计消耗保留。"]), h("div", { "class": styles.fields }, [h("label", {}, ["追加请求次数", h("input", { "class": "input", "type": "number", "min": "0", "step": "1", "value": requests.value, "disabled": busy.value || !!pending.value, "onInput": e => setRequests(Number((e.target as HTMLInputElement).value)) }, [])]), h("label", {}, ["追加费用（元）", h("input", { "class": "input", "type": "number", "min": "0", "step": "0.000001", "value": yuan.value, "disabled": busy.value || !!pending.value, "onInput": e => setYuan(Number((e.target as HTMLInputElement).value)) }, [])]), h("label", {}, ["追加运行时间（分钟）", h("input", { "class": "input", "type": "number", "min": "0", "step": "1", "value": minutes.value, "disabled": busy.value || !!pending.value, "onInput": e => setMinutes(Number((e.target as HTMLInputElement).value)) }, [])])]), h("button", { "class": "btn", "disabled": busy.value, "onClick": () => void resume() }, [busy.value ? '处理中…' : pending.value ? '重试本次恢复' : '追加并继续']), pending.value && !busy.value && h("button", { "class": "btn btn-quiet", "onClick": () => { pending.value = null; setError(null); } }, ["结束本次操作"])]), uncertain.value && h(Fragment, null, [h("p", {}, ["队列投递确认不明，额度已追加。先刷新状态；若仍排队，可重新投递，费用额度不会再次追加。"]), h("button", { "class": "btn", "disabled": busy.value, "onClick": () => { pending.value = null; void resume(true); } }, ["重新投递（不追加额度）"])]), error.value && h("p", { "role": "alert" }, [error.value])]);
        };
    }
});

export default TaskBudgetPanel

</script>
