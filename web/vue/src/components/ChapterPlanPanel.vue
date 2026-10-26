<script lang="ts">
import { useMemoryFormGuard } from "../composables/useMemoryFormGuard";
import type { PropType } from 'vue'
import { defineComponent, h, Fragment, ref, shallowRef, computed, onMounted, watch, onScopeDispose } from 'vue'

import type { ArtifactState } from "../composables/useTaskEvents";
import { api, ApiError } from "../../../src/lib/api";
import { formatApiError } from "../../../src/lib/apiError";
import { autoGrow } from "../../../src/lib/autoGrow";
import type { AgentRun, ChapterPlan, ChapterPlanCharacter, ChapterPlanScene, TaskStatus, } from "../../../src/types";
import styles from "../../../src/components/ChapterPlanPanel.module.css";
import StructuredTextField from "./StructuredTextField.vue";
interface Props {
    taskId: string | null;
    chapterSeq: number;
    status: TaskStatus | null;
    runs: AgentRun[];
    artifact: ArtifactState | null;
    onConfirmed: (taskId: string, chapterSeq: number) => void;
    onCancelled: (taskId: string, chapterSeq: number) => void;
}
const JSON_KEYS = new Set([
    'project_id', 'chapter_seq', 'goals', 'scenes', 'characters', 'hooks_to_plant',
    'hooks_to_resolve', 'expected_events', 'hard_constraints', 'transition', 'mode',
    'anchor_quote', 'pending_action', 'opening_beat', 'bridge', 'location_id',
    'participants', 'goal', 'time', 'character_id', 'expected_state',
]);
function isPlan(value: unknown): value is ChapterPlan {
    if (!value || typeof value !== 'object')
        return false;
    const plan = value as Partial<ChapterPlan>;
    return Array.isArray(plan.goals) && Array.isArray(plan.expected_events);
}
function clonePlan(plan: ChapterPlan): ChapterPlan {
    return JSON.parse(JSON.stringify(plan)) as ChapterPlan;
}
function streamPreview(raw: string): string {
    const values: string[] = [];
    for (const match of raw.matchAll(/"((?:\\.|[^"\\])*)"/g)) {
        try {
            const value = JSON.parse(`"${match[1]}"`) as string;
            if (value && !JSON_KEYS.has(value) && !/^[0-9a-f-]{30,}$/i.test(value))
                values.push(value);
        }
        catch { /* 不完整转义留给后续片段 */ }
    }
    return values.join(' · ');
}
function listText(items: string[]): string { return items.join('\n'); }
function textList(value: string): string[] {
    return value.split('\n').map((item) => item.trim()).filter(Boolean);
}
function stateText(state: Record<string, unknown>): string {
    return Object.entries(state).map(([key, value]) => `${key}：${String(value)}`).join('\n');
}
function textState(value: string): Record<string, string> {
    const state: Record<string, string> = {};
    for (const line of value.split('\n')) {
        const [key, ...rest] = line.split(/[：:]/);
        if (key?.trim() && rest.join(':').trim())
            state[key.trim()] = rest.join(':').trim();
    }
    return state;
}
function PlanReadOnly({ plan }: {
    plan: ChapterPlan;
}) {
    return h("div", { "class": styles.readonly }, [h("section", {}, [h("h4", {}, ["本章目标"]), h("ul", {}, [plan.goals.map((item, i) => h("li", { "key": i }, [item]))])]), plan.transition && h("section", {}, [h("h4", {}, ["章节衔接"]), h("p", {}, [h("b", {}, [plan.transition.mode]), " · ", plan.transition.opening_beat]), plan.transition.pending_action && h("p", {}, ["承接：", plan.transition.pending_action]), plan.transition.bridge && h("p", {}, ["过渡：", plan.transition.bridge])]), h("section", {}, [h("h4", {}, ["场景安排"]), h("ol", {}, [plan.scenes.map((scene, i) => h("li", { "key": i }, [h("b", {}, [scene.location_id]), scene.time ? ` · ${scene.time}` : '', "：", scene.goal, scene.participants.length > 0 && h("small", {}, [scene.participants.join('、')])]))])]), h("section", {}, [h("h4", {}, ["预期事件"]), h("ul", {}, [plan.expected_events.map((item, i) => h("li", { "key": i }, [item]))])]), (plan.hooks_to_plant.length > 0 || plan.hooks_to_resolve.length > 0) && h("section", {}, [h("h4", {}, ["伏笔"]), plan.hooks_to_plant.map((item, i) => h("p", { "key": `p${i}` }, ["埋设：", item])), plan.hooks_to_resolve.map((item, i) => h("p", { "key": `r${i}` }, ["回收：", item]))]), plan.hard_constraints.length > 0 && h("section", {}, [h("h4", {}, ["硬约束"]), h("ul", {}, [plan.hard_constraints.map((item, i) => h("li", { "key": i }, [item]))])])]);
}
function ListField({ label, value, onChange }: {
    label: string;
    value: string[];
    onChange: (next: string[]) => void;
}) {
    return h("label", { "class": styles.field }, [h("span", {}, [label, h("small", {}, ["每行一条"])]), h(StructuredTextField<string[]>, { "rows": 2, "value": value, "format": listText, "parse": textList, "onChange": onChange }, () => [])]);
}
// onChange carries parsed list values, not bubbling native DOM change events.
ListField.inheritAttrs = false;
export const PlanEditor = defineComponent({
    name: "PlanEditor",
    props: { plan: { type: Object as PropType<({
        plan: ChapterPlan;
        onChange: (next: ChapterPlan) => void;
    })["plan"]>, required: true }, onChange: { type: Function as PropType<({
        plan: ChapterPlan;
        onChange: (next: ChapterPlan) => void;
    })["onChange"]>, required: true } },
    setup(props: {
        plan: ChapterPlan;
        onChange: (next: ChapterPlan) => void;
    }) {
        const plan = computed(() => props.plan);
        const onChange = computed(() => props.onChange);
        const root = shallowRef<HTMLDivElement | null>(null);
        const update = <K extends keyof ChapterPlan>(key: K, value: ChapterPlan[K]) => onChange.value({ ...plan.value, [key]: value });
        const transition = computed(() => plan.value.transition ?? { mode: 'continue' as const, anchor_quote: '', pending_action: '', opening_beat: '', bridge: '' });
        const updateScene = (index: number, patch: Partial<ChapterPlanScene>) => {
            const scenes = plan.value.scenes.map((scene, i) => i === index ? { ...scene, ...patch } : scene);
            update('scenes', scenes);
        };
        const updateCharacter = (index: number, patch: Partial<ChapterPlanCharacter>) => {
            const characters = plan.value.characters.map((character, i) => i === index ? { ...character, ...patch } : character);
            update('characters', characters);
        };
        // 框随内容长高：整个计划正文只留 .body 那一条滚动条。
        // 框自己再滚，就成了「能滚的块里嵌一个能滚的框」。
        onMounted(() => { if (root.value) for (const el of root.value.querySelectorAll('textarea')) autoGrow(el) });
        watch(() => [plan.value], (_next, _prev, _onCleanup) => {
            if (!root.value)
                return;
            for (const el of root.value.querySelectorAll('textarea'))
                autoGrow(el);
        }, { immediate: true, flush: "post" });
        return () => {
            return h("div", { "class": styles.editor, "ref": root }, [h(ListField, { "label": "本章目标", "value": plan.value.goals, "onChange": (value) => update('goals', value) }, () => []), h("fieldset", { "class": styles.transition }, [h("legend", {}, ["与上一章的衔接"]), h("label", {}, [h("span", {}, ["方式"]), h("select", { "value": transition.value.mode, "onInput": (e) => update('transition', { ...transition.value, mode: (e.target as HTMLInputElement).value as typeof transition.value.mode }) }, [h("option", { "value": "continue" }, ["直接接续"]), h("option", { "value": "time_jump" }, ["时间跳转"]), h("option", { "value": "scene_cut" }, ["场景切换"]), h("option", { "value": "opening" }, ["首章开场"])])]), h("label", {}, [h("span", {}, ["上一章锚点"]), h("input", { "value": transition.value.anchor_quote, "onInput": (e) => update('transition', { ...transition.value, anchor_quote: (e.target as HTMLInputElement).value }) }, [])]), h("label", {}, [h("span", {}, ["未完成动作"]), h("input", { "value": transition.value.pending_action, "onInput": (e) => update('transition', { ...transition.value, pending_action: (e.target as HTMLInputElement).value }) }, [])]), h("label", {}, [h("span", {}, ["本章第一拍"]), h("textarea", { "rows": 2, "value": transition.value.opening_beat, "onInput": (e) => update('transition', { ...transition.value, opening_beat: (e.target as HTMLInputElement).value }) }, [])]), h("label", {}, [h("span", {}, ["过渡桥"]), h("textarea", { "rows": 2, "value": transition.value.bridge, "onInput": (e) => update('transition', { ...transition.value, bridge: (e.target as HTMLInputElement).value }) }, [])])]), h("fieldset", { "class": styles.collection }, [h("legend", {}, ["场景安排"]), plan.value.scenes.map((scene, index) => h("div", { "class": styles.item, "key": index }, [h("input", { "aria-label": `场景 ${index + 1} 地点`, "placeholder": "地点", "value": scene.location_id, "onInput": (e) => updateScene(index, { location_id: (e.target as HTMLInputElement).value }) }, []), h("input", { "aria-label": `场景 ${index + 1} 时间`, "placeholder": "时间（可选）", "value": scene.time ?? '', "onInput": (e) => updateScene(index, { time: (e.target as HTMLInputElement).value || null }) }, []), h(StructuredTextField<string[]>, { "singleLine": true, "aria-label": `场景 ${index + 1} 人物`, "class": styles.wide, "placeholder": "人物，用顿号或逗号分隔", "value": scene.participants, "format": (value) => value.join('、'), "parse": (value) => value.split(/[、,，]/).map((v) => v.trim()).filter(Boolean), "onChange": (value) => updateScene(index, { participants: value }) }, () => []), h("textarea", { "aria-label": `场景 ${index + 1} 目标`, "class": styles.wide, "rows": 2, "placeholder": "场景目标", "value": scene.goal, "onInput": (e) => updateScene(index, { goal: (e.target as HTMLInputElement).value }) }, []), h("button", { "type": "button", "onClick": () => update('scenes', plan.value.scenes.filter((_, i) => i !== index)) }, ["移除场景"])])), h("button", { "type": "button", "onClick": () => update('scenes', [...plan.value.scenes, { location_id: '', participants: [], goal: '', time: null }]) }, ["＋ 添加场景"])]), plan.value.characters.length > 0 && h("fieldset", { "class": styles.collection }, [h("legend", {}, ["人物预期状态"]), plan.value.characters.map((character, index) => h("div", { "class": styles.item, "key": index }, [h("input", { "aria-label": `人物 ${index + 1} 名称`, "value": character.character_id, "onInput": (e) => updateCharacter(index, { character_id: (e.target as HTMLInputElement).value }) }, []), h(StructuredTextField<Record<string, unknown>>, { "aria-label": `人物 ${index + 1} 状态`, "class": styles.wide, "rows": 2, "value": character.expected_state, "format": stateText, "parse": textState, "onChange": (value) => updateCharacter(index, { expected_state: value }) }, () => [])]))]), h(ListField, { "label": "预期事件", "value": plan.value.expected_events, "onChange": (value) => update('expected_events', value) }, () => []), h(ListField, { "label": "埋设伏笔", "value": plan.value.hooks_to_plant, "onChange": (value) => update('hooks_to_plant', value) }, () => []), h(ListField, { "label": "回收伏笔", "value": plan.value.hooks_to_resolve, "onChange": (value) => update('hooks_to_resolve', value) }, () => []), h(ListField, { "label": "硬约束", "value": plan.value.hard_constraints, "onChange": (value) => update('hard_constraints', value) }, () => [])]);
        };
    }
});
export const ChapterPlanPanel = defineComponent({
    name: "ChapterPlanPanel",
    props: { taskId: { type: String as PropType<(Props)["taskId"]>, required: true }, chapterSeq: { type: Number as PropType<(Props)["chapterSeq"]>, required: true }, status: { type: String as PropType<(Props)["status"]>, required: true }, runs: { type: Array as PropType<(Props)["runs"]>, required: true }, artifact: { type: Object as PropType<(Props)["artifact"]>, required: true }, onConfirmed: { type: Function as PropType<(Props)["onConfirmed"]>, required: true }, onCancelled: { type: Function as PropType<(Props)["onCancelled"]>, required: true } },
    setup(props: Props) {
        const taskId = computed(() => props.taskId);
        const chapterSeq = computed(() => props.chapterSeq);
        const status = computed(() => props.status);
        const runs = computed(() => props.runs);
        const artifact = computed(() => props.artifact);
        const onConfirmed = computed(() => props.onConfirmed);
        const onCancelled = computed(() => props.onCancelled);
        const draft = ref<ChapterPlan | null>(null), setDraft = (next: typeof draft.value | ((current: typeof draft.value) => typeof draft.value)) => draft.value = typeof next === "function" ? next(draft.value) : next;
        const busy = ref(false), setBusy = (next: typeof busy.value | ((current: typeof busy.value) => typeof busy.value)) => busy.value = typeof next === "function" ? next(busy.value) : next;
        const error = ref<string | null>(null), setError = (next: typeof error.value | ((current: typeof error.value) => typeof error.value)) => error.value = typeof next === "function" ? next(error.value) : next;
        let operationEpoch = 0;
        onScopeDispose(() => { operationEpoch++; });
        watch([taskId, chapterSeq], () => {
            operationEpoch++;
            setBusy(false);
            setError(null);
        }, { flush: 'sync' });
        const plans = computed(() => {
            const reviews = new Map<number, ChapterPlan>();
            for (const run of runs.value) {
                const attempt = run.detail?.plan_attempt ?? 1;
                if (run.node === 'plan_review' && isPlan(run.detail?.approved_plan))
                    reviews.set(attempt, run.detail.approved_plan);
            }
            return runs.value.filter((run) => run.node === 'plan_chapter' && isPlan(run.detail?.plan)).map((run) => {
                const attempt = run.detail?.plan_attempt ?? 1;
                return { attempt, plan: reviews.get(attempt) ?? run.detail!.plan! };
            });
        });
        const streamedPlan = computed(() => isPlan(artifact.value?.artifact) ? artifact.value.artifact : null);
        const latestPersistedAttempt = computed(() => plans.value.at(-1)?.attempt ?? 0);
        const streamingNewPlan = computed(() => Boolean(artifact.value && !artifact.value.complete && artifact.value.attempt > latestPersistedAttempt.value));
        const current = computed(() => streamingNewPlan.value ? null
            : streamedPlan.value ? { attempt: artifact.value?.attempt || latestPersistedAttempt.value || 1, plan: streamedPlan.value }
                : plans.value.at(-1) ?? null);
        const previous = computed(() => current.value ? plans.value.filter((item) => item.attempt < current.value!.attempt)
            : plans.value);
        const preview = computed(() => streamPreview(artifact.value?.content ?? ''));
        const editable = computed(() => status.value === 'awaiting_plan' && current.value !== null);
        useMemoryFormGuard(() => editable.value && draft.value !== null && JSON.stringify(draft.value) !== JSON.stringify(current.value?.plan));
        watch([taskId, chapterSeq, () => current.value?.attempt, editable], (_next, _prev, _onCleanup) => {
            if (current.value && editable.value)
                setDraft(clonePlan(current.value!.plan));
            else
                setDraft(null);
            setError(null);
        }, { immediate: true, flush: "post" });
        async function confirm() {
            if (!taskId.value || !current.value || !draft.value || busy.value)
                return;
            if (draft.value.goals.length === 0 || draft.value.expected_events.length === 0) {
                setError('本章目标和预期事件至少各保留一条。');
                return;
            }
            if (!draft.value.transition?.opening_beat.trim()) {
                setError('请填写“本章第一拍”，它决定正文如何承接上一章。');
                return;
            }
            if (draft.value.scenes.some((scene) => !scene.location_id.trim() || !scene.goal.trim())) {
                setError('每个场景都需要填写地点和场景目标。');
                return;
            }
            if (['time_jump', 'scene_cut'].includes(draft.value.transition.mode) && !draft.value.transition.bridge.trim()) {
                setError('时间跳转或场景切换需要填写“过渡桥”。');
                return;
            }
            setBusy(true);
            setError(null);
            const version = operationEpoch, id = taskId.value, seq = chapterSeq.value;
            try {
                await api.confirmTaskPlan(id, draft.value, current.value.attempt);
                if (version === operationEpoch) onConfirmed.value(id, seq);
            }
            catch (err) {
                if (version !== operationEpoch) return;
                if (err instanceof ApiError && err.code === 'PLAN_VERSION_CONFLICT') {
                    setError('计划已在其他页面更新，请刷新后再编辑。');
                }
                else if (err instanceof ApiError && err.status === 422) {
                    setError(formatApiError(err, '计划内容不符合约束，请修改后重试。'));
                }
                else {
                    setError('计划确认失败，请重试。');
                }
            }
            finally {
                if (version === operationEpoch) setBusy(false);
            }
        }
        async function cancel() {
            if (!taskId.value || busy.value)
                return;
            setBusy(true);
            setError(null);
            const version = operationEpoch, id = taskId.value, seq = chapterSeq.value;
            try {
                await api.cancelTask(id);
                if (version === operationEpoch) onCancelled.value(id, seq);
            }
            catch {
                if (version === operationEpoch) setError('取消失败，请重试。');
            }
            finally {
                if (version === operationEpoch) setBusy(false);
            }
        }
        return () => {
            return h("section", { "class": styles.panel }, [h("header", { "class": styles.head }, [h("span", {}, [h("b", {}, ["第 ", chapterSeq.value, " 章 Plan"]), h("small", {}, [!current.value ? '生成中' : editable.value ? '等待确认' : '已生成'])]), h("span", {}, ["独立 Plan 页面"])]), h("div", { "class": styles.body }, [!current.value ? h(Fragment, null, [h("div", { "class": styles.streaming }, [h("span", {}, ["AI 正在规划"]), h("p", {}, [preview.value || '正在读取前情、伏笔和人物状态…', h("i", {}, [])])]), previous.value.length > 0 && h("details", { "class": styles.history }, [h("summary", {}, ["历史计划（", previous.value.length, "）"]), previous.value.map((item) => h("details", { "key": item.attempt }, [h("summary", {}, ["第 ", item.attempt, " 版计划"]), h(PlanReadOnly, { "plan": item.plan }, () => [])]))])]) : h(Fragment, null, [editable.value && draft.value ? h(PlanEditor, { "plan": draft.value, "onChange": setDraft }, () => []) : h(PlanReadOnly, { "plan": current.value.plan }, () => []), previous.value.length > 0 && h("details", { "class": styles.history }, [h("summary", {}, ["历史计划（", previous.value.length, "）"]), previous.value.map((item) => h("details", { "key": item.attempt }, [h("summary", {}, ["第 ", item.attempt, " 版计划"]), h(PlanReadOnly, { "plan": item.plan }, () => [])]))]), error.value && h("div", { "class": "banner banner-error", "role": "alert" }, [error.value]), editable.value && h("div", { "class": styles.confirmBar }, [h("span", {}, ["确认后才会产生正文写作费用并进入 Write。"]), h("div", { "class": styles.confirmActions }, [h("button", { "type": "button", "class": "btn btn-quiet", "disabled": busy.value, "onClick": () => void cancel() }, ["取消本次写作"]), h("button", { "type": "button", "class": "btn btn-primary", "disabled": busy.value, "onClick": () => void confirm() }, [busy.value ? '提交中…' : '确认计划并开始写作'])])])])])]);
        };
    }
});

export default ChapterPlanPanel

</script>
