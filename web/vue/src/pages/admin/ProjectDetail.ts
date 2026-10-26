/* eslint-disable vue/one-component-per-file -- Native Vue render helpers stay with their owning page. */
import type { PropType } from 'vue';
import { computed, defineComponent, Fragment, h as renderNode, shallowRef } from 'vue';
import { useRoute } from 'vue-router';
import { adminApi, type AdminChapterDetail, type AdminContext, type AdminContextCollection, type AdminProject } from "../../../../src/lib/adminApi";
import { chapterStatusLabel, creationStatusLabel } from "../../../../src/lib/labels";
import { asRecord } from "../../../../src/lib/snapshotView";
import styles from "../../../../src/pages/AdminPage.module.css";
import { useAdminContext } from './context';
import { ReadableContent } from "./ReadableContent";
import { CapturedView, DetailPage, formatDate, LoadState, PAGE_SIZE, Pagination, RefreshButton, useResource } from "./shared";
const ChapterDetailView = defineComponent((props: {
    token: string;
    projectId: string;
    chapterId: string;
    onForbidden: () => void;
}) => {
    const load = (signal: AbortSignal) => adminApi.getChapter(props.token, props.projectId, props.chapterId, signal);
    const resource = useResource<AdminChapterDetail>(load, props.onForbidden);
    const value = computed(() => (resource.data));
    return () => {
        return (renderNode(LoadState, { ...resource, "empty": !value.value, children: [value.value && renderNode("article", { "class": `panel ${styles.detail}` }, [
                    renderNode("h3", {}, [
                        value.value.title ?? `第 ${value.value.chapter_seq} 章`, " · v", value.value.version
                    ]), renderNode("h4", {}, ["摘要"]), typeof value.value.summary === "string" && value.value.summary !== "" ? renderNode("p", { "class": styles.text }, [value.value.summary]) : renderNode(ReadableContent, { "value": value.value.summary }), renderNode("h4", {}, ["全文"]), value.value.content ? renderNode("p", { "class": styles.text }, [value.value.content]) : renderNode("p", { "class": styles.muted }, ["无正文"])
                ])] }));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        projectId: { type: String as PropType<string>, required: true },
        chapterId: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
/** 台账条目：键名翻中文，参与人物从 id 换成人名，嵌套结构再降一级。 */
function ContextEntries({ collection, nameOf }: {
    collection: AdminContextCollection;
    nameOf: (id: string) => string;
}) {
    if (collection.items.length === 0)
        return renderNode("p", { "class": styles.muted }, ["暂无记录"]);
    return (renderNode("ul", { "class": styles.plainList }, [collection.items.map((item: import("../../../../src/lib/adminApi").CapturedData, index: number) => {
            const record = asRecord(item.data);
            if (!record)
                return renderNode("li", { "key": index }, [renderNode(ReadableContent, { "value": item.data })]);
            const resolved: Record<string, unknown> = { ...record };
            if (Array.isArray(resolved.participants)) {
                resolved.participants = resolved.participants.map(entry => (typeof entry === "string" ? nameOf(entry) : entry));
            }
            return renderNode("li", { "key": index }, [renderNode(ReadableContent, { "value": Object.fromEntries(Object.entries(resolved).filter(([key]) => key !== "id")) })]);
        })]));
}
const ContextView = defineComponent((props: {
    value: AdminContext;
}) => {
    const nameOf = computed(() => {
        const names = new Map<string, string>();
        for (const item of props.value.characters.items) {
            const record = asRecord(item.data);
            if (record && typeof record.id === "string" && typeof record.name === "string") {
                names.set(record.id, record.name);
            }
        }
        return (id: string) => names.get(id) ?? `${id.slice(0, 8)}…`;
    });
    const collections = computed<Array<[
        string,
        AdminContextCollection
    ]>>(() => ([
        ["大纲", props.value.outlines],
        ["事件", props.value.events],
        ["事实", props.value.facts],
        ["人物", props.value.characters],
        ["伏笔", props.value.foreshadows],
        ["故事线", props.value.threads],
    ]));
    return () => {
        return (renderNode("div", { "class": styles.context }, [
            renderNode(CapturedView, { "value": props.value.settings, "label": "作品设置" }), collections.value.map(([label, collection]) => renderNode("section", { "class": styles.capture, "key": label }, [
                renderNode("h4", {}, [
                    label, "（显示 ", collection.items.length, " / 共 ", collection.total, "）"
                ]), collection.truncated && renderNode("div", { "class": styles.flags }, [renderNode("span", { "class": "badge badge-warning" }, ["集合已截断"])]), renderNode(ContextEntries, { "collection": collection, "nameOf": nameOf.value })
            ]))
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        value: { type: Object as PropType<AdminContext>, required: true }
    }
});
export const ProjectDetailView = defineComponent((props: {
    token: string;
    project: AdminProject;
    onForbidden: () => void;
}) => {
    const offset = shallowRef(0);
    const setOffset = (next: typeof offset.value | ((old: typeof offset.value) => typeof offset.value)) => { offset.value = typeof next === "function" ? next(offset.value) : next; };
    const chapterId = shallowRef<string | null>(null);
    const setChapterId = (next: typeof chapterId.value | ((old: typeof chapterId.value) => typeof chapterId.value)) => { chapterId.value = typeof next === "function" ? next(chapterId.value) : next; };
    const loadChapters = (signal: AbortSignal) => adminApi.listChapters(props.token, props.project.id, { limit: PAGE_SIZE, offset: offset.value }, signal);
    const loadContext = (signal: AbortSignal) => adminApi.getProjectContext(props.token, props.project.id, PAGE_SIZE, signal);
    const chapters = useResource(loadChapters, props.onForbidden);
    const context = useResource(loadContext, props.onForbidden);
    return () => {
        return (renderNode("div", { "class": styles.drilldown }, [
            renderNode("div", { "class": styles.detailHead }, [
                renderNode("div", {}, [
                    renderNode("h3", {}, [
                        "《", props.project.title, "》"
                    ]), renderNode("p", {}, [
                        props.project.username, " · ", props.project.genre, " · ", creationStatusLabel(props.project.creation_status)
                    ])
                ]), renderNode("div", {}, [
                    renderNode(RefreshButton, { "onClick": chapters.retry }), renderNode("button", { "type": "button", "class": "btn btn-secondary", "onClick": context.retry }, ["刷新设定"])
                ])
            ]), renderNode("div", { "class": styles.split }, [
                renderNode("section", { "class": `panel ${styles.detail}` }, [
                    renderNode("h3", {}, ["章节元数据"]), renderNode(LoadState, { ...chapters, "empty": chapters.data?.items.length === 0, children: [chapters.data && renderNode(Fragment, {}, [
                                renderNode("ul", { "class": styles.list }, [chapters.data.items.map((chapter: import("../../../../src/lib/adminApi").AdminChapter) => renderNode("li", { "key": chapter.id }, [
                                        renderNode("div", {}, [
                                            renderNode("strong", {}, [chapter.title ?? `第 ${chapter.chapter_seq} 章`]), renderNode("small", {}, [
                                                chapterStatusLabel(chapter.status), " · ", chapter.word_count.toLocaleString(), " 字 · ", formatDate(chapter.updated_at)
                                            ])
                                        ]), renderNode("button", { "type": "button", "class": "btn btn-quiet", "aria-label": `查看${chapter.title ?? `第 ${chapter.chapter_seq} 章`}全文`, "onClick": () => setChapterId(chapter.id) }, ["全文"])
                                    ]))]), renderNode(Pagination, { "total": chapters.data.total, "offset": offset.value, "onChange": (next: number) => { setChapterId(null); setOffset(next); } })
                            ])] })
                ]), renderNode("section", { "class": `panel ${styles.detail}` }, [
                    renderNode("h3", {}, ["受限上下文快照"]), renderNode(LoadState, { ...context, "empty": !context.data, children: [context.data && renderNode(ContextView, { "value": context.data })] })
                ])
            ]), chapterId.value && renderNode(ChapterDetailView, { "key": chapterId.value, "token": props.token, "projectId": props.project.id, "chapterId": chapterId.value, "onForbidden": props.onForbidden })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        project: { type: Object as PropType<AdminProject>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
export const ProjectDetailPage = defineComponent((_props: Record<string, never>) => { const adminContext = useAdminContext(); const { onForbidden } = adminContext; const { projectId = "" } = (useRoute().params as Record<string, string>); const load = (signal: AbortSignal) => adminApi.getProject(adminContext.token, projectId, signal); const resource = useResource<AdminProject>(load, onForbidden); return () => { return (renderNode(DetailPage, { "heading": "作品详情", "backTab": "projects", children: [renderNode(LoadState, { ...resource, "empty": !resource.data, children: [resource.data && renderNode(ProjectDetailView, { "token": adminContext.token, "project": resource.data, "onForbidden": onForbidden })] })] })); }; }, {
    inheritAttrs: false,
    props: {}
});
ContextEntries.props = ["collection", "nameOf"];
ContextEntries.inheritAttrs = false;
