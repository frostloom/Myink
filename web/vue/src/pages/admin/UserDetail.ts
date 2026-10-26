import { computed, defineComponent, h as renderNode, shallowRef } from 'vue';
import { useRoute } from 'vue-router';
import { adminApi } from "../../../../src/lib/adminApi";
import { ApiError } from "../../../../src/lib/api";
import { roleLabel, tierLabel } from "../../../../src/lib/labels";
import styles from "../../../../src/pages/AdminPage.module.css";
import { useAdminContext } from './context';
import { RunDetailView, RunTable } from "./RunDetail";
import { DetailPage, formatCost, LoadState, Metrics, PAGE_SIZE, useResource } from "./shared";
export const UserDetailPage = defineComponent((_props: Record<string, never>) => {
    const adminContext = useAdminContext();
    const { onForbidden } = adminContext;
    const { userId = "" } = (useRoute().params as Record<string, string>);
    const loadUser = async (signal: AbortSignal) => {
        try {
            return await adminApi.getUser(adminContext.token, userId, signal);
        }
        catch (reason) {
            if (reason instanceof ApiError && reason.status === 404) {
                throw new ApiError(404, "用户不存在", reason.body);
            }
            throw reason;
        }
    };
    const loadRuns = (signal: AbortSignal) => adminApi.listRuns(adminContext.token, { userId, limit: PAGE_SIZE, offset: 0 }, signal);
    const user = useResource(loadUser, onForbidden);
    const runs = useResource(loadRuns, onForbidden);
    const value = computed(() => (user.data));
    const selected = shallowRef<number | null>(null);
    const setSelected = (next: typeof selected.value | ((old: typeof selected.value) => typeof selected.value)) => { selected.value = typeof next === "function" ? next(selected.value) : next; };
    return () => {
        return (renderNode(DetailPage, { "heading": value.value ? `${value.value.username} · 账号详情` : "账号详情", "backTab": "users", children: [renderNode(LoadState, { ...user, "empty": !value.value, children: [value.value && renderNode("div", { "class": `panel ${styles.panel}` }, [
                            renderNode("h3", {}, [
                                "总花费 ", formatCost(value.value.metrics.cost_est)
                            ]), renderNode("p", {}, [
                                tierLabel(value.value.tier), " · ", roleLabel(value.value.role), " · 作品 ", value.value.project_count, " 本"
                            ]), renderNode(Metrics, { "value": value.value.metrics })
                        ])] }), renderNode("section", { "class": `panel ${styles.panel}` }, [
                    renderNode("h3", {}, ["调用明细"]), renderNode(LoadState, { ...runs, "empty": runs.data?.items.length === 0, children: [runs.data && renderNode(RunTable, { "runs": runs.data.items, "onSelect": (run: import("../../../../src/lib/adminApi").AdminRun) => setSelected(run.id) })] })
                ]), selected.value !== null && renderNode(RunDetailView, { "token": adminContext.token, "runId": selected.value, "onForbidden": onForbidden })] }));
    };
}, {
    inheritAttrs: false,
    props: {}
});
