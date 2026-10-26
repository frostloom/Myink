<script lang="ts">
import { useMemoryFormGuard } from "../composables/useMemoryFormGuard";
import type { PropType } from 'vue'
import { defineComponent, h, ref, shallowRef, computed, watch } from 'vue'

import { api, ApiError } from "../../../src/lib/api";
import { formatApiError } from "../../../src/lib/apiError";
import type { ChapterMeta, WritingMode } from "../../../src/types";
import styles from "../../../src/components/GenerationPanel.module.css";
/** 单章估算成本（与 COST_PER_CHAPTER_YUAN 默认值对齐；无 API 暴露，前端常量标注「估算」） */
const COST_PER_CHAPTER = 0.05;
const BATCH_MAX = 20;
interface Props {
    projectId: string;
    chapters: ChapterMeta[];
    selectedChapter: ChapterMeta | null;
    /** 当前书已有任务在规划/写作/等待人工时，阻止重复发起。 */
    taskBusy?: boolean;
    beforeGenerate?: () => Promise<boolean>;
    /** 批次生成时带 batchTotal（时间线实时 i/N）；单章任务带 chapterSeq（右栏按章过滤） */
    onTaskStart: (taskId: string, batchTotal?: number, chapterSeq?: number, mode?: WritingMode) => void;
}
export const GenerationPanel = defineComponent({
    name: "GenerationPanel",
    props: { projectId: { type: String as PropType<(Props)["projectId"]>, required: true }, chapters: { type: Array as PropType<(Props)["chapters"]>, required: true }, selectedChapter: { type: Object as PropType<(Props)["selectedChapter"]>, required: true }, taskBusy: { type: Boolean as PropType<(Props)["taskBusy"]>, required: false, default: undefined }, beforeGenerate: { type: Function as PropType<(Props)["beforeGenerate"]>, required: false, default: undefined }, onTaskStart: { type: Function as PropType<(Props)["onTaskStart"]>, required: true } },
    setup(props: Props) {
        const projectId = computed(() => props.projectId);
        const chapters = computed(() => props.chapters);
        const selectedChapter = computed(() => props.selectedChapter);
        const taskBusy = computed(() => props.taskBusy ?? false);
        const onTaskStart = computed(() => props.onTaskStart);
        const beforeGenerate = computed(() => props.beforeGenerate);
        const open = ref(true), setOpen = (next: typeof open.value | ((current: typeof open.value) => typeof open.value)) => open.value = typeof next === "function" ? next(open.value) : next;
        const instruction = ref(''), setInstruction = (next: typeof instruction.value | ((current: typeof instruction.value) => typeof instruction.value)) => instruction.value = typeof next === "function" ? next(instruction.value) : next;
        const batchN = ref(3), setBatchN = (next: typeof batchN.value | ((current: typeof batchN.value) => typeof batchN.value)) => batchN.value = typeof next === "function" ? next(batchN.value) : next;
        const mode = ref<WritingMode>('auto'), setMode = (next: typeof mode.value | ((current: typeof mode.value) => typeof mode.value)) => mode.value = typeof next === "function" ? next(mode.value) : next;
        const busy = ref<null | 'chapter' | 'batch'>(null), setBusy = (next: typeof busy.value | ((current: typeof busy.value) => typeof busy.value)) => busy.value = typeof next === "function" ? next(busy.value) : next;
        const banner = ref<string | null>(null), setBanner = (next: typeof banner.value | ((current: typeof banner.value) => typeof banner.value)) => banner.value = typeof next === "function" ? next(banner.value) : next;
        const notice = ref<string | null>(null), setNotice = (next: typeof notice.value | ((current: typeof notice.value) => typeof notice.value)) => notice.value = typeof next === "function" ? next(notice.value) : next;
        const requestVersion = shallowRef(0);
        useMemoryFormGuard(() => Boolean(instruction.value) || batchN.value !== 3);
        watch(() => projectId.value, (_next, _prev, onCleanup) => {
            requestVersion.value += 1;
            setInstruction('');
            setBusy(null);
            setBanner(null);
            setNotice(null);
            onCleanup(() => { requestVersion.value += 1; });
        }, { immediate: true, flush: "sync" });
        const tail = computed(() => chapters.value.reduce<ChapterMeta | null>((current, chapter) => (current === null || chapter.chapter_seq > current.chapter_seq ? chapter : current), null));
        const tailIsEmptyPlaceholder = computed(() => Boolean(tail.value && (tail.value.word_count ?? 0) === 0
            && ['planning', 'writing', 'failed', 'cancelled'].includes(tail.value.status)));
        const nextSeq = computed(() => tailIsEmptyPlaceholder.value && tail.value ? tail.value.chapter_seq : (tail.value?.chapter_seq ?? 0) + 1);
        const chapterIsPlanning = computed(() => tailIsEmptyPlaceholder.value && tail.value?.status === 'planning');
        const chapterIsRunning = computed(() => tailIsEmptyPlaceholder.value && tail.value?.status === 'writing');
        const chapterIsBusy = computed(() => chapterIsPlanning.value || chapterIsRunning.value);
        const controlsBusy = computed(() => busy.value !== null || chapterIsBusy.value || taskBusy.value);
        const chapterActionLabel = computed(() => chapterIsRunning.value ? `第 ${nextSeq.value} 章生成中…`
            : chapterIsPlanning.value ? `第 ${nextSeq.value} 章等待计划确认`
                : tailIsEmptyPlaceholder.value ? `继续生成第 ${nextSeq.value} 章`
                    : `写下一章（第 ${nextSeq.value} 章）`);
        const tailId = computed(() => tail.value?.id ?? projectId.value);
        const batchStart = computed(() => nextSeq.value);
        const batchCost = computed(() => (batchN.value * COST_PER_CHAPTER).toFixed(2));
        function showError(err: unknown) {
            setNotice(null);
            if (err instanceof ApiError) {
                setBanner(formatApiError(err));
            }
            else {
                setBanner('请求失败，请重试');
            }
        }
        // 写下一章：空书也可写（第 1 章，写作指令透传）；tailId 恒非空（空书回退 projectId 占位）
        async function generateNextChapter() {
            if (busy.value)
                return;
            const operation = {
                projectId: projectId.value,
                chapterId: tailId.value,
                seq: nextSeq.value,
                mode: mode.value,
                instruction: instruction.value.trim(),
                size: batchN.value,
                beforeGenerate: beforeGenerate.value,
                onTaskStart: onTaskStart.value,
            };
            const version = requestVersion.value;
            const isCurrent = () => version === requestVersion.value && operation.projectId === projectId.value;
            setBusy('chapter');
            setBanner(null);
            setNotice(null);
            try {
                if (operation.beforeGenerate && !(await operation.beforeGenerate()))
                    return;
                if (!isCurrent())
                    return;
                const resp = await api.generateChapter(operation.projectId, operation.chapterId, {
                    seq: operation.seq,
                    mode: operation.mode,
                    ...(operation.instruction ? { user_instruction: operation.instruction } : {}),
                });
                if (!isCurrent())
                    return;
                operation.onTaskStart(resp.task_id, undefined, operation.seq, operation.mode);
                setNotice(`第 ${operation.seq} 章写作任务已创建，进度会显示在下方“章节流转”中。`);
            }
            catch (err) {
                if (isCurrent())
                    showError(err);
            }
            finally {
                if (isCurrent())
                    setBusy(null);
            }
        }
        // 重写本章（仅 confirmed 章；awaiting_review 走时间线 resume/reject 分流）：
        // worker _guard_write_order(rewrite=True) 放行已确认章，重写会失效重建该章相关记忆
        async function rewriteChapter() {
            if (!selectedChapter.value || selectedChapter.value.status !== 'confirmed' || busy.value)
                return;
            const operation = {
                projectId: projectId.value,
                chapterId: selectedChapter.value.id,
                seq: selectedChapter.value.chapter_seq,
                mode: mode.value,
                instruction: instruction.value.trim(),
                size: batchN.value,
                beforeGenerate: beforeGenerate.value,
                onTaskStart: onTaskStart.value,
            };
            const version = requestVersion.value;
            const isCurrent = () => version === requestVersion.value && operation.projectId === projectId.value;
            if (!window.confirm(`重写第 ${operation.seq} 章？将失效重建该章相关记忆，不可撤销。`) || !isCurrent())
                return;
            setBusy('chapter');
            setBanner(null);
            setNotice(null);
            try {
                if (operation.beforeGenerate && !(await operation.beforeGenerate()))
                    return;
                if (!isCurrent())
                    return;
                const resp = await api.generateChapter(operation.projectId, operation.chapterId, {
                    seq: operation.seq,
                    rewrite: true,
                    mode: operation.mode,
                    ...(operation.instruction ? { user_instruction: operation.instruction } : {}),
                });
                if (!isCurrent())
                    return;
                operation.onTaskStart(resp.task_id, undefined, operation.seq, operation.mode);
                setNotice(`第 ${operation.seq} 章重写任务已创建，进度会显示在下方“章节流转”中。`);
            }
            catch (err) {
                if (isCurrent())
                    showError(err);
            }
            finally {
                if (isCurrent())
                    setBusy(null);
            }
        }
        async function generateBatch() {
            if (busy.value || mode.value === 'manual')
                return;
            const operation = {
                projectId: projectId.value,
                chapterId: tailId.value,
                seq: nextSeq.value,
                mode: mode.value,
                instruction: instruction.value.trim(),
                size: batchN.value,
                beforeGenerate: beforeGenerate.value,
                onTaskStart: onTaskStart.value,
            };
            const version = requestVersion.value;
            const isCurrent = () => version === requestVersion.value && operation.projectId === projectId.value;
            setBusy('batch');
            setBanner(null);
            setNotice(null);
            try {
                if (operation.beforeGenerate && !(await operation.beforeGenerate()))
                    return;
                if (!isCurrent())
                    return;
                const resp = await api.generateBatch(operation.projectId, {
                    size: operation.size,
                    start: operation.seq,
                });
                if (!isCurrent())
                    return;
                operation.onTaskStart(resp.task_id, operation.size, operation.seq);
                setNotice(`批次任务已创建，将从第 ${operation.seq} 章开始写作。`);
            }
            catch (err) {
                if (isCurrent())
                    showError(err);
            }
            finally {
                if (isCurrent())
                    setBusy(null);
            }
        }
        return () => {
            // 短篇：整篇一次成稿的入口在工作台的中间栏状态带上，这里不再有短篇分支。
            return (h("section", { "class": `panel ${styles.panel}` }, [h("header", { "class": styles.head }, [h("button", { "type": "button", "class": styles.toggle, "onClick": () => setOpen((value) => !value), "aria-expanded": open.value }, [h("span", { "class": styles.heading }, ["生成与重写"]), h("span", { "class": styles.next }, [chapterIsRunning.value ? `当前生成：第 ${nextSeq.value} 章`
                                : chapterIsPlanning.value ? `等待确认：第 ${nextSeq.value} 章`
                                    : tailIsEmptyPlaceholder.value ? `待继续：第 ${nextSeq.value} 章`
                                        : `下一章：第 ${nextSeq.value} 章`]), h("span", { "class": styles.caret }, [open.value ? '▾' : '▸'])])]), open.value && h("div", { "class": styles.body }, [banner.value && h("div", { "class": "banner banner-error", "role": "alert" }, [banner.value]), notice.value && h("div", { "class": styles.notice, "role": "status" }, [notice.value]), h("form", { "class": styles.form, "onSubmit": (event) => { event.preventDefault(); void generateNextChapter(); } }, [h("label", { "class": styles.label, "for": "user-instruction" }, ["写作指令（可留空）"]), h("textarea", { "id": "user-instruction", "class": "textarea", "rows": 2, "value": instruction.value, "onInput": (e) => setInstruction((e.target as HTMLInputElement).value), "placeholder": "如：节奏放慢，重点刻画战斗场面" }, []), h("button", { "type": "button", "class": "btn btn-primary", "disabled": controlsBusy.value, "onClick": () => void generateNextChapter() }, [busy.value === 'chapter' ? '发起中…' : chapterActionLabel.value]), h("fieldset", { "class": styles.modeSwitch }, [h("legend", {}, ["写作模式"]), h("button", { "type": "button", "class": mode.value === 'auto' ? styles.modeActive : styles.modeButton, "aria-pressed": mode.value === 'auto', "disabled": controlsBusy.value, "onClick": () => setMode('auto') }, ["自动"]), h("button", { "type": "button", "class": mode.value === 'manual' ? styles.modeActive : styles.modeButton, "aria-pressed": mode.value === 'manual', "disabled": controlsBusy.value, "onClick": () => setMode('manual') }, ["手动确认 Plan"]), h("span", {}, [mode.value === 'manual' ? 'Plan 可编辑，确认后才开始写作' : '展示 Plan 后自动写作'])]), h("button", { "type": "button", "class": "btn btn-quiet", "disabled": !selectedChapter.value || selectedChapter.value.status !== 'confirmed' || controlsBusy.value, "onClick": rewriteChapter }, [selectedChapter.value && selectedChapter.value.status === 'confirmed'
                                ? `重写第 ${selectedChapter.value.chapter_seq} 章`
                                : '重写本章']), chapters.value.length === 0 && (h("p", { "class": styles.emptyHint }, ["新书可直接写第 1 章（上面的写作指令会生效）；要一次写多章再用下方「发起批次」。"]))]), h("form", { "class": styles.form, "onSubmit": (event) => { event.preventDefault(); void generateBatch(); } }, [h("label", { "class": styles.label, "for": "batch-n" }, ["批次生成"]), h("div", { "class": styles.batchRow }, [h("input", { "id": "batch-n", "type": "number", "min": 1, "max": BATCH_MAX, "value": batchN.value, "disabled": mode.value === 'manual', "onInput": (e) => setBatchN(Math.max(1, Math.min(BATCH_MAX, Number((e.target as HTMLInputElement).value)))) }, []), h("span", { "class": styles.batchHint }, ["从第", batchStart.value, "章起", h("span", { "class": styles.cost }, [" ≈ ¥", batchCost.value, "（估算）"])])]), h("button", { "type": "button", "class": "btn btn-secondary", "disabled": controlsBusy.value || mode.value === 'manual', "onClick": () => void generateBatch() }, [busy.value === 'batch' ? '发起中…' : '发起批次']), mode.value === 'manual' && h("p", { "class": styles.batchDisabled }, ["手动模式需要逐章确认计划，批量生成已禁用。"])])])]));
        };
    }
});

export default GenerationPanel

</script>
