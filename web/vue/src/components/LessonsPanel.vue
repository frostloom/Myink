<script lang="ts">
import type { PropType } from 'vue'
import { defineComponent, h, ref, computed, watch } from 'vue'

import { api } from "../../../src/lib/api";
import { formatApiError } from "../../../src/lib/apiError";
import type { WritingLesson } from "../../../src/types";
import StatusBadge from "./StatusBadge.vue";
import styles from "../../../src/components/LessonsPanel.module.css";
interface Props {
    projectId: string;
}
type LessonStatus = WritingLesson['status'];
const STATUS_TONE: Record<LessonStatus, 'accent' | 'success' | 'hint'> = {
    proposed: 'accent',
    active: 'success',
    rejected: 'hint',
};
const STATUS_LABEL: Record<LessonStatus, string> = {
    proposed: '待确认',
    active: '已生效',
    rejected: '已拒绝',
};
export const LessonsPanel = defineComponent({
    name: "LessonsPanel",
    props: { projectId: { type: String as PropType<(Props)["projectId"]>, required: true } },
    setup(props: Props) {
        const projectId = computed(() => props.projectId);
        const open = ref(false), setOpen = (next: typeof open.value | ((current: typeof open.value) => typeof open.value)) => open.value = typeof next === "function" ? next(open.value) : next;
        const lessons = ref<WritingLesson[]>([]), setLessons = (next: typeof lessons.value | ((current: typeof lessons.value) => typeof lessons.value)) => lessons.value = typeof next === "function" ? next(lessons.value) : next;
        const busy = ref<string | null>(null), setBusy = (next: typeof busy.value | ((current: typeof busy.value) => typeof busy.value)) => busy.value = typeof next === "function" ? next(busy.value) : next;
        const error = ref<string | null>(null), setError = (next: typeof error.value | ((current: typeof error.value) => typeof error.value)) => error.value = typeof next === "function" ? next(error.value) : next;
        watch(() => [projectId.value], (_next, _prev, onCleanup) => {
            let alive = true;
            api.listLessons(projectId.value)
                .then((list) => { if (alive)
                setLessons(list); })
                .catch(() => { if (alive)
                setLessons([]); });
            onCleanup(() => { alive = false; });
        }, { immediate: true, flush: "post" });
        const pending = computed(() => lessons.value.filter((l) => l.status === 'proposed').length);
        async function act(action: 'confirm' | 'reject', lid: string) {
            if (busy.value)
                return;
            setBusy(lid);
            setError(null);
            try {
                if (action === 'confirm')
                    await api.confirmLesson(projectId.value, lid);
                else
                    await api.rejectLesson(projectId.value, lid);
                const list = await api.listLessons(projectId.value).catch(() => []);
                setLessons(list);
            }
            catch (err) {
                setError(formatApiError(err, '操作失败'));
            }
            finally {
                setBusy(null);
            }
        }
        return () => {
            return (h("section", { "class": `panel ${styles.panel}` }, [h("header", { "class": styles.head }, [h("button", { "type": "button", "class": styles.toggle, "onClick": () => setOpen((o) => !o) }, [h("span", { "class": styles.title }, ["写作经验"]), pending.value > 0 && h("span", { "class": "badge badge-warning" }, [pending.value]), h("span", { "class": styles.caret }, [open.value ? '▾' : '▸'])])]), error.value && h("div", { "class": "banner banner-error" }, [error.value]), open.value && lessons.value.length === 0 && (h("p", { "class": "empty" }, ["暂无写作经验。批次收尾 reflexion 复盘出的高危经验会出现在这里。"])), open.value && lessons.value.length > 0 && (h("ul", { "class": styles.list }, [lessons.value.map((l) => (h("li", { "key": l.lesson_id, "class": styles.item }, [h("div", { "class": styles.meta }, [h(StatusBadge, { "tone": STATUS_TONE[l.status] ?? 'hint' }, () => [STATUS_LABEL[l.status] ?? l.status]), h("span", { "class": styles.chapter }, ["第 ", l.source_chapter, " 章"]), l.recurrence_count > 0 && (h("span", { "class": `badge badge-warning` }, ["复发 ×", l.recurrence_count]))]), h("p", { "class": styles.content }, [l.content]), l.status === 'proposed' && (h("div", { "class": styles.actions }, [h("button", { "type": "button", "class": "btn btn-primary", "disabled": busy.value !== null, "onClick": () => void act('confirm', l.lesson_id) }, [busy.value === l.lesson_id ? '处理中…' : '确认生效']), h("button", { "type": "button", "class": "btn btn-quiet", "disabled": busy.value !== null, "onClick": () => void act('reject', l.lesson_id) }, ["拒绝"])]))])))]))]));
        };
    }
});

export default LessonsPanel

</script>
