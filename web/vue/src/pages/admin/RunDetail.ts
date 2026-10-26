/* eslint-disable vue/one-component-per-file -- Native Vue render helpers stay with their owning page. */
import type { PropType } from 'vue';
import { computed, defineComponent, h as renderNode } from 'vue';
import { useRoute } from 'vue-router';
import { adminApi, type AdminRun, type AdminRunDetail } from "../../../../src/lib/adminApi";
import { nodeLabel } from "../../../../src/lib/labels";
import styles from "../../../../src/pages/AdminPage.module.css";
import layout from "../../../../src/pages/admin/ExecutionDetail.module.css";
import { Disclosure, ExecutionContent, ExecutionError } from "./ExecutionContent";
import { useAdminContext } from './context';
import { CapturedView, DetailPage, formatCost, formatDate, formatDuration, LoadState, RefreshButton, useResource } from "./shared";
export function RunTable({ runs, onSelect }: {
    runs: AdminRun[];
    onSelect: (run: AdminRun) => void;
}) {
    return (renderNode("div", { "class": styles.tableWrap }, [renderNode("table", {}, [
            renderNode("thead", {}, [renderNode("tr", {}, [
                    renderNode("th", {}, ["运行"]), renderNode("th", {}, ["节点 "]), renderNode("th", {}, ["作品"]), renderNode("th", {}, ["模型"]), renderNode("th", {}, ["输入 token"]), renderNode("th", {}, ["输出 token"]), renderNode("th", {}, ["预估成本"]), renderNode("th", {}, ["耗时"]), renderNode("th", {}, ["降级"]), renderNode("th", {}, ["重试"]), renderNode("th", {}, ["时间"]), renderNode("th", {}, ["操作"])
                ])]), renderNode("tbody", {}, [runs.map((run: AdminRun) => renderNode("tr", { "key": run.id }, [
                    renderNode("td", {}, [
                        "#", run.id
                    ]), renderNode("td", {}, [renderNode("strong", {}, [nodeLabel(run.node)])]), renderNode("td", {}, [run.project_title ?? "—"]), renderNode("td", {}, [run.model_id ?? "—"]), renderNode("td", {}, [run.input_tokens.toLocaleString()]), renderNode("td", {}, [run.output_tokens.toLocaleString()]), renderNode("td", {}, [formatCost(run.cost_est)]), renderNode("td", {}, [formatDuration(run.duration_ms)]), renderNode("td", {}, [run.degraded ? "是" : "否"]), renderNode("td", {}, [run.retry_count]), renderNode("td", {}, [formatDate(run.created_at)]), renderNode("td", {}, [renderNode("button", { "type": "button", "class": "btn btn-quiet", "aria-label": `查看节点 ${run.node} #${run.id}`, "onClick": () => onSelect(run) }, ["详情"])])
                ]))])
        ])]));
}
export const RunDetailView = defineComponent((props: {
    token: string;
    runId: number;
    onForbidden: () => void;
}) => {
    const load = (signal: AbortSignal) => adminApi.getRun(props.token, props.runId, signal);
    const resource = useResource<AdminRunDetail>(load, props.onForbidden);
    const value = computed(() => (resource.data));
    return () => {
        return (renderNode(LoadState, { ...resource, "empty": !value.value, children: [value.value && renderNode("article", { "class": `panel ${styles.detail}` }, [
                    renderNode("div", { "class": styles.detailHead }, [
                        renderNode("div", {}, [
                            renderNode("h3", {}, [
                                "节点 ", nodeLabel(value.value.node), " #", value.value.id
                            ]), renderNode("p", {}, [
                                value.value.model_id ?? "未记录模型", " · ", formatDuration(value.value.duration_ms)
                            ])
                        ]), renderNode(RefreshButton, { "onClick": resource.retry })
                    ]), value.value.detail_missing && renderNode("p", { "class": "banner banner-warning" }, ["旧记录未保存详情，无法重建。"]), value.value.prompt_missing && renderNode("p", { "class": "banner banner-warning" }, ["旧记录未保存提示词，无法重建。"]), renderNode("dl", { "class": layout.readings }, [
                        renderNode("div", {}, [
                            renderNode("dt", {}, ["输入 Token"]), renderNode("dd", {}, [value.value.input_tokens.toLocaleString()])
                        ]), renderNode("div", {}, [
                            renderNode("dt", {}, ["输出 Token"]), renderNode("dd", {}, [value.value.output_tokens.toLocaleString()])
                        ]), renderNode("div", {}, [
                            renderNode("dt", {}, ["预估成本"]), renderNode("dd", {}, [formatCost(value.value.cost_est)])
                        ]), renderNode("div", {}, [
                            renderNode("dt", {}, ["调用重试"]), renderNode("dd", {}, [value.value.retry_count])
                        ])
                    ]), Boolean(value.value.error.data) && renderNode(ExecutionError, { "value": value.value.error, "label": "错误详情" }), (value.value.detail.truncated || value.value.detail.redacted) && renderNode("p", { "class": layout.muted }, [
                        value.value.detail.truncated && "内容已截断。", value.value.detail.redacted && "敏感信息已脱敏。"
                    ]), renderNode(ExecutionContent, { "value": value.value.detail.data }), renderNode(Disclosure, { "title": "技术诊断", children: [renderNode(CapturedView, { "value": value.value.detail, "raw": true, "label": "原始运行记录" }), Boolean(value.value.error.data) && renderNode(CapturedView, { "value": value.value.error, "raw": true, "label": "原始错误记录" })] })
                ])] }));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        runId: { type: Number as PropType<number>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
export const RunDetailPage = defineComponent((_props: Record<string, never>) => { const adminContext = useAdminContext(); const { onForbidden } = adminContext; const { runId = "" } = (useRoute().params as Record<string, string>); return () => { return (renderNode(DetailPage, { "heading": "运行详情", "backTab": "runs", children: [renderNode(RunDetailView, { "token": adminContext.token, "runId": Number(runId), "onForbidden": onForbidden })] })); }; }, {
    inheritAttrs: false,
    props: {}
});
RunTable.props = ["runs", "onSelect"];
RunTable.inheritAttrs = false;
