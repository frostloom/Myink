/* eslint-disable vue/one-component-per-file -- Native Vue render helpers stay with their owning page. */
import type { PropType } from 'vue';
import { computed, defineComponent, Fragment, h as renderNode, shallowRef } from 'vue';
import { useRoute } from 'vue-router';
import { adminApi, type AdminRun, type AdminTaskDetail, type AdminPage as PageResult } from "../../../../src/lib/adminApi";
import { nodeLabel, taskChapterLabel, taskStatusLabel, taskTypeLabel } from "../../../../src/lib/labels";
import { asRecord } from "../../../../src/lib/snapshotView";
import layout from "../../../../src/pages/admin/ExecutionDetail.module.css";
import styles from "../../../../src/pages/AdminPage.module.css";
import { useAdminContext } from './context';
import { Disclosure, ExecutionError } from "./ExecutionContent";
import { RunDetailView } from "./RunDetail";
import { CapturedView, DetailPage, formatCost, formatDate, formatDuration, LoadState, PAGE_SIZE, Pagination, RefreshButton, useResource } from "./shared";
export const TaskDetailView = defineComponent((props: {
    token: string;
    taskId: string;
    onForbidden: () => void;
}) => {
    const offset = shallowRef(0);
    const setOffset = (next: typeof offset.value | ((old: typeof offset.value) => typeof offset.value)) => { offset.value = typeof next === "function" ? next(offset.value) : next; };
    const runId = shallowRef<number | null>(null);
    const setRunId = (next: typeof runId.value | ((old: typeof runId.value) => typeof runId.value)) => { runId.value = typeof next === "function" ? next(runId.value) : next; };
    const loadTask = (signal: AbortSignal) => adminApi.getTask(props.token, props.taskId, signal);
    const loadRuns = (signal: AbortSignal) => adminApi.listTaskRuns(props.token, props.taskId, { limit: PAGE_SIZE, offset: offset.value }, signal);
    const detail = useResource<AdminTaskDetail>(loadTask, props.onForbidden);
    const runs = useResource<PageResult<AdminRun>>(loadRuns, props.onForbidden);
    const value = computed(() => (detail.data));
    const payload = computed(() => (asRecord(value.value?.payload.data)));
    const snapshot = computed(() => (asRecord(payload.value?.writing_resources)));
    const library = computed(() => (Array.isArray(snapshot.value?.reference_library) ? snapshot.value.reference_library : []));
    const roles = computed(() => (asRecord(snapshot.value?.role_prompts)));
    const groups = computed(() => {
        const result = new Map<string, AdminRun[]>();
        for (const run of runs.data?.items ?? [])
            result.set(run.node, [...(result.get(run.node) ?? []), run]);
        return result;
    });
    return () => {
        return (renderNode("div", { "class": styles.drilldown }, [
            renderNode("section", { "class": `panel ${styles.detail}` }, [renderNode(LoadState, { ...detail, "empty": !value.value, children: [value.value && renderNode("div", { "class": layout.summary }, [
                            renderNode("div", { "class": layout.summaryHead }, [
                                renderNode("div", {}, [
                                    renderNode("h2", {}, [value.value.project_title]), renderNode("p", { "class": layout.meta }, [
                                        renderNode("span", {}, [taskTypeLabel(value.value.task_type)]), renderNode("span", {}, [value.value.username]), renderNode("span", { "class": "badge" }, [taskStatusLabel(value.value.status)])
                                    ])
                                ]), renderNode(RefreshButton, { "onClick": () => { detail.retry(); runs.retry(); } })
                            ]), renderNode("dl", { "class": layout.readings }, [
                                renderNode("div", {}, [
                                    renderNode("dt", {}, ["任务跨度"]), renderNode("dd", {}, [formatDuration(value.value.elapsed_ms)])
                                ]), renderNode("div", {}, [
                                    renderNode("dt", {}, ["模型调用"]), renderNode("dd", {}, [
                                        value.value.metrics.run_count, " 次"
                                    ])
                                ]), renderNode("div", {}, [
                                    renderNode("dt", {}, ["预估成本"]), renderNode("dd", {}, [formatCost(value.value.metrics.cost_est)])
                                ]), renderNode("div", {}, [
                                    renderNode("dt", {}, ["目标篇幅"]), renderNode("dd", {}, [
                                        typeof payload.value?.chapter_count === "number" ? `${payload.value.chapter_count} 章` : taskChapterLabel(value.value), typeof payload.value?.chars_per_chapter === "number" ? ` · 每章 ${payload.value.chars_per_chapter} 字` : ""
                                    ])
                                ])
                            ]), renderNode("p", { "class": layout.muted }, [
                                "创建于 ", formatDate(value.value.created_at), " · 更新于 ", formatDate(value.value.updated_at)
                            ]), Boolean(value.value.error.data) && renderNode(ExecutionError, { "value": value.value.error, "label": "任务错误" })
                        ])] })]), renderNode("section", { "class": `panel ${styles.detail}`, "aria-label": "执行记录" }, [
                renderNode("div", { "class": styles.detailHead }, [renderNode("div", {}, [
                        renderNode("h3", {}, ["执行记录"]), renderNode("p", {}, ["按创作环节分组；展开一次模型调用，查看输出和实际资料查阅。"])
                    ])]), renderNode(LoadState, { ...runs, "empty": runs.data?.items.length === 0, children: [Array.from(groups.value, ([node, items]) => renderNode("section", { "key": node, "class": layout.group }, [
                            renderNode("div", { "class": layout.groupHead }, [
                                renderNode("h4", {}, [nodeLabel(node)]), renderNode("span", {}, [
                                    "本页 ", items.length, " 次调用"
                                ])
                            ]), renderNode("div", { "class": layout.calls }, [items.sort((a: AdminRun, b: AdminRun) => Date.parse(a.created_at) - Date.parse(b.created_at) || a.id - b.id).map((run: AdminRun) => renderNode("div", { "key": run.id }, [
                                    renderNode("button", { "type": "button", "class": layout.call, "aria-label": `查看节点 ${run.node} #${run.id}`, "aria-expanded": runId.value === run.id, "onClick": () => setRunId(runId.value === run.id ? null : run.id) }, [
                                        renderNode("span", { "class": layout.callMain }, [
                                            renderNode("strong", {}, [run.model_id ?? "未记录模型"]), renderNode("span", { "class": layout.callMeta }, [
                                                renderNode("span", {}, [
                                                    "记录 #", run.id
                                                ]), renderNode("span", {}, [formatDate(run.created_at)]), run.degraded && renderNode("span", {}, ["使用备用模型"]), run.retry_count > 0 && renderNode("span", {}, [
                                                    "重试 ", run.retry_count, " 次"
                                                ])
                                            ])
                                        ]), renderNode("span", { "class": layout.callMeta }, [
                                            renderNode("span", {}, [formatDuration(run.duration_ms)]), renderNode("span", {}, [
                                                "预估 ", formatCost(run.cost_est)
                                            ]), renderNode("span", {}, [runId.value === run.id ? "收起" : "查看详情"])
                                        ])
                                    ]), runId.value === run.id && renderNode(RunDetailView, { "token": props.token, "runId": run.id, "onForbidden": props.onForbidden })
                                ]))])
                        ])), runs.data && runs.data.total > PAGE_SIZE && renderNode(Pagination, { "total": runs.data.total, "offset": offset.value, "onChange": (next: number) => { setRunId(null); setOffset(next); } })] })
            ]), value.value && renderNode("section", { "class": `panel ${styles.detail}` }, [
                renderNode("h3", {}, ["本任务的资源版本"]), renderNode("p", { "class": layout.muted }, [roles.value || Array.isArray(snapshot.value?.reference_library) ? renderNode(Fragment, {}, [
                        "已冻结 ", roles.value ? Object.keys(roles.value).length : 0, " 类角色提示词、", library.value.length, " 项可查阅资料。", value.value.payload.truncated && "快照已截断，数量仅表示留存的条目。", "可用资料数量不代表实际查阅次数，请以执行记录中的查阅结果为准。"
                    ]) : "这条旧任务未保存资源版本，无法还原当时的可用资料；实际使用情况请查看执行记录。"]), renderNode(Disclosure, { "title": "技术诊断", children: [renderNode("dl", { "class": styles.summaryList }, [
                            renderNode("div", {}, [
                                renderNode("dt", {}, ["任务编号"]), renderNode("dd", {}, [value.value.id])
                            ]), renderNode("div", {}, [
                                renderNode("dt", {}, ["批次编号"]), renderNode("dd", {}, [value.value.batch_task_id ?? "无"])
                            ]), renderNode("div", {}, [
                                renderNode("dt", {}, ["任务重试"]), renderNode("dd", {}, [value.value.retry_count])
                            ])
                        ]), renderNode(CapturedView, { "value": value.value.payload, "raw": true, "label": "原始任务快照" }), Boolean(value.value.error.data) && renderNode(CapturedView, { "value": value.value.error, "raw": true, "label": "原始错误记录" })] })
            ])
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        taskId: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
export const TaskDetailPage = defineComponent((_props: Record<string, never>) => { const adminContext = useAdminContext(); const { onForbidden } = adminContext; const { taskId = "" } = (useRoute().params as Record<string, string>); return () => { return (renderNode(DetailPage, { "heading": "任务详情", "backTab": "tasks", children: [renderNode(TaskDetailView, { "token": adminContext.token, "taskId": taskId, "onForbidden": onForbidden })] })); }; }, {
    inheritAttrs: false,
    props: {}
});
