<script lang="ts">
import type { PropType } from 'vue'
import { defineComponent, h, computed } from 'vue'

// 次级导航：章节序/标题/状态，点选加载编辑器。
import { chapterStatusLabel, chapterStatusTone } from "../../../src/lib/labels";
import type { ChapterMeta } from "../../../src/types";
import StatusBadge from "./StatusBadge.vue";
import styles from "../../../src/components/ChapterList.module.css";
interface Props {
    chapters: ChapterMeta[];
    selectedCid: string | null;
    onSelect: (cid: string) => void;
    /** 章序 → 待确认候选数（候选池面板联动：点进有候选的章先处理再续跑） */
    pendingByChapter?: Map<number, number>;
}
export const ChapterList = defineComponent({
    name: "ChapterList",
    props: { chapters: { type: Array as PropType<(Props)["chapters"]>, required: true }, selectedCid: { type: String as PropType<(Props)["selectedCid"]>, required: true }, onSelect: { type: Function as PropType<(Props)["onSelect"]>, required: true }, pendingByChapter: { type: Object as PropType<(Props)["pendingByChapter"]>, required: false, default: undefined } },
    setup(props: Props) {
        const chapters = computed(() => props.chapters);
        const selectedCid = computed(() => props.selectedCid);
        const onSelect = computed(() => props.onSelect);
        const pendingByChapter = computed(() => props.pendingByChapter);
        return () => {
            if (chapters.value.length === 0) {
                return h("div", { "class": "empty" }, ["还没有章节。在右侧发起首次生成。"]);
            }
            return (h("div", { "class": styles.list }, [chapters.value.map((c) => {
                    const pending = pendingByChapter.value?.get(c.chapter_seq) ?? 0;
                    return (h("button", { "key": c.id, "type": "button", "class": selectedCid.value === c.id ? `${styles.item} ${styles.active}` : styles.item, "onClick": () => onSelect.value(c.id) }, [h("span", { "class": styles.seq }, ["第 ", c.chapter_seq, " 章"]), c.title && h("span", { "class": styles.title }, [c.title]), c.word_count != null && (h("span", { "class": styles.words, "title": "正文字符数（含标点）" }, [c.word_count.toLocaleString(), "字"])), pending > 0 && (h("span", { "class": `badge badge-warning ${styles.pending}`, "title": "有待确认候选" }, [pending, "待确认"])), h(StatusBadge, { "tone": chapterStatusTone(c.status) }, () => [chapterStatusLabel(c.status)])]));
                })]));
        };
    }
});

export default ChapterList

</script>
