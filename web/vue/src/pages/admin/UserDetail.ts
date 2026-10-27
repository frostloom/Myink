import { computed, defineComponent, h as renderNode } from 'vue';
import { useRoute } from 'vue-router';
import { adminApi } from "../../../../src/lib/adminApi";
import { ApiError } from "../../../../src/lib/api";
import { roleLabel, tierLabel } from "../../../../src/lib/labels";
import styles from "../../../../src/pages/AdminPage.module.css";
import { useAdminContext } from './context';
import { DetailPage, formatCost, LoadState, Metrics, useResource } from "./shared";
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
    const user = useResource(loadUser, onForbidden);
    const value = computed(() => user.data);
    return () => {
        return (renderNode(DetailPage, { "heading": value.value ? `${value.value.username} · 账号详情` : "账号详情", "backTab": "users", children: [renderNode(LoadState, { ...user, "empty": !value.value, children: [value.value && renderNode("div", { "class": `panel ${styles.panel}` }, [
                            renderNode("h3", {}, [
                                "总花费 ", formatCost(value.value.metrics.cost_est)
                            ]), renderNode("p", {}, [
                                tierLabel(value.value.tier), " · ", roleLabel(value.value.role), " · 作品 ", value.value.project_count, " 本"
                            ]), renderNode(Metrics, { "value": value.value.metrics })
                        ])] })] }));
    };
}, {
    inheritAttrs: false,
    props: {}
});
