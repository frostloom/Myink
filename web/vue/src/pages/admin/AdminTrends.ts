/* eslint-disable vue/one-component-per-file -- Native Vue render helpers stay with their owning page. */
import * as echarts from "echarts";
import type { PropType } from 'vue';
import { Fragment, computed, defineComponent, h as renderNode, shallowRef, watch } from 'vue';
import { adminApi, type AdminTrendPoint } from "../../../../src/lib/adminApi";
import styles from "../../../../src/pages/admin/AdminTrends.module.css";
import { LoadState, useResource } from "./shared";
const counts = [['user_count', '新增用户'], ['project_count', '新增作品'], ['chapter_count', '新增章节'], ['task_count', '新增任务'], ['run_count', '模型调用']] as const;
const tokens = [['input_tokens', '输入 Token'], ['output_tokens', '输出 Token']] as const;
const cost = [['cost_est', '估算费用（人民币）']] as const;
function recent(days: number) {
    const end = new Date();
    const start = new Date(end);
    start.setUTCDate(start.getUTCDate() - days + 1);
    return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}
const TrendChart = defineComponent((props: {
    points: AdminTrendPoint[];
    series: readonly (readonly [
        keyof Omit<AdminTrendPoint, "day">,
        string
    ])[];
    title: string;
}) => {
    const ref = shallowRef<HTMLDivElement | null>(null);
    watch([() => ref.value, () => props.points, () => props.series], (_next, _old, onCleanup) => {
        const cleanup = (() => {
            if (!ref.value)
                return;
            const chart = echarts.init(ref.value, undefined, { renderer: "svg" });
            chart.setOption({
                color: ["#3d8073", "#688cc4", "#b89754", "#a078b1", "#bd7562"],
                tooltip: { trigger: "axis", confine: true },
                legend: { bottom: 0, type: "scroll" },
                grid: { top: 20, left: 20, right: 20, bottom: 65, containLabel: true },
                xAxis: { type: "category", data: props.points.map((p: AdminTrendPoint) => p.day), boundaryGap: false },
                yAxis: { type: "value", min: 0 },
                series: props.series.map(([key, name]) => ({ name, type: "line", showSymbol: props.points.length < 15, data: props.points.map((p: AdminTrendPoint) => p[key]) })),
            });
            const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => chart.resize());
            observer?.observe(ref.value);
            const resize = () => chart.resize();
            window.addEventListener("resize", resize);
            return () => { observer?.disconnect(); window.removeEventListener("resize", resize); chart.dispose(); };
        })();
        if (typeof cleanup === "function")
            onCleanup(cleanup);
    }, { immediate: true, flush: "post" });
    return () => {
        return renderNode("section", { "class": styles.chartCard }, [
            renderNode("h3", {}, [props.title]), renderNode("div", { "class": styles.chart, ref: ref, "role": "img", "aria-label": props.title }, [])
        ]);
    };
}, {
    inheritAttrs: false,
    props: {
        points: { type: Array as PropType<AdminTrendPoint[]>, required: true },
        series: { type: Array as PropType<readonly (readonly [
                keyof Omit<AdminTrendPoint, "day">,
                string
            ])[]>, required: true },
        title: { type: String as PropType<string>, required: true }
    }
});
export const AdminTrends = defineComponent((props: {
    token: string;
    onForbidden: () => void;
}) => {
    const range = shallowRef((() => recent(30))());
    const setRange = (next: typeof range.value | ((old: typeof range.value) => typeof range.value)) => { range.value = typeof next === "function" ? next(range.value) : next; };
    const draft = shallowRef(range.value);
    const setDraft = (next: typeof draft.value | ((old: typeof draft.value) => typeof draft.value)) => { draft.value = typeof next === "function" ? next(draft.value) : next; };
    const validation = shallowRef("");
    const setValidation = (next: typeof validation.value | ((old: typeof validation.value) => typeof validation.value)) => { validation.value = typeof next === "function" ? next(validation.value) : next; };
    const load = (signal: AbortSignal) => adminApi.getTrends(props.token, range.value.start, range.value.end, signal);
    const resource = useResource(load, props.onForbidden);
    const points = computed(() => (resource.data?.items ?? []));
    const allSeries = computed(() => ([...counts, ...tokens, ...cost]));
    const empty = computed(() => (points.value.every((p: AdminTrendPoint) => allSeries.value.every(([key]) => p[key] === 0))));
    const choose = (days: number) => { const next = recent(days); setDraft(next); setRange(next); setValidation(""); };
    const submit = (event: SubmitEvent) => {
        event.preventDefault();
        const days = (Date.parse(draft.value.end) - Date.parse(draft.value.start)) / 86400000 + 1;
        if (!Number.isFinite(days) || days < 1 || days > 90) {
            setValidation("请选择连续 1 至 90 天");
            return;
        }
        setValidation("");
        setRange({ ...draft.value });
    };
    return () => {
        return renderNode("section", { "class": styles.trends, "aria-labelledby": "trends-heading" }, [
            renderNode("h2", { "id": "trends-heading" }, ["每日趋势"]), renderNode("p", {}, ["按 UTC 自然日统计新增记录，起止日期均包含在内；费用为估算人民币金额。"]), renderNode("form", { "class": styles.filters, "onSubmit": submit }, [
                renderNode("button", { "type": "button", "class": "btn btn-secondary", "onClick": () => choose(7) }, ["近7天"]), renderNode("button", { "type": "button", "class": "btn btn-secondary", "onClick": () => choose(30) }, ["近30天"]), renderNode("label", {}, [
                    "开始日期", renderNode("input", { "aria-label": "开始日期", "type": "date", "required": true, "value": draft.value.start, "onInput": (e: Event) => setDraft({ ...draft.value, start: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }) }, [])
                ]), renderNode("label", {}, [
                    "结束日期", renderNode("input", { "aria-label": "结束日期", "type": "date", "required": true, "value": draft.value.end, "onInput": (e: Event) => setDraft({ ...draft.value, end: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }) }, [])
                ]), renderNode("button", { "class": "btn btn-secondary", "type": "submit" }, ["查询趋势"]), renderNode("button", { "class": "btn btn-quiet", "type": "button", "onClick": resource.retry }, ["刷新趋势"])
            ]), validation.value && renderNode("p", { "role": "alert" }, [validation.value]), renderNode(LoadState, { ...resource, "empty": false, children: [empty.value ? renderNode("p", { "class": "empty" }, ["所选日期暂无记录"]) : renderNode(Fragment, {}, [
                        renderNode("dl", { "class": styles.summary }, [allSeries.value.map(([key, label]) => renderNode("div", { "key": key }, [
                                renderNode("dt", {}, [label]), renderNode("dd", {}, [points.value.reduce((sum: number, p: AdminTrendPoint) => sum + p[key], 0).toLocaleString("zh-CN", { maximumFractionDigits: key === "cost_est" ? 4 : 0 })])
                            ]))]), renderNode(TrendChart, { "points": points.value, "series": counts, "title": "新增记录与模型调用" }), renderNode(TrendChart, { "points": points.value, "series": tokens, "title": "每日输入与输出 Token" }), renderNode(TrendChart, { "points": points.value, "series": cost, "title": "每日估算费用" })
                    ])] })
        ]);
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
