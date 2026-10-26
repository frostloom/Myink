<script lang="ts">
import { useMemoryFormGuard } from "../composables/useMemoryFormGuard";
import type { PropType } from 'vue'
import { defineComponent, h, Fragment, Teleport, onMounted, ref, shallowRef, computed, watch } from 'vue'

import { candidateFields, candidateLabel, candidateTone } from "../../../src/lib/candidates";
import { api } from "../../../src/lib/api";
import type { ChapterStatus, MemoryCandidate } from "../../../src/types";
import StatusBadge from "./StatusBadge.vue";
import styles from "../../../src/components/CandidatePanel.module.css";
/** 放行目标：单章 awaiting_review 任务确认完候选后，从这里 resume 完成记忆与章节状态 */
export interface ReleaseTarget {
    taskId: string;
    chapterSeq: number;
    batchSize?: number;
}
interface Props {
    projectId: string;
    /** 右栏只展示当前选中章节的候选和评审记录。未传时保留组件独立测试兼容。 */
    chapterSeq?: number | null;
    chapterStatus?: ChapterStatus | null;
    candidates: MemoryCandidate[];
    onChanged: () => void;
    /** 当前章 await review 确认收尾后可放行 → 空态渲染主按钮 */
    releaseTarget?: ReleaseTarget | null;
    onReleased?: (taskId: string, chapterSeq: number, batchSize?: number) => void;
    /** 将人物、实体和伏笔 UUID 转成人可读名称。 */
    referenceNames?: Readonly<Record<string, string>>;
}
type Cid = MemoryCandidate['candidate_id'] | '__release__';
export const CandidatePanel = defineComponent({
    name: "CandidatePanel",
    props: { projectId: { type: String as PropType<(Props)["projectId"]>, required: true }, chapterSeq: { type: Number as PropType<(Props)["chapterSeq"]>, required: false, default: undefined }, chapterStatus: { type: String as PropType<(Props)["chapterStatus"]>, required: false, default: undefined }, candidates: { type: Array as PropType<(Props)["candidates"]>, required: true }, onChanged: { type: Function as PropType<(Props)["onChanged"]>, required: true }, releaseTarget: { type: Object as PropType<(Props)["releaseTarget"]>, required: false, default: undefined }, onReleased: { type: Function as PropType<(Props)["onReleased"]>, required: false, default: undefined }, referenceNames: { type: Object as PropType<(Props)["referenceNames"]>, required: false, default: undefined } },
    setup(props: Props) {
        const projectId = computed(() => props.projectId);
        const chapterSeq = computed(() => props.chapterSeq);
        const chapterStatus = computed(() => props.chapterStatus);
        const projectCandidates = computed(() => props.candidates);
        const onChanged = computed(() => props.onChanged);
        const releaseTarget = computed(() => props.releaseTarget);
        const onReleased = computed(() => props.onReleased);
        const referenceNames = computed(() => props.referenceNames ?? {});
        const allCandidates = computed(() => chapterSeq.value == null
            ? projectCandidates.value : projectCandidates.value.filter((candidate) => candidate.source_chapter === chapterSeq.value));
        const currentReleaseTarget = computed(() => releaseTarget.value && (chapterSeq.value == null || releaseTarget.value.chapterSeq === chapterSeq.value)
            ? releaseTarget.value : null);
        const submittedIds = ref<string[]>([]), setSubmittedIds = (next: typeof submittedIds.value | ((current: typeof submittedIds.value) => typeof submittedIds.value)) => submittedIds.value = typeof next === "function" ? next(submittedIds.value) : next;
        const candidates = computed(() => allCandidates.value.filter((c) => c.status === 'pending' && !submittedIds.value.includes(c.candidate_id)));
        const history = computed(() => allCandidates.value.filter((c) => c.status !== 'pending').slice(-20).reverse());
        const open = ref(candidates.value.length > 0), setOpen = (next: typeof open.value | ((current: typeof open.value) => typeof open.value)) => open.value = typeof next === "function" ? next(open.value) : next;
        const busy = ref<Cid | null>(null), setBusy = (next: typeof busy.value | ((current: typeof busy.value) => typeof busy.value)) => busy.value = typeof next === "function" ? next(busy.value) : next;
        const reason = ref(''), setReason = (next: typeof reason.value | ((current: typeof reason.value) => typeof reason.value)) => reason.value = typeof next === "function" ? next(reason.value) : next;
        useMemoryFormGuard(() => Boolean(reason.value));
        const notice = ref(''), setNotice = (next: typeof notice.value | ((current: typeof notice.value) => typeof notice.value)) => notice.value = typeof next === "function" ? next(notice.value) : next;
        const error = ref<string | null>(null), setError = (next: typeof error.value | ((current: typeof error.value) => typeof error.value)) => error.value = typeof next === "function" ? next(error.value) : next;
        const retryChapter = ref<number | null>(null), setRetryChapter = (next: typeof retryChapter.value | ((current: typeof retryChapter.value) => typeof retryChapter.value)) => retryChapter.value = typeof next === "function" ? next(retryChapter.value) : next;
        const retryChapters = computed(() => [...new Set([
                ...(retryChapter.value === null ? [] : [retryChapter.value]),
                ...allCandidates.value.filter((c) => c.status === 'rejected' && c.review?.mode === 'revise'
                    && !c.review.applied && !submittedIds.value.includes(c.candidate_id)).map((c) => c.source_chapter),
            ])]);
        const count = computed(() => candidates.value.length);
        const actionable = computed(() => count.value > 0 || currentReleaseTarget.value !== null || retryChapters.value.length > 0);
        const hasHistory = computed(() => history.value.length > 0);
        const hasShownCandidates = shallowRef(count.value > 0);
        const actionKey = computed(() => actionable.value ? `${chapterSeq.value ?? 'all'}:${candidates.value.map((candidate) => candidate.candidate_id).join(',')}:${retryChapters.value.join(',')}:${currentReleaseTarget.value?.taskId ?? ''}`
            : '');
        const previousActionKey = shallowRef(actionKey.value);
        const closeButtonRef = shallowRef<HTMLButtonElement | null>(null);
        const reviewOpen = ref(actionable.value), setReviewOpen = (next: typeof reviewOpen.value | ((current: typeof reviewOpen.value) => typeof reviewOpen.value)) => reviewOpen.value = typeof next === "function" ? next(reviewOpen.value) : next;
        // 首次异步加载到待确认项时自动展开；用户之后主动折叠时不再抢回展开状态。
        watch(() => [count.value], (_next, _prev, _onCleanup) => {
            if (count.value > 0 && !hasShownCandidates.value) {
                hasShownCandidates.value = true;
                setOpen(true);
            }
        }, { immediate: true, flush: "post" });
        // 新一轮待确认到达时自动提醒；用户主动关闭后，本轮不反复抢回焦点。
        watch(() => [actionKey.value], (_next, _prev, _onCleanup) => {
            if (actionKey.value && actionKey.value !== previousActionKey.value)
                setReviewOpen(true);
            if (!actionKey.value)
                setReviewOpen(false);
            previousActionKey.value = actionKey.value;
        }, { immediate: true, flush: "post" });
        // 最后一条候选处理并成功放行后，父级会清掉 releaseTarget。此时旧的“任务正在继续”
        // 提示已经过期，应自动收起并切换为历史记录状态，避免完成章仍看起来在待确认。
        watch(() => [actionable.value, chapterStatus.value], (_next, _prev, _onCleanup) => {
            if (actionable.value || chapterStatus.value !== 'confirmed')
                return;
            setNotice('');
            setError(null);
            setOpen(false);
        }, { immediate: true, flush: "post" });
        async function findTarget(chapterSeq: number, retry = false): Promise<ReleaseTarget> {
            // 候选池跨章节；不能直接续跑编辑器当前选中章，也不能从旧任务中挑一个恢复。
            const [latest] = await api.listTasks(projectId.value, chapterSeq);
            const allowed = retry ? ['awaiting_review', 'failed', 'paused', 'queued'] : ['awaiting_review'];
            if (!latest || !allowed.includes(latest.status)) {
                throw new Error(`第 ${chapterSeq} 章当前没有可修改的待评审任务，请刷新任务状态。`);
            }
            if (latest.task_type === 'batch_generate') {
                const detail = await api.getTask(latest.task_id);
                const currentChapter = Number(detail.payload.start) + (detail.progress?.current ?? 0);
                if (currentChapter !== chapterSeq)
                    throw new Error('这条候选不属于批次当前待处理章节，请刷新候选列表。');
            }
            return { taskId: latest.task_id, chapterSeq, batchSize: latest.batch_size ?? undefined };
        }
        async function startRevision(target: ReleaseTarget) {
            await api.resumeBatch(target.taskId);
            setSubmittedIds((ids) => [...ids, ...allCandidates.value.filter((c) => c.source_chapter === target.chapterSeq).map((c) => c.candidate_id)]);
            setRetryChapter(null);
            setReason('');
            setNotice(`第 ${target.chapterSeq} 章已提交自动修改，系统会检查修改后的内容，进度见任务区。`);
            setReviewOpen(false);
            onReleased.value?.(target.taskId, target.chapterSeq, target.batchSize);
            onChanged.value();
        }
        async function act(action: 'confirm' | 'reject', candidate: MemoryCandidate) {
            if (busy.value)
                return;
            const cid = candidate.candidate_id;
            setBusy(cid);
            setError(null);
            setNotice('');
            let rejectionSaved = false;
            try {
                if (action === 'confirm') {
                    await api.confirmCandidate(projectId.value, cid);
                    setSubmittedIds((ids) => [...ids, cid]);
                    const isLastPending = candidates.value.every((item) => item.candidate_id === cid);
                    if (isLastPending && currentReleaseTarget.value) {
                        try {
                            await api.resumeBatch(currentReleaseTarget.value.taskId);
                            setNotice(`第 ${currentReleaseTarget.value.chapterSeq} 章设定已确认，任务正在继续。`);
                            setReviewOpen(false);
                            onReleased.value?.(currentReleaseTarget.value.taskId, currentReleaseTarget.value.chapterSeq, currentReleaseTarget.value.batchSize);
                        }
                        catch {
                            setError('设定已接受，但任务未能继续。请点“重试完成确认”，无需再次接受。');
                        }
                    }
                    else {
                        const remaining = Math.max(0, candidates.value.length - 1);
                        setNotice(remaining > 0 ? `已接受这条设定，还有 ${remaining} 条待确认。` : '已接受这条设定。');
                    }
                }
                else {
                    const target = await findTarget(candidate.source_chapter);
                    await api.rejectCandidate(projectId.value, cid, reason.value, 'revise');
                    rejectionSaved = true;
                    setRetryChapter(candidate.source_chapter);
                    await startRevision(target);
                }
                onChanged.value();
            }
            catch (err) {
                setError(rejectionSaved ? '意见已保存，但自动修改未能启动。请点“重试修改”，无需再次拒绝。'
                    : err instanceof Error ? err.message : '操作失败');
                // 请求响应丢失时，服务端可能已保存意见；刷新后也能找回重试入口。
                onChanged.value();
            }
            finally {
                setBusy(null);
            }
        }
        async function retryRevision(chapterSeq: number) {
            if (busy.value)
                return;
            setBusy('__release__');
            setError(null);
            try {
                await startRevision(await findTarget(chapterSeq, true));
            }
            catch (err) {
                setError(err instanceof Error ? err.message : '启动修改失败，请重试');
            }
            finally {
                setBusy(null);
            }
        }
        // 放行本章：正文已在待确认阶段可见；候选确认完后 resume 完成记忆与章节状态。
        async function release() {
            if (!currentReleaseTarget.value || busy.value)
                return;
            setBusy('__release__');
            setError(null);
            try {
                await api.resumeBatch(currentReleaseTarget.value.taskId);
                setNotice(`第 ${currentReleaseTarget.value.chapterSeq} 章设定已确认，任务正在继续。`);
                setReviewOpen(false);
                onReleased.value?.(currentReleaseTarget.value.taskId, currentReleaseTarget.value.chapterSeq, currentReleaseTarget.value.batchSize);
                onChanged.value();
            }
            catch (err) {
                setError(err instanceof Error ? err.message : '接受本章失败');
            }
            finally {
                setBusy(null);
            }
        }
        watch(() => [reviewOpen.value, busy.value], (_next, _prev, onCleanup) => {
            if (!reviewOpen.value)
                return;
            const previousOverflow = document.body.style.overflow;
            const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
            document.body.style.overflow = 'hidden';
            closeButtonRef.value?.focus();
            function onKeyDown(event: KeyboardEvent) {
                if (event.key === 'Escape' && busy.value === null)
                    setReviewOpen(false);
            }
            document.addEventListener('keydown', onKeyDown);
            onCleanup(() => {
                document.body.style.overflow = previousOverflow;
                document.removeEventListener('keydown', onKeyDown);
                previousFocus?.focus();
            });
        }, { immediate: true, flush: "post" });
        onMounted(() => { if (reviewOpen.value) closeButtonRef.value?.focus() });
        return () => {
            return (h(Fragment, null, [h("section", { "class": `panel ${styles.panel}`, "aria-label": "设定评审侧栏" }, [h("header", { "class": styles.head }, [h("button", { "type": "button", "class": styles.toggle, "onClick": () => setOpen((o) => !o), "aria-expanded": open.value }, [h("span", { "class": styles.headingGroup }, [h("span", { "class": styles.title }, [actionable.value ? '设定确认' : '设定记录']), chapterSeq.value != null && h("span", { "class": styles.chapter }, ["第 ", chapterSeq.value, " 章"])]), h("span", { "class": styles.headerMeta }, [count.value > 0 && h("span", { "class": "badge badge-warning" }, [count.value, " 项"]), count.value === 0 && (currentReleaseTarget.value || retryChapters.value.length > 0) && h("span", { "class": "badge badge-warning" }, ["待处理"]), !actionable.value && hasHistory.value && h("span", { "class": "badge badge-success" }, ["已完成"]), h("span", { "class": styles.caret }, [open.value ? '▾' : '▸'])])])]), open.value && notice.value && h("p", { "role": "status", "class": styles.notice }, [notice.value]), open.value && history.value.length > 0 && h("details", { "class": styles.history }, [h("summary", {}, ["最近评审记录（", history.value.length, "）"]), history.value.map((c) => h("p", { "key": c.candidate_id }, ["第 ", c.source_chapter, " 章 · ", candidateLabel(c.kind), " · ", c.status === 'confirmed' ? '已确认' : c.review?.superseded ? '旧稿候选已作废' : c.review?.mode === 'revise' ? (c.review.applied ? '已按意见修订并复审' : '等待按意见修订') : '仅拒绝记忆入库', c.review?.reason && `：${c.review.reason}`]))]), open.value && !reviewOpen.value && error.value && h("div", { "class": "banner banner-error" }, [error.value]), open.value && (h("div", { "class": styles.release }, [h("p", { "class": "empty" }, [actionable.value ? '本章有设定需要处理，操作会在页面中央的确认窗口中完成。' : '本章没有待确认的设定。']), actionable.value && (h("button", { "type": "button", "class": "btn btn-primary", "onClick": () => setReviewOpen(true) }, [count.value > 0 ? `处理 ${count.value} 项设定` : '继续处理']))]))]), reviewOpen.value && actionable.value && h(Teleport, { to: document.body }, [h("div", { "class": styles.modalBackdrop, "onMouseDown": (event: MouseEvent) => {
                            if (event.target === event.currentTarget && busy.value === null)
                                setReviewOpen(false);
                        } }, [h("section", { "class": styles.modal, "role": "dialog", "aria-modal": "true", "aria-labelledby": "candidate-review-title" }, [h("header", { "class": styles.modalHead }, [h("div", {}, [h("h2", { "id": "candidate-review-title" }, ["设定确认"]), h("p", {}, [chapterSeq.value != null ? `第 ${chapterSeq.value} 章` : '当前章节', " · ", count.value > 0 ? `${count.value} 项待处理` : '继续未完成操作'])]), h("button", { "ref": closeButtonRef, "type": "button", "class": styles.modalClose, "aria-label": "暂后处理", "disabled": busy.value !== null, "onClick": () => setReviewOpen(false) }, ["×"])]), h("div", { "class": styles.modalBody }, [h("p", { "class": styles.modalHint }, [count.value > 0
                                        ? '接受会保存设定；不接受会按你的意见自动修改本章，然后重新检查。'
                                        : '上一次结果已经保存，可以继续未完成的后续步骤。']), error.value && h("div", { "class": "banner banner-error" }, [error.value]), retryChapters.value.map((seq) => (h("button", { "key": seq, "type": "button", "class": "btn btn-primary", "disabled": busy.value !== null, "onClick": () => void retryRevision(seq) }, [busy.value === '__release__' ? '处理中…' : `重试修改第 ${seq} 章`]))), currentReleaseTarget.value && !retryChapters.value.includes(currentReleaseTarget.value.chapterSeq)
                                    && count.value === 0 && (h("button", { "type": "button", "class": "btn btn-primary", "disabled": busy.value !== null, "onClick": () => void release() }, [busy.value === '__release__' ? '处理中…' : '重试完成确认'])), count.value > 0 && (h("label", { "class": styles.reasonField }, [h("span", {}, ["修改意见（可选）"]), h("input", { "class": "input", "value": reason.value, "disabled": busy.value !== null, "maxLength": 2000, "onInput": (e) => setReason((e.target as HTMLInputElement).value), "placeholder": "例如：人物仍然受伤，需要治疗过程" }, [])])), count.value > 0 && (h("ul", { "class": styles.list }, [candidates.value.map((c) => (h("li", { "key": c.candidate_id, "class": styles.item }, [h("div", { "class": styles.meta }, [h(StatusBadge, { "tone": candidateTone(c.kind) }, () => [candidateLabel(c.kind)]), h("span", { "class": styles.chapter }, ["第 ", c.source_chapter, " 章"]), c.confidence < 1 && h("span", { "class": styles.conf }, ["置信 ", Math.round(c.confidence * 100), "%"])]), h("dl", { "class": styles.fields }, [candidateFields(c.kind, c.payload, referenceNames.value).map(([label, value]) => (h("div", { "key": label, "class": styles.row }, [h("dt", {}, [label]), h("dd", {}, [value])])))]), c.kind === 'character_card' && (h("p", { "class": styles.danger }, ["确认将在设定页新建人物卡片（身份 / 角色 / 性格），正文后续抽取会持续更新其状态。"])), c.kind === 'memory_removal' && (h("p", { "class": styles.danger }, ["确认将按类型失效被删记忆（events 硬删 / facts 关窗），不可撤销。"])), h("div", { "class": styles.actions }, [h("button", { "type": "button", "class": "btn btn-primary", "disabled": busy.value !== null || retryChapters.value.includes(c.source_chapter), "onClick": () => void act('confirm', c) }, [busy.value === c.candidate_id ? '处理中…' : '接受']), h("button", { "type": "button", "class": "btn btn-quiet", "disabled": busy.value !== null || retryChapters.value.includes(c.source_chapter), "onClick": () => void act('reject', c) }, ["不接受，自动修改"])])])))]))])])])])]));
        };
    }
});

export default CandidatePanel

</script>
