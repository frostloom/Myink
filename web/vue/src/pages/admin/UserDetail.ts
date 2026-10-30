import { computed, defineComponent, h as renderNode, ref } from 'vue';
import { useRoute } from 'vue-router';
import { adminApi } from "../../../../src/lib/adminApi";
import { ApiError } from "../../../../src/lib/api";
import { formatApiError } from "../../../../src/lib/apiError";
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
    const busy = ref(false);
    const error = ref('');
    async function changeMembership() {
        if (!value.value || busy.value) return;
        busy.value = true;
        error.value = '';
        try {
            const saved = await adminApi.updateMembership(adminContext.token, userId,
                value.value.tier === 'vip' ? 'normal' : 'vip');
            user.data = { ...value.value, tier: saved.tier };
        } catch (reason) {
            if (reason instanceof ApiError && reason.status === 403) onForbidden();
            error.value = formatApiError(reason, '会员等级保存失败，请重试');
        } finally {
            busy.value = false;
        }
    }
    return () => {
        return (renderNode(DetailPage, { "heading": value.value ? `${value.value.username} · 账号详情` : "账号详情", "backTab": "users", children: [renderNode(LoadState, { ...user, "empty": !value.value, children: [value.value && renderNode("div", { "class": `panel ${styles.panel}` }, [
                            renderNode("h3", {}, [
                                "总花费 ", formatCost(value.value.metrics.cost_est)
                            ]), renderNode("p", {}, [
                                renderNode("span", { class: `${styles.tierBadge} ${value.value.tier === "vip" ? styles.vipTierBadge : ""}` }, tierLabel(value.value.tier)), " · ", roleLabel(value.value.role), " · 作品 ", value.value.project_count, " 本"
                            ]), renderNode('button', { type: 'button', class: 'btn btn-secondary',
                                disabled: busy.value, onClick: () => void changeMembership() },
                                [busy.value ? '保存中…' : value.value.tier === 'vip' ? '取消 VIP' : '开通 VIP']),
                            error.value && renderNode('p', { role: 'alert' }, error.value),
                            renderNode(Metrics, { "value": value.value.metrics })
                        ])] })] }));
    };
}, {
    inheritAttrs: false,
    props: {}
});
