import { useAdminListNavigation } from './navigation';
import { useMemoryFormGuard } from '../../composables/useMemoryFormGuard';
import { ApiError } from '../../../../src/lib/api';
/* eslint-disable vue/one-component-per-file -- Native Vue render helpers stay with their owning page. */
import type { PropType } from 'vue';
import { computed, defineComponent, Fragment, h as renderNode, shallowRef, watch } from 'vue';
import { useRoute } from 'vue-router';
import { adminApi, type AdminAccessLog, type AdminInvitation, type AdminInvitationCreated, type AdminOverview, type AdminProject, type AdminRun, type AdminTask, type AdminUser, type AdminPage as PageResult, } from "../../../../src/lib/adminApi";
import { formatApiError } from "../../../../src/lib/apiError";
import { creationStatusLabel, NODE_LABELS, taskChapterLabel, taskStatusLabel, taskTypeLabel, tierLabel, } from "../../../../src/lib/labels";
import styles from "../../../../src/pages/AdminPage.module.css";
import type { Feedback } from "../../../../src/types";
import AttachmentChip from "../../components/AttachmentChip.vue";
import { AccessLogContent } from "./AccessLogContent";
import { AdminTrends } from "./AdminTrends";
import { Analytics } from "./Analytics";
import { useAdminContext } from './context';
import { RunDetailDialog, RunTable } from "./RunDetail";
import { formatCost, formatDate, LoadState, metricEntries, PAGE_SIZE, Pagination, RefreshButton, useResource } from "./shared";
type Tab = 'overview' | 'analytics' | 'users' | 'projects' | 'tasks' | 'runs' | 'logs' | 'invites' | 'feedback';
const TABS: Array<[
    Tab,
    string
]> = [
    ['overview', '概览'], ['analytics', '分析'], ['users', '用户'], ['projects', '作品'], ['tasks', '任务'],
    ['runs', '全部运行'], ['logs', '访问日志'], ['invites', '邀请码'], ['feedback', '反馈'],
];
const OverviewView = defineComponent((props: {
    token: string;
    onForbidden: () => void;
}) => {
    const load = (signal: AbortSignal) => adminApi.getOverview(props.token, signal);
    const resource = useResource<AdminOverview>(load, props.onForbidden);
    const value = computed(() => (resource.data));
    return () => {
        return (renderNode("section", { "class": styles.view, "aria-labelledby": "overview-heading" }, [
            renderNode("div", { "class": styles.viewHead }, [
                renderNode("div", {}, [renderNode("h1", { "id": "overview-heading" }, ["全局概览"])]), renderNode(RefreshButton, { "onClick": resource.retry })
            ]), renderNode(LoadState, { ...resource, "empty": !value.value, children: [value.value && (renderNode(Fragment, {}, [
                        renderNode("dl", { "class": styles.readout }, [
                            renderNode("div", { "class": styles.lead }, [
                                renderNode("dt", {}, ["用户"]), renderNode("dd", {}, [value.value.user_count])
                            ]), renderNode("div", { "class": styles.lead }, [
                                renderNode("dt", {}, ["作品"]), renderNode("dd", {}, [value.value.project_count])
                            ]), renderNode("div", { "class": styles.lead }, [
                                renderNode("dt", {}, ["章节"]), renderNode("dd", {}, [value.value.chapter_count])
                            ]), renderNode("div", { "class": styles.lead }, [
                                renderNode("dt", {}, ["任务"]), renderNode("dd", {}, [value.value.task_count])
                            ]), metricEntries(value.value.metrics).map(([label, text]) => (renderNode("div", { "key": label }, [
                                renderNode("dt", {}, [label]), renderNode("dd", {}, [text])
                            ])))
                        ]), Object.keys(value.value.task_status_counts).length === 0 ? renderNode("div", { "class": "empty" }, ["暂无状态统计"]) : (renderNode("dl", { "class": styles.statuses }, [Object.entries(value.value.task_status_counts).map(([name, count]) => (renderNode("div", { "key": name }, [
                                renderNode("dt", {}, [taskStatusLabel(name)]), renderNode("dd", {}, [count])
                            ])))]))
                    ]))] }), renderNode(AdminTrends, { "token": props.token, "onForbidden": props.onForbidden })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
const UsersView = defineComponent((props: {
    token: string;
    onForbidden: () => void;
}) => {
    const { filters, offset, setFilters, setOffset, openDetail: navigate } = useAdminListNavigation({ q: '' });
    const q = computed(() => filters.value.q);
    const draftQ = shallowRef(q.value);
    watch(q, value => { draftQ.value = value; });
    const setDraftQ = (value: string) => { draftQ.value = value; };
    const setQ = (value: string) => setFilters({ q: value });
    const load = (signal: AbortSignal) => adminApi.listUsers(props.token, { q: q.value, limit: PAGE_SIZE, offset: offset.value }, signal);
    const resource = useResource<PageResult<AdminUser>>(load, props.onForbidden);
    const submit = (event: SubmitEvent) => { event.preventDefault(); setQ(draftQ.value.trim()); };
    return () => {
        return (renderNode("section", { "class": styles.view, "aria-labelledby": "users-heading" }, [
            renderNode("div", { "class": styles.viewHead }, [
                renderNode("div", {}, [renderNode("h1", { "id": "users-heading" }, ["用户"])]), renderNode(RefreshButton, { "onClick": resource.retry })
            ]), renderNode("form", { "class": styles.filters, "role": "search", "aria-label": "用户筛选", "onSubmit": submit }, [
                renderNode("label", {}, [
                    renderNode("span", {}, ["用户名或 ID"]), renderNode("input", { "class": "input", "value": draftQ.value, "maxLength": 128, "onInput": (e: Event) => setDraftQ((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [])
                ]), renderNode("button", { "class": "btn btn-primary", "type": "submit" }, ["筛选"])
            ]), renderNode(LoadState, { ...resource, "empty": resource.data?.items.length === 0, children: [resource.data && renderNode(Fragment, {}, [
                        renderNode("div", { "class": styles.tableWrap }, [renderNode("table", {}, [
                                renderNode("thead", {}, [renderNode("tr", {}, [
                                        renderNode("th", {}, ["用户"]), renderNode("th", {}, ["等级"]), renderNode("th", {}, ["作品"]), renderNode("th", {}, ["章节"]), renderNode("th", {}, ["字数"]), renderNode("th", {}, ["运行"]), renderNode("th", {}, ["总花费"]), renderNode("th", {}, ["操作"])
                                    ])]), renderNode("tbody", {}, [resource.data.items.map((user: AdminUser) => renderNode("tr", { "key": user.id }, [
                                        renderNode("td", {}, [renderNode("strong", {}, [user.username])]), renderNode("td", {}, [tierLabel(user.tier)]), renderNode("td", {}, [user.project_count]), renderNode("td", {}, [user.chapter_count]), renderNode("td", {}, [user.word_count.toLocaleString()]), renderNode("td", {}, [user.metrics.run_count]), renderNode("td", {}, [formatCost(user.metrics.cost_est)]), renderNode("td", {}, [renderNode("button", { "type": "button", "class": "btn btn-quiet", "aria-label": `查看用户 ${user.username}`, "onClick": () => navigate(`/admin/users/${user.id}`) }, ["查看"])])
                                    ]))])
                            ])]), renderNode(Pagination, { "total": resource.data.total, "offset": offset.value, "onChange": setOffset })
                    ])] })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
const ProjectsView = defineComponent((props: {
    token: string;
    onForbidden: () => void;
}) => {
    const { filters, offset, setFilters, setOffset, openDetail: navigate } = useAdminListNavigation({ q: '', userId: '' });
    const draftQ = shallowRef(filters.value.q);
    const draftUser = shallowRef(filters.value.userId);
    watch(filters, value => { draftQ.value = value.q; draftUser.value = value.userId; });
    const setDraftQ = (value: string) => { draftQ.value = value; };
    const setDraftUser = (value: string) => { draftUser.value = value; };
    const load = (signal: AbortSignal) => adminApi.listProjects(props.token, { ...filters.value, limit: PAGE_SIZE, offset: offset.value }, signal);
    const resource = useResource<PageResult<AdminProject>>(load, props.onForbidden);
    const groups = computed(() => {
        const accounts = new Map<string, { username: string; projects: AdminProject[] }>();
        for (const project of resource.data?.items ?? []) {
            if (!accounts.has(project.user_id)) accounts.set(project.user_id, { username: project.username, projects: [] });
            accounts.get(project.user_id)!.projects.push(project);
        }
        return [...accounts.entries()];
    });
    const submit = (event: SubmitEvent) => {
        event.preventDefault();
        setFilters({ q: draftQ.value.trim(), userId: draftUser.value.trim() });
    };
    return () => {
        return (renderNode("section", { "class": styles.view, "aria-labelledby": "projects-heading" }, [
            renderNode("div", { "class": styles.viewHead }, [
                renderNode("div", {}, [renderNode("h1", { "id": "projects-heading" }, ["作品"])]), renderNode(RefreshButton, { "onClick": resource.retry })
            ]), renderNode("form", { "class": styles.filters, "role": "search", "aria-label": "作品筛选", "onSubmit": submit }, [
                renderNode("label", {}, [
                    renderNode("span", {}, ["作品搜索"]), renderNode("input", { "class": "input", "value": draftQ.value, "maxLength": 128, "onInput": (event: Event) => setDraftQ((event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [])
                ]), renderNode("label", {}, [
                    renderNode("span", {}, ["用户 ID"]), renderNode("input", { "class": "input", "value": draftUser.value, "onInput": (event: Event) => setDraftUser((event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [])
                ]), renderNode("button", { "class": "btn btn-primary", "type": "submit" }, ["筛选"])
            ]), renderNode(LoadState, { ...resource, "empty": resource.data?.items.length === 0, children: [resource.data && renderNode(Fragment, {}, [
                        groups.value.map(([userId, group]) => renderNode("section", { key: userId, class: styles.projectGroup }, [renderNode("h3", {}, [group.username]), renderNode("div", { "class": styles.tableWrap }, [renderNode("table", { "aria-label": `${group.username}的作品` }, [
                                renderNode("thead", {}, [renderNode("tr", {}, [
                                        renderNode("th", {}, ["作品"]), renderNode("th", {}, ["作者"]), renderNode("th", {}, ["状态"]), renderNode("th", {}, ["章节"]), renderNode("th", {}, ["字数"]), renderNode("th", {}, ["任务"]), renderNode("th", {}, ["运行"]), renderNode("th", {}, ["预估成本"]), renderNode("th", {}, ["操作"])
                                    ])]), renderNode("tbody", {}, [group.projects.map((project: AdminProject) => renderNode("tr", { "key": project.id }, [
                                        renderNode("td", {}, [renderNode("strong", {}, [project.title])]), renderNode("td", {}, [project.username]), renderNode("td", {}, [creationStatusLabel(project.creation_status)]), renderNode("td", {}, [project.chapter_count]), renderNode("td", {}, [project.word_count.toLocaleString()]), renderNode("td", {}, [project.task_count]), renderNode("td", {}, [project.metrics.run_count]), renderNode("td", {}, [formatCost(project.metrics.cost_est)]), renderNode("td", {}, [renderNode("button", { "type": "button", "class": "btn btn-quiet", "aria-label": `查看《${project.title}》`, "onClick": () => navigate(`/admin/projects/${project.id}`) }, ["查看"])])
                                    ]))])
                            ])])])), renderNode(Pagination, { "total": resource.data.total, "offset": offset.value, "onChange": setOffset })
                    ])] })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
const TasksView = defineComponent((props: {
    token: string;
    onForbidden: () => void;
}) => {
    const { filters, offset, setFilters, setOffset, openDetail: navigate } = useAdminListNavigation({ userId: '', projectId: '', status: '' });
    const draft = shallowRef(filters.value);
    watch(filters, value => { draft.value = value; });
    const setDraft = (value: typeof draft.value) => { draft.value = value; };
    const load = (signal: AbortSignal) => adminApi.listTasks(props.token, { ...filters.value, limit: PAGE_SIZE, offset: offset.value }, signal);
    const resource = useResource<PageResult<AdminTask>>(load, props.onForbidden);
    const submit = (event: SubmitEvent) => {
        event.preventDefault();
        setFilters({
            userId: draft.value.userId.trim(),
            projectId: draft.value.projectId.trim(),
            status: draft.value.status.trim(),
        });
    };
    return () => {
        return (renderNode("section", { "class": styles.view, "aria-labelledby": "tasks-heading" }, [
            renderNode("div", { "class": styles.viewHead }, [
                renderNode("div", {}, [renderNode("h1", { "id": "tasks-heading" }, ["任务"])]), renderNode(RefreshButton, { "onClick": resource.retry })
            ]), renderNode("form", { "class": styles.filters, "aria-label": "任务筛选", "onSubmit": submit }, [
                renderNode("label", {}, [
                    renderNode("span", {}, ["用户 ID"]), renderNode("input", { "class": "input", "value": draft.value.userId, "onInput": (event: Event) => setDraft({ ...draft.value, userId: (event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }) }, [])
                ]), renderNode("label", {}, [
                    renderNode("span", {}, ["作品 ID"]), renderNode("input", { "class": "input", "value": draft.value.projectId, "onInput": (event: Event) => setDraft({ ...draft.value, projectId: (event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }) }, [])
                ]), renderNode("label", {}, [
                    renderNode("span", {}, ["状态"]), renderNode("select", { "class": "input", "value": draft.value.status, "onChange": (event: Event) => setDraft({ ...draft.value, status: (event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }) }, [
                        renderNode("option", { "value": "" }, ["全部状态"]), ["queued", "running", "paused", "awaiting_plan", "awaiting_review", "failed", "cancelled", "done"].map((status: string) => renderNode("option", { "key": status, "value": status }, [taskStatusLabel(status)]))
                    ])
                ]), renderNode("button", { "class": "btn btn-primary", "type": "submit" }, ["筛选"])
            ]), renderNode(LoadState, { ...resource, "empty": resource.data?.items.length === 0, children: [resource.data && renderNode(Fragment, {}, [
                        renderNode("div", { "class": styles.tableWrap }, [renderNode("table", {}, [
                                renderNode("thead", {}, [renderNode("tr", {}, [
                                        renderNode("th", {}, ["作品"]), renderNode("th", {}, ["用户"]), renderNode("th", {}, ["类型"]), renderNode("th", {}, ["状态"]), renderNode("th", {}, ["目标章节"]), renderNode("th", {}, ["重试"]), renderNode("th", {}, ["运行"]), renderNode("th", {}, ["token 合计"]), renderNode("th", {}, ["创建时间"]), renderNode("th", {}, ["操作"])
                                    ])]), renderNode("tbody", {}, [resource.data.items.map((task: AdminTask) => renderNode("tr", { "key": task.id }, [
                                        renderNode("td", {}, [renderNode("strong", {}, [task.project_title])]), renderNode("td", {}, [task.username]), renderNode("td", {}, [taskTypeLabel(task.task_type)]), renderNode("td", {}, [taskStatusLabel(task.status)]), renderNode("td", {}, [taskChapterLabel(task)]), renderNode("td", {}, [task.retry_count]), renderNode("td", {}, [task.metrics.run_count]), renderNode("td", {}, [(task.metrics.input_tokens + task.metrics.output_tokens).toLocaleString()]), renderNode("td", {}, [formatDate(task.created_at)]), renderNode("td", {}, [renderNode("button", { "type": "button", "class": "btn btn-quiet", "aria-label": `查看任务 ${task.id}`, "onClick": () => navigate(`/admin/tasks/${task.id}`) }, ["查看"])])
                                    ]))])
                            ])]), renderNode(Pagination, { "total": resource.data.total, "offset": offset.value, "onChange": setOffset })
                    ])] })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
const RunsView = defineComponent((props: {
    token: string;
    onForbidden: () => void;
}) => {
    const { filters, offset, setFilters, setOffset } = useAdminListNavigation({ userId: '', projectId: '', node: '' });
    const selectedRun = shallowRef<number | null>(null);
    const draft = shallowRef(filters.value);
    watch(filters, value => { draft.value = value; });
    const setDraft = (value: typeof draft.value) => { draft.value = value; };
    const load = (signal: AbortSignal) => adminApi.listRuns(props.token, { ...filters.value, limit: PAGE_SIZE, offset: offset.value }, signal);
    const resource = useResource<PageResult<AdminRun>>(load, props.onForbidden);
    const submit = (event: SubmitEvent) => {
        event.preventDefault();
        setFilters({
            userId: draft.value.userId.trim(),
            projectId: draft.value.projectId.trim(),
            node: draft.value.node.trim(),
        });
    };
    return () => {
        return (renderNode("section", { "class": styles.view, "aria-labelledby": "runs-heading" }, [
            selectedRun.value !== null && renderNode(RunDetailDialog, { token: props.token, runId: selectedRun.value, onForbidden: props.onForbidden, onClose: () => { selectedRun.value = null; } }), renderNode("div", { "class": styles.viewHead }, [
                renderNode("div", {}, [renderNode("h1", { "id": "runs-heading" }, ["全部运行"])]), renderNode(RefreshButton, { "onClick": resource.retry })
            ]), renderNode("form", { "class": styles.filters, "aria-label": "运行筛选", "onSubmit": submit }, [
                renderNode("label", {}, [
                    renderNode("span", {}, ["用户 ID"]), renderNode("input", { "class": "input", "value": draft.value.userId, "onInput": (event: Event) => setDraft({ ...draft.value, userId: (event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }) }, [])
                ]), renderNode("label", {}, [
                    renderNode("span", {}, ["作品 ID"]), renderNode("input", { "class": "input", "value": draft.value.projectId, "onInput": (event: Event) => setDraft({ ...draft.value, projectId: (event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }) }, [])
                ]), renderNode("label", {}, [
                    renderNode("span", {}, ["节点"]), renderNode("select", { "class": "input", "value": draft.value.node, "onChange": (event: Event) => setDraft({ ...draft.value, node: (event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }) }, [
                        renderNode("option", { "value": "" }, ["全部写作环节"]), Object.entries(NODE_LABELS).map(([node, label]) => renderNode("option", { "key": node, "value": node }, [label]))
                    ])
                ]), renderNode("button", { "class": "btn btn-primary", "type": "submit" }, ["筛选"])
            ]), renderNode(LoadState, { ...resource, "empty": resource.data?.items.length === 0, children: [resource.data && renderNode(Fragment, {}, [
                        renderNode(RunTable, { "runs": resource.data.items, "onSelect": (run: AdminRun) => (selectedRun.value = run.id) }), renderNode(Pagination, { "total": resource.data.total, "offset": offset.value, "onChange": setOffset })
                    ])] })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
const LogsView = defineComponent((props: {
    token: string;
    onForbidden: () => void;
}) => {
    const { offset, setOffset } = useAdminListNavigation({});
    const load = (signal: AbortSignal) => adminApi.listAccessLogs(props.token, { limit: PAGE_SIZE, offset: offset.value }, signal);
    const resource = useResource<PageResult<AdminAccessLog>>(load, props.onForbidden);
    return () => {
        return (renderNode("section", { "class": styles.view, "aria-labelledby": "logs-heading" }, [
            renderNode("div", { "class": styles.viewHead }, [
                renderNode("div", {}, [renderNode("h1", { "id": "logs-heading" }, ["访问日志"])]), renderNode(RefreshButton, { "onClick": resource.retry })
            ]), renderNode(LoadState, { ...resource, "empty": resource.data?.items.length === 0, children: [resource.data && renderNode(Fragment, {}, [
                        renderNode("div", { "class": styles.tableWrap }, [renderNode("table", {}, [
                                renderNode("thead", {}, [renderNode("tr", {}, [
                                        renderNode("th", {}, ["时间"]), renderNode("th", {}, ["管理员"]), renderNode("th", {}, ["动作"]), renderNode("th", {}, ["目标"])
                                    ])]), renderNode("tbody", {}, [resource.data.items.map((entry: AdminAccessLog) => renderNode("tr", { "key": entry.id }, [
                                        renderNode("td", {}, [formatDate(entry.created_at)]), renderNode(AccessLogContent, { "entry": entry })
                                    ]))])
                            ])]), renderNode(Pagination, { "total": resource.data.total, "offset": offset.value, "onChange": setOffset })
                    ])] })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
function InviteBadge({ invite }: {
    invite: AdminInvitation;
}) {
    if (invite.revoked_at)
        return renderNode("span", { "class": "badge badge-error" }, ["已撤销"]);
    if (new Date(invite.expires_at).getTime() <= Date.now())
        return renderNode("span", { "class": "badge badge-warning" }, ["已过期"]);
    if (invite.redemption_count >= invite.max_redemptions)
        return renderNode("span", { "class": "badge" }, ["已用完"]);
    return renderNode("span", { "class": "badge badge-success" }, ["可用"]);
}
const InvitesView = defineComponent((props: {
    token: string;
    onForbidden: () => void;
}) => {
    const offset = shallowRef(0);
    const setOffset = (next: typeof offset.value | ((old: typeof offset.value) => typeof offset.value)) => { offset.value = typeof next === "function" ? next(offset.value) : next; };
    const expiresDays = shallowRef("7");
    const setExpiresDays = (next: typeof expiresDays.value | ((old: typeof expiresDays.value) => typeof expiresDays.value)) => { expiresDays.value = typeof next === "function" ? next(expiresDays.value) : next; };
    const maxRedemptions = shallowRef("1");
    const setMaxRedemptions = (next: typeof maxRedemptions.value | ((old: typeof maxRedemptions.value) => typeof maxRedemptions.value)) => { maxRedemptions.value = typeof next === "function" ? next(maxRedemptions.value) : next; };
    const label = shallowRef("");
    useMemoryFormGuard(() => Boolean(label.value || code.value) || expiresDays.value !== "7" || maxRedemptions.value !== "1");
    const setLabel = (next: typeof label.value | ((old: typeof label.value) => typeof label.value)) => { label.value = typeof next === "function" ? next(label.value) : next; };
    const code = shallowRef("");
    const setCode = (next: typeof code.value | ((old: typeof code.value) => typeof code.value)) => { code.value = typeof next === "function" ? next(code.value) : next; };
    const minted = shallowRef<AdminInvitationCreated | null>(null);
    const setMinted = (next: typeof minted.value | ((old: typeof minted.value) => typeof minted.value)) => { minted.value = typeof next === "function" ? next(minted.value) : next; };
    const copied = shallowRef(false);
    const setCopied = (next: typeof copied.value | ((old: typeof copied.value) => typeof copied.value)) => { copied.value = typeof next === "function" ? next(copied.value) : next; };
    const busy = shallowRef(false);
    const setBusy = (next: typeof busy.value | ((old: typeof busy.value) => typeof busy.value)) => { busy.value = typeof next === "function" ? next(busy.value) : next; };
    const error = shallowRef<string | null>(null);
    const setError = (next: typeof error.value | ((old: typeof error.value) => typeof error.value)) => { error.value = typeof next === "function" ? next(error.value) : next; };
    const load = (signal: AbortSignal) => adminApi.listInvitations(props.token, { limit: PAGE_SIZE, offset: offset.value }, signal);
    const resource = useResource<PageResult<AdminInvitation>>(load, props.onForbidden);
    const run = async (action: () => Promise<void>, fallback: string) => {
        setError(null);
        setBusy(true);
        try {
            await action();
        }
        catch (reason) {
            if (reason instanceof ApiError && reason.status === 403)
                props.onForbidden();
            setError(formatApiError(reason, fallback));
        }
        finally {
            setBusy(false);
        }
    };
    const submit = (event: SubmitEvent) => {
        event.preventDefault();
        void run(async () => {
            const created = await adminApi.createInvitation(props.token, {
                expiresDays: Number(expiresDays.value),
                maxRedemptions: Number(maxRedemptions.value),
                label: label.value,
                code: code.value,
            });
            setMinted(created);
            setCopied(false);
            setLabel("");
            setCode("");
            setOffset(0);
            resource.retry();
        }, "创建失败，请稍后重试");
    };
    const revoke = (invitationId: string) => void run(async () => {
        await adminApi.revokeInvitation(props.token, invitationId);
        resource.retry();
    }, "撤销失败，请稍后重试");
    const copy = () => {
        if (!minted.value)
            return;
        navigator.clipboard.writeText(minted.value.code).then(() => setCopied(true)).catch(() => setError("复制失败，请手动选中上方文本"));
    };
    return () => {
        return (renderNode("section", { "class": styles.view, "aria-labelledby": "invites-heading" }, [
            renderNode("div", { "class": styles.viewHead }, [
                renderNode("div", {}, [renderNode("h1", { "id": "invites-heading" }, ["邀请码"])]), renderNode(RefreshButton, { "onClick": resource.retry })
            ]), renderNode("form", { "class": styles.filters, "aria-label": "生成邀请码", "onSubmit": submit }, [
                renderNode("label", {}, [
                    renderNode("span", {}, ["有效天数"]), renderNode("input", { "class": "input", "type": "number", "min": 1, "max": 365, "required": true, "value": expiresDays.value, "onInput": (event: Event) => setExpiresDays((event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [])
                ]), renderNode("label", {}, [
                    renderNode("span", {}, ["可用次数"]), renderNode("input", { "class": "input", "type": "number", "min": 1, "max": 1000, "required": true, "value": maxRedemptions.value, "onInput": (event: Event) => setMaxRedemptions((event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [])
                ]), renderNode("label", {}, [
                    renderNode("span", {}, ["备注"]), renderNode("input", { "class": "input", "maxLength": 64, "value": label.value, "onInput": (event: Event) => setLabel((event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [])
                ]), renderNode("label", {}, [
                    renderNode("span", {}, ["自定义码（留空随机生成）"]), renderNode("input", { "class": "input", "minLength": 4, "maxLength": 64, "value": code.value, "onInput": (event: Event) => setCode((event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [])
                ]), renderNode("button", { "class": "btn btn-primary", "type": "submit", "disabled": busy.value }, ["生成邀请码"])
            ]), minted.value && (renderNode("div", { "class": `panel ${styles.panel}` }, [
                renderNode("h3", {}, ["邀请码（只显示这一次）"]), renderNode("pre", { "class": styles.pre }, [minted.value.code]), renderNode("div", { "class": styles.actions }, [
                    renderNode("button", { "type": "button", "class": "btn btn-secondary", "onClick": copy }, [copied.value ? "已复制" : "复制"]), renderNode("button", { "type": "button", "class": "btn btn-quiet", "onClick": () => setMinted(null) }, ["关闭"])
                ])
            ])), error.value && renderNode("div", { "class": "banner banner-error", "role": "alert" }, [renderNode("span", {}, [error.value])]), renderNode(LoadState, { ...resource, "empty": resource.data?.items.length === 0, children: [resource.data && renderNode(Fragment, {}, [
                        renderNode("div", { "class": styles.tableWrap }, [renderNode("table", {}, [
                                renderNode("thead", {}, [renderNode("tr", {}, [
                                        renderNode("th", {}, ["备注"]), renderNode("th", {}, ["状态"]), renderNode("th", {}, ["有效期至"]), renderNode("th", {}, ["已用/上限"]), renderNode("th", {}, ["创建人"]), renderNode("th", {}, ["操作"])
                                    ])]), renderNode("tbody", {}, [resource.data.items.map((invite: AdminInvitation) => renderNode("tr", { "key": invite.id }, [
                                        renderNode("td", {}, [invite.label ?? "—"]), renderNode("td", {}, [renderNode(InviteBadge, { "invite": invite })]), renderNode("td", {}, [formatDate(invite.expires_at)]), renderNode("td", {}, [
                                            invite.redemption_count, " / ", invite.max_redemptions
                                        ]), renderNode("td", {}, [invite.created_by_username ?? "—"]), renderNode("td", { "class": styles.actions }, [renderNode("button", { "type": "button", "class": "btn btn-quiet", "disabled": busy.value || invite.revoked_at !== null, "onClick": () => revoke(invite.id) }, ["撤销"])])
                                    ]))])
                            ])]), renderNode(Pagination, { "total": resource.data.total, "offset": offset.value, "onChange": setOffset })
                    ])] })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
const FEEDBACK_CATEGORY_LABELS: Record<string, string> = {
    bug: '问题故障',
    suggestion: '功能建议',
    other: '其他',
};
const FeedbackView = defineComponent((props: {
    token: string;
    onForbidden: () => void;
}) => {
    const draftStatus = shallowRef("");
    const setDraftStatus = (next: typeof draftStatus.value | ((old: typeof draftStatus.value) => typeof draftStatus.value)) => { draftStatus.value = typeof next === "function" ? next(draftStatus.value) : next; };
    const status = shallowRef("");
    const setStatus = (next: typeof status.value | ((old: typeof status.value) => typeof status.value)) => { status.value = typeof next === "function" ? next(status.value) : next; };
    const offset = shallowRef(0);
    const setOffset = (next: typeof offset.value | ((old: typeof offset.value) => typeof offset.value)) => { offset.value = typeof next === "function" ? next(offset.value) : next; };
    const busy = shallowRef<string | null>(null);
    const setBusy = (next: typeof busy.value | ((old: typeof busy.value) => typeof busy.value)) => { busy.value = typeof next === "function" ? next(busy.value) : next; };
    const error = shallowRef<string | null>(null);
    const setError = (next: typeof error.value | ((old: typeof error.value) => typeof error.value)) => { error.value = typeof next === "function" ? next(error.value) : next; };
    const load = (signal: AbortSignal) => adminApi.listFeedback(props.token, { status: status.value, limit: PAGE_SIZE, offset: offset.value }, signal);
    const resource = useResource<PageResult<Feedback>>(load, props.onForbidden);
    const submit = (event: SubmitEvent) => {
        event.preventDefault();
        setOffset(0);
        setStatus(draftStatus.value);
    };
    const setFeedbackStatus = (item: Feedback, next: string) => {
        setError(null);
        setBusy(item.id);
        adminApi.setFeedbackStatus(props.token, item.id, next).then(() => resource.retry()).catch((reason: unknown) => { if (reason instanceof ApiError && reason.status === 403)
            props.onForbidden(); setError(formatApiError(reason, "状态更新失败，请稍后重试")); }).finally(() => setBusy(null));
    };
    return () => {
        return (renderNode("section", { "class": styles.view, "aria-labelledby": "feedback-heading" }, [
            renderNode("div", { "class": styles.viewHead }, [
                renderNode("div", {}, [renderNode("h1", { "id": "feedback-heading" }, ["问题反馈"])]), renderNode(RefreshButton, { "onClick": resource.retry })
            ]), renderNode("form", { "class": styles.filters, "aria-label": "反馈筛选", "onSubmit": submit }, [
                renderNode("label", {}, [
                    renderNode("span", {}, ["状态"]), renderNode("select", { "class": "input", "value": draftStatus.value, "onChange": (event: Event) => setDraftStatus((event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [
                        renderNode("option", { "value": "" }, ["全部"]), renderNode("option", { "value": "open" }, ["待处理"]), renderNode("option", { "value": "resolved" }, ["已解决"])
                    ])
                ]), renderNode("button", { "class": "btn btn-primary", "type": "submit" }, ["筛选"])
            ]), error.value && renderNode("div", { "class": "banner banner-error", "role": "alert" }, [renderNode("span", {}, [error.value])]), renderNode(LoadState, { ...resource, "empty": resource.data?.items.length === 0, children: [resource.data && renderNode(Fragment, {}, [
                        renderNode("div", { "class": styles.tableWrap }, [renderNode("table", {}, [
                                renderNode("thead", {}, [renderNode("tr", {}, [
                                        renderNode("th", {}, ["提交时间"]), renderNode("th", {}, ["用户"]), renderNode("th", {}, ["类型"]), renderNode("th", {}, ["描述"]), renderNode("th", {}, ["附件"]), renderNode("th", {}, ["状态"]), renderNode("th", {}, ["操作"])
                                    ])]), renderNode("tbody", {}, [resource.data.items.map((item: Feedback) => renderNode("tr", { "key": item.id }, [
                                        renderNode("td", {}, [formatDate(item.created_at)]), renderNode("td", {}, [item.username || "—"]), renderNode("td", {}, [FEEDBACK_CATEGORY_LABELS[item.category] ?? "其他"]), renderNode("td", { "class": styles.text }, [
                                            item.description, item.contact && renderNode("small", {}, [
                                                "联系方式：", item.contact
                                            ]), item.page_url && renderNode("small", {}, [
                                                "页面：", item.page_url
                                            ])
                                        ]), renderNode("td", {}, [item.attachments.length === 0 ? renderNode("span", { "class": styles.muted }, ["—"]) : (renderNode("div", { "class": styles.feedbackChips }, [item.attachments.map((attachment: import("../../../../src/types").FeedbackAttachment) => (renderNode(AttachmentChip, { "key": attachment.index, "feedbackId": item.id, "attachment": attachment })))]))]), renderNode("td", {}, [item.status === "resolved" ? renderNode("span", { "class": "badge badge-success" }, ["已解决"]) : renderNode("span", { "class": "badge badge-warning" }, ["待处理"])]), renderNode("td", { "class": styles.actions }, [item.status === "resolved" ? renderNode("button", { "type": "button", "class": "btn btn-quiet", "disabled": busy.value === item.id, "onClick": () => setFeedbackStatus(item, "open") }, ["撤回"]) : renderNode("button", { "type": "button", "class": "btn btn-secondary", "disabled": busy.value === item.id, "onClick": () => setFeedbackStatus(item, "resolved") }, ["标记已解决"])])
                                    ]))])
                            ])]), renderNode(Pagination, { "total": resource.data.total, "offset": offset.value, "onChange": setOffset })
                    ])] })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
export const AdminConsole = defineComponent((_props: Record<string, never>) => {
    const adminContext = useAdminContext();
    const { onForbidden } = adminContext;
    const route = useRoute();
    const requested = computed(() => route.query.tab as string | undefined);
    const tab = computed(() => (TABS.some(([id]) => id === requested.value) ? requested.value as Tab : "overview"));
    return () => {
        return (renderNode(Fragment, {}, [
            tab.value === "overview" && renderNode(OverviewView, { "token": adminContext.token, "onForbidden": onForbidden }), tab.value === "analytics" && renderNode(Analytics, { "token": adminContext.token, "onForbidden": onForbidden }), tab.value === "users" && renderNode(UsersView, { "token": adminContext.token, "onForbidden": onForbidden }), tab.value === "projects" && renderNode(ProjectsView, { "token": adminContext.token, "onForbidden": onForbidden }), tab.value === "tasks" && renderNode(TasksView, { "token": adminContext.token, "onForbidden": onForbidden }), tab.value === "runs" && renderNode(RunsView, { "token": adminContext.token, "onForbidden": onForbidden }), tab.value === "logs" && renderNode(LogsView, { "token": adminContext.token, "onForbidden": onForbidden }), tab.value === "invites" && renderNode(InvitesView, { "token": adminContext.token, "onForbidden": onForbidden }), tab.value === "feedback" && renderNode(FeedbackView, { "token": adminContext.token, "onForbidden": onForbidden })
        ]));
    };
}, {
    inheritAttrs: false,
    props: {}
});
InviteBadge.props = ["invite"];
InviteBadge.inheritAttrs = false;
