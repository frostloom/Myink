/* eslint-disable vue/one-component-per-file -- Native Vue render helpers stay with their owning page. */
import type { PropType } from 'vue';
import { defineComponent, Fragment, h as renderNode, shallowRef } from 'vue';
import { adminApi, type AdminGenerationTask, type AdminProject, type AdminSnapshotFinding, type AdminTaskAverages, type AdminTaskChapter, type AdminUser, type AdminPage as PageResult, } from "../../../../src/lib/adminApi";
import { conflictTypeLabel, creationStatusLabel, findingSourceLabel, nodeLabel, roleLabel, scopeLabel, severityLabel, taskChapterLabel, taskStatusLabel, taskTypeLabel, tierLabel, } from "../../../../src/lib/labels";
import { severityClass } from "../../../../src/lib/snapshotView";
import styles from "../../../../src/pages/admin/Analytics.module.css";
import { AdminTrends } from "./AdminTrends";
import { FieldRows, formatCost, formatDate, formatDuration, LoadState, PAGE_SIZE, Pagination, RefreshButton, useResource, } from "./shared";
import { SnapshotView } from "./SnapshotView";
function formatAverageDuration(value: number | null): string {
    if (value === null)
        return '—';
    const rounded = Math.round(value);
    return rounded < 1000 ? `${rounded} ms` : `${(rounded / 1000).toFixed(2)} 秒`;
}
/** 单次任务的均值：先按任务汇总再对任务取平均，不是对 run 行取平均。 */
function Averages({ value }: {
    value: AdminTaskAverages;
}) {
    if (value.avg_runs_per_task === null)
        return renderNode("span", { "class": styles.muted }, ["无任务"]);
    return (renderNode(FieldRows, { "rows": [
            ["预估成本", formatCost(value.avg_cost_per_task ?? 0)],
            ["耗时", formatAverageDuration(value.avg_duration_ms_per_task)],
            ["调用", `${value.avg_runs_per_task.toFixed(1)} 次/任务`],
        ] }));
}
const FindingsPanel = defineComponent((props: {
    token: string;
    projectId: string;
    onForbidden: () => void;
}) => {
    const draftSeverity = shallowRef("");
    const setDraftSeverity = (next: typeof draftSeverity.value | ((old: typeof draftSeverity.value) => typeof draftSeverity.value)) => { draftSeverity.value = typeof next === "function" ? next(draftSeverity.value) : next; };
    const draftChapter = shallowRef("");
    const setDraftChapter = (next: typeof draftChapter.value | ((old: typeof draftChapter.value) => typeof draftChapter.value)) => { draftChapter.value = typeof next === "function" ? next(draftChapter.value) : next; };
    const filters = shallowRef<{
        severity: string;
        chapterSeq?: number;
    }>({ severity: "" });
    const setFilters = (next: typeof filters.value | ((old: typeof filters.value) => typeof filters.value)) => { filters.value = typeof next === "function" ? next(filters.value) : next; };
    const offset = shallowRef(0);
    const setOffset = (next: typeof offset.value | ((old: typeof offset.value) => typeof offset.value)) => { offset.value = typeof next === "function" ? next(offset.value) : next; };
    const load = (signal: AbortSignal) => adminApi.listFindings(props.token, props.projectId, { ...filters.value, limit: PAGE_SIZE, offset: offset.value }, signal);
    const resource = useResource<PageResult<AdminSnapshotFinding>>(load, props.onForbidden);
    const submit = (event: SubmitEvent) => {
        event.preventDefault();
        setOffset(0);
        const chapter = Number(draftChapter.value);
        setFilters({
            severity: draftSeverity.value.trim(),
            chapterSeq: draftChapter.value.trim() !== "" && Number.isFinite(chapter) ? chapter : undefined,
        });
    };
    return () => {
        return (renderNode("section", { "class": `panel ${styles.panel}` }, [
            renderNode("div", { "class": styles.panelHead }, [
                renderNode("div", {}, [renderNode("h3", {}, ["校验发现"])]), renderNode(RefreshButton, { "onClick": resource.retry })
            ]), renderNode("form", { "class": styles.filters, "aria-label": "发现筛选", "onSubmit": submit }, [
                renderNode("label", {}, [
                    renderNode("span", {}, ["严重度"]), renderNode("select", { "class": "input", "value": draftSeverity.value, "onChange": (event: Event) => setDraftSeverity((event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [
                        renderNode("option", { "value": "" }, ["全部程度"]), ["critical", "major", "minor", "hint"].map((severity: string) => renderNode("option", { "key": severity, "value": severity }, [severityLabel(severity)]))
                    ])
                ]), renderNode("label", {}, [
                    renderNode("span", {}, ["章号"]), renderNode("input", { "class": "input", "type": "number", "min": 1, "value": draftChapter.value, "onInput": (event: Event) => setDraftChapter((event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [])
                ]), renderNode("button", { "class": "btn btn-primary", "type": "submit" }, ["筛选"])
            ]), renderNode(LoadState, { ...resource, "empty": resource.data?.items.length === 0, children: [resource.data && renderNode(Fragment, {}, [
                        renderNode("div", { "class": styles.tableWrap }, [renderNode("table", {}, [
                                renderNode("thead", {}, [renderNode("tr", {}, [
                                        renderNode("th", {}, ["章"]), renderNode("th", {}, ["第几次"]), renderNode("th", {}, ["严重度"]), renderNode("th", {}, ["类型"]), renderNode("th", {}, ["范围"]), renderNode("th", {}, ["来源"]), renderNode("th", {}, ["建议"]), renderNode("th", {}, ["证据"])
                                    ])]), renderNode("tbody", {}, [resource.data.items.map((finding: AdminSnapshotFinding, index: number) => renderNode("tr", { "key": `${finding.snapshot_id}-${index}` }, [
                                        renderNode("td", {}, [
                                            "第 ", finding.chapter_seq ?? "—", " 章"
                                        ]), renderNode("td", {}, [
                                            "第 ", finding.attempt, " 次"
                                        ]), renderNode("td", {}, [renderNode("span", { "class": severityClass(finding.severity) }, [finding.severity ? severityLabel(finding.severity) : "未标"])]), renderNode("td", {}, [finding.conflict_type ? conflictTypeLabel(finding.conflict_type) : "—"]), renderNode("td", {}, [finding.scope ? scopeLabel(finding.scope) : "—"]), renderNode("td", {}, [finding.source ? findingSourceLabel(finding.source) : "—"]), renderNode("td", {}, [finding.suggestion ?? "—"]), renderNode("td", {}, [finding.evidence.map((item: import("../../../../src/lib/adminApi").SnapshotEvidence) => `第 ${item.chapter} 章：${item.quote}`).join("；") || "—"])
                                    ]))])
                            ])]), renderNode(Pagination, { "total": resource.data.total, "offset": offset.value, "onChange": setOffset })
                    ])] })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        projectId: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
function ChapterSnapshots({ chapter, onSelect }: {
    chapter: AdminTaskChapter;
    onSelect: (snapshotId: number | null) => void;
}) {
    if (chapter.snapshots.length === 0)
        return renderNode("p", { "class": styles.muted }, ["这一章没有落盘快照"]);
    return (renderNode("div", { "class": styles.tableWrap }, [renderNode("table", {}, [
            renderNode("thead", {}, [renderNode("tr", {}, [
                    renderNode("th", {}, ["阶段"]), renderNode("th", {}, ["第几次"]), renderNode("th", {}, ["时间"]), renderNode("th", {}, ["模型"]), renderNode("th", {}, ["预估成本"]), renderNode("th", {}, ["耗时"]), renderNode("th", {}, ["降级"]), renderNode("th", {}, ["操作"])
                ])]), renderNode("tbody", {}, [chapter.snapshots.map((ref: import("../../../../src/lib/adminApi").AdminSnapshotRef) => renderNode("tr", { "key": ref.id }, [
                    renderNode("td", {}, [nodeLabel(ref.stage)]), renderNode("td", {}, [
                        "第 ", ref.attempt, " 次"
                    ]), renderNode("td", {}, [formatDate(ref.created_at)]), renderNode("td", {}, [ref.model_id ?? "未记录"]), renderNode("td", {}, [formatCost(ref.cost_est)]), renderNode("td", {}, [formatDuration(ref.duration_ms)]), renderNode("td", {}, [ref.degraded ? "是" : "否"]), renderNode("td", {}, [renderNode("button", { "type": "button", "class": "btn btn-quiet", "aria-label": `查看第 ${chapter.chapter_seq} 章 ${ref.stage} 快照`, "onClick": () => onSelect(ref.id) }, ["查看"])])
                ]))])
        ])]));
}
const TaskChapters = defineComponent((props: {
    token: string;
    task: AdminGenerationTask;
    onForbidden: () => void;
}) => {
    const offset = shallowRef(0);
    const setOffset = (next: typeof offset.value | ((old: typeof offset.value) => typeof offset.value)) => { offset.value = typeof next === "function" ? next(offset.value) : next; };
    const chapter = shallowRef<AdminTaskChapter | null>(null);
    const setChapter = (next: typeof chapter.value | ((old: typeof chapter.value) => typeof chapter.value)) => { chapter.value = typeof next === "function" ? next(chapter.value) : next; };
    const snapshotId = shallowRef<number | null>(null);
    const setSnapshotId = (next: typeof snapshotId.value | ((old: typeof snapshotId.value) => typeof snapshotId.value)) => { snapshotId.value = typeof next === "function" ? next(snapshotId.value) : next; };
    const load = (signal: AbortSignal) => adminApi.listTaskChapters(props.token, props.task.id, { limit: PAGE_SIZE, offset: offset.value }, signal);
    const resource = useResource<PageResult<AdminTaskChapter>>(load, props.onForbidden);
    return () => {
        return (renderNode("section", { "class": `panel ${styles.panel}` }, [
            renderNode("div", { "class": styles.panelHead }, [
                renderNode("div", {}, [renderNode("h3", {}, [
                        taskTypeLabel(props.task.task_type), " · 每章分解（", taskChapterLabel(props.task), "）"
                    ])]), renderNode(RefreshButton, { "onClick": resource.retry })
            ]), renderNode(LoadState, { ...resource, "empty": resource.data?.items.length === 0, children: [resource.data && renderNode(Fragment, {}, [
                        renderNode("div", { "class": styles.tableWrap }, [renderNode("table", {}, [
                                renderNode("thead", {}, [renderNode("tr", {}, [
                                        renderNode("th", {}, ["章"]), renderNode("th", {}, ["跑过的节点"]), renderNode("th", {}, ["运行"]), renderNode("th", {}, ["token 合计"]), renderNode("th", {}, ["预估成本"]), renderNode("th", {}, ["耗时"]), renderNode("th", {}, ["快照"]), renderNode("th", {}, ["操作"])
                                    ])]), renderNode("tbody", {}, [resource.data.items.map((row: AdminTaskChapter) => renderNode("tr", { "key": String(row.chapter_seq) }, [
                                        renderNode("td", {}, [
                                            "第 ", row.chapter_seq ?? "—", " 章"
                                        ]), renderNode("td", {}, [row.stages.map(nodeLabel).join("、") || "无"]), renderNode("td", {}, [row.metrics.run_count]), renderNode("td", {}, [(row.metrics.input_tokens + row.metrics.output_tokens).toLocaleString()]), renderNode("td", {}, [formatCost(row.metrics.cost_est)]), renderNode("td", {}, [formatDuration(row.metrics.duration_ms)]), renderNode("td", {}, [row.snapshots.length]), renderNode("td", {}, [renderNode("button", { "type": "button", "class": "btn btn-quiet", "aria-label": `查看第 ${row.chapter_seq} 章的快照`, "onClick": () => { setSnapshotId(null); setChapter(row); } }, ["快照"])])
                                    ]))])
                            ])]), renderNode(Pagination, { "total": resource.data.total, "offset": offset.value, "onChange": (next: number) => { setChapter(null); setSnapshotId(null); setOffset(next); } })
                    ])] }), chapter.value && renderNode("div", { "class": styles.drilldown }, [
                renderNode("div", { "class": styles.panelHead }, [
                    renderNode("div", {}, [renderNode("h4", {}, [
                            "第 ", chapter.value.chapter_seq ?? "—", " 章的快照"
                        ])]), renderNode("button", { "type": "button", "class": "btn btn-quiet", "onClick": () => { setChapter(null); setSnapshotId(null); } }, ["收起"])
                ]), renderNode(ChapterSnapshots, { "chapter": chapter.value, "onSelect": setSnapshotId })
            ]), snapshotId.value !== null && renderNode(SnapshotView, { "key": snapshotId.value, "token": props.token, "snapshotId": snapshotId.value, "onForbidden": props.onForbidden })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        task: { type: Object as PropType<AdminGenerationTask>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
const BookTasks = defineComponent((props: {
    token: string;
    project: AdminProject;
    onForbidden: () => void;
}) => {
    const offset = shallowRef(0);
    const setOffset = (next: typeof offset.value | ((old: typeof offset.value) => typeof offset.value)) => { offset.value = typeof next === "function" ? next(offset.value) : next; };
    const task = shallowRef<AdminGenerationTask | null>(null);
    const setTask = (next: typeof task.value | ((old: typeof task.value) => typeof task.value)) => { task.value = typeof next === "function" ? next(task.value) : next; };
    const load = (signal: AbortSignal) => adminApi.listGenerationTasks(props.token, props.project.id, { limit: PAGE_SIZE, offset: offset.value }, signal);
    const resource = useResource<PageResult<AdminGenerationTask>>(load, props.onForbidden);
    return () => {
        return (renderNode("div", { "class": styles.drilldown }, [
            renderNode("section", { "class": `panel ${styles.panel}` }, [
                renderNode("div", { "class": styles.panelHead }, [
                    renderNode("div", {}, [renderNode("h3", {}, [
                            "《", props.project.title, "》的任务"
                        ])]), renderNode(RefreshButton, { "onClick": resource.retry })
                ]), renderNode(LoadState, { ...resource, "empty": resource.data?.items.length === 0, children: [resource.data && renderNode(Fragment, {}, [
                            renderNode("div", { "class": styles.tableWrap }, [renderNode("table", {}, [
                                    renderNode("thead", {}, [renderNode("tr", {}, [
                                            renderNode("th", {}, ["任务"]), renderNode("th", {}, ["状态"]), renderNode("th", {}, ["目标章节"]), renderNode("th", {}, ["章数"]), renderNode("th", {}, ["快照"]), renderNode("th", {}, ["运行"]), renderNode("th", {}, ["token 合计"]), renderNode("th", {}, ["预估成本"]), renderNode("th", {}, ["耗时"]), renderNode("th", {}, ["重试"]), renderNode("th", {}, ["创建时间"]), renderNode("th", {}, ["操作"])
                                        ])]), renderNode("tbody", {}, [resource.data.items.map((row: AdminGenerationTask) => renderNode("tr", { "key": row.id }, [
                                            renderNode("td", {}, [taskTypeLabel(row.task_type)]), renderNode("td", {}, [taskStatusLabel(row.status)]), renderNode("td", {}, [taskChapterLabel(row)]), renderNode("td", {}, [row.chapter_count]), renderNode("td", {}, [row.snapshot_count]), renderNode("td", {}, [row.metrics.run_count]), renderNode("td", {}, [(row.metrics.input_tokens + row.metrics.output_tokens).toLocaleString()]), renderNode("td", {}, [formatCost(row.metrics.cost_est)]), renderNode("td", {}, [formatDuration(row.metrics.duration_ms)]), renderNode("td", {}, [row.retry_count]), renderNode("td", {}, [formatDate(row.created_at)]), renderNode("td", {}, [renderNode("button", { "type": "button", "class": "btn btn-quiet", "aria-label": `查看任务 ${row.id} 的每章分解`, "onClick": () => setTask(row) }, ["每章"])])
                                        ]))])
                                ])]), renderNode(Pagination, { "total": resource.data.total, "offset": offset.value, "onChange": (next: number) => { setTask(null); setOffset(next); } })
                        ])] })
            ]), task.value && renderNode(TaskChapters, { "key": task.value.id, "token": props.token, "task": task.value, "onForbidden": props.onForbidden }), renderNode(FindingsPanel, { "token": props.token, "projectId": props.project.id, "onForbidden": props.onForbidden })
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
const UserBooks = defineComponent((props: {
    token: string;
    user: AdminUser;
    onForbidden: () => void;
}) => {
    const offset = shallowRef(0);
    const setOffset = (next: typeof offset.value | ((old: typeof offset.value) => typeof offset.value)) => { offset.value = typeof next === "function" ? next(offset.value) : next; };
    const project = shallowRef<AdminProject | null>(null);
    const setProject = (next: typeof project.value | ((old: typeof project.value) => typeof project.value)) => { project.value = typeof next === "function" ? next(project.value) : next; };
    const load = (signal: AbortSignal) => adminApi.listProjects(props.token, { userId: props.user.id, limit: PAGE_SIZE, offset: offset.value }, signal);
    const resource = useResource<PageResult<AdminProject>>(load, props.onForbidden);
    return () => {
        return (renderNode("div", { "class": styles.drilldown }, [
            renderNode("section", { "class": `panel ${styles.panel}` }, [
                renderNode("div", { "class": styles.panelHead }, [
                    renderNode("div", {}, [renderNode("h3", {}, [
                            props.user.username, " 的作品"
                        ])]), renderNode(RefreshButton, { "onClick": resource.retry })
                ]), renderNode(LoadState, { ...resource, "empty": resource.data?.items.length === 0, children: [resource.data && renderNode(Fragment, {}, [
                            renderNode("div", { "class": styles.tableWrap }, [renderNode("table", {}, [
                                    renderNode("thead", {}, [renderNode("tr", {}, [
                                            renderNode("th", {}, ["作品"]), renderNode("th", {}, ["题材"]), renderNode("th", {}, ["状态"]), renderNode("th", {}, ["章节"]), renderNode("th", {}, ["字数"]), renderNode("th", {}, ["任务"]), renderNode("th", {}, ["运行"]), renderNode("th", {}, ["单次任务均值"]), renderNode("th", {}, ["操作"])
                                        ])]), renderNode("tbody", {}, [resource.data.items.map((row: AdminProject) => renderNode("tr", { "key": row.id }, [
                                            renderNode("td", {}, [row.title]), renderNode("td", {}, [row.genre || "—"]), renderNode("td", {}, [creationStatusLabel(row.creation_status)]), renderNode("td", {}, [row.chapter_count]), renderNode("td", {}, [row.word_count.toLocaleString()]), renderNode("td", {}, [row.task_count]), renderNode("td", {}, [row.metrics.run_count]), renderNode("td", {}, [renderNode(Averages, { "value": row.task_averages })]), renderNode("td", {}, [renderNode("button", { "type": "button", "class": "btn btn-quiet", "aria-label": `查看《${row.title}》的分析`, "onClick": () => setProject(row) }, ["下钻"])])
                                        ]))])
                                ])]), renderNode(Pagination, { "total": resource.data.total, "offset": offset.value, "onChange": (next: number) => { setProject(null); setOffset(next); } })
                        ])] })
            ]), project.value && renderNode(BookTasks, { "key": project.value.id, "token": props.token, "project": project.value, "onForbidden": props.onForbidden })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        user: { type: Object as PropType<AdminUser>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
export const Analytics = defineComponent((props: {
    token: string;
    onForbidden: () => void;
}) => {
    const draft = shallowRef("");
    const setDraft = (next: typeof draft.value | ((old: typeof draft.value) => typeof draft.value)) => { draft.value = typeof next === "function" ? next(draft.value) : next; };
    const q = shallowRef("");
    const setQ = (next: typeof q.value | ((old: typeof q.value) => typeof q.value)) => { q.value = typeof next === "function" ? next(q.value) : next; };
    const offset = shallowRef(0);
    const setOffset = (next: typeof offset.value | ((old: typeof offset.value) => typeof offset.value)) => { offset.value = typeof next === "function" ? next(offset.value) : next; };
    const user = shallowRef<AdminUser | null>(null);
    const setUser = (next: typeof user.value | ((old: typeof user.value) => typeof user.value)) => { user.value = typeof next === "function" ? next(user.value) : next; };
    const load = (signal: AbortSignal) => adminApi.listUsers(props.token, { q: q.value, limit: PAGE_SIZE, offset: offset.value }, signal);
    const resource = useResource<PageResult<AdminUser>>(load, props.onForbidden);
    const submit = (event: SubmitEvent) => {
        event.preventDefault();
        setUser(null);
        setOffset(0);
        setQ(draft.value.trim());
    };
    return () => {
        return (renderNode("section", { "class": styles.view, "aria-labelledby": "analytics-heading" }, [
            renderNode("div", { "class": styles.viewHead }, [
                renderNode("div", {}, [renderNode("h1", { "id": "analytics-heading" }, ["数据分析"])]), renderNode(RefreshButton, { "onClick": resource.retry })
            ]), renderNode(AdminTrends, { "token": props.token, "onForbidden": props.onForbidden }), renderNode("h3", {}, ["用户与作品明细"]), renderNode("form", { "class": styles.filters, "role": "search", "aria-label": "用户筛选", "onSubmit": submit }, [
                renderNode("label", {}, [
                    renderNode("span", {}, ["搜索用户"]), renderNode("input", { "class": "input", "maxLength": 128, "value": draft.value, "onInput": (event: Event) => setDraft((event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [])
                ]), renderNode("button", { "class": "btn btn-primary", "type": "submit" }, ["搜索"])
            ]), renderNode(LoadState, { ...resource, "empty": resource.data?.items.length === 0, children: [resource.data && renderNode(Fragment, {}, [
                        renderNode("div", { "class": styles.tableWrap }, [renderNode("table", {}, [
                                renderNode("thead", {}, [renderNode("tr", {}, [
                                        renderNode("th", {}, ["用户"]), renderNode("th", {}, ["角色"]), renderNode("th", {}, ["等级"]), renderNode("th", {}, ["作品"]), renderNode("th", {}, ["章节"]), renderNode("th", {}, ["字数"]), renderNode("th", {}, ["任务"]), renderNode("th", {}, ["运行"]), renderNode("th", {}, ["单次任务均值"]), renderNode("th", {}, ["操作"])
                                    ])]), renderNode("tbody", {}, [resource.data.items.map((row: AdminUser) => renderNode("tr", { "key": row.id }, [
                                        renderNode("td", {}, [row.username]), renderNode("td", {}, [roleLabel(row.role)]), renderNode("td", {}, [tierLabel(row.tier)]), renderNode("td", {}, [row.project_count]), renderNode("td", {}, [row.chapter_count]), renderNode("td", {}, [row.word_count.toLocaleString()]), renderNode("td", {}, [row.task_count]), renderNode("td", {}, [row.metrics.run_count]), renderNode("td", {}, [renderNode(Averages, { "value": row.task_averages })]), renderNode("td", {}, [renderNode("button", { "type": "button", "class": "btn btn-quiet", "aria-label": `分析 ${row.username}`, "onClick": () => setUser(row) }, ["下钻"])])
                                    ]))])
                            ])]), renderNode(Pagination, { "total": resource.data.total, "offset": offset.value, "onChange": (next: number) => { setUser(null); setOffset(next); } })
                    ])] }), user.value && renderNode(UserBooks, { "key": user.value.id, "token": props.token, "user": user.value, "onForbidden": props.onForbidden })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
Averages.props = ["value"];
Averages.inheritAttrs = false;
ChapterSnapshots.props = ["chapter", "onSelect"];
ChapterSnapshots.inheritAttrs = false;
