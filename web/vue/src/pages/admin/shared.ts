import { adminReturnTo } from './navigation';
import { Fragment, h, reactive, shallowRef, watchEffect, type VNodeChild } from 'vue';
import { RouterLink as Link, useRoute, useRouter } from 'vue-router';
import type { AdminMetrics, CapturedData } from "../../../../src/lib/adminApi";
import { ApiError } from "../../../../src/lib/api";
import { formatApiError } from "../../../../src/lib/apiError";
import { formatDuration as formatDurationMs } from "../../../../src/lib/duration";
import { asRecord, fieldLabel, isInternalKey } from "../../../../src/lib/snapshotView";
import styles from "../../../../src/pages/AdminPage.module.css";
import { ReadableContent } from "./ReadableContent";
export const PAGE_SIZE = 25;
/** /admin 外壳交给子路由的东西：闸门验过的 token 与「权限已变」的回调。 */
export type AdminOutletContext = {
    token: string;
    onForbidden: () => void;
};
export function useResource<T>(loader: (signal: AbortSignal) => Promise<T>, onForbidden: () => void) {
    const data = shallowRef<T | null>(null);
    const loading = shallowRef(true);
    const error = shallowRef<string | null>(null);
    const revision = shallowRef(0);
    let sequence = 0;
    watchEffect((onCleanup) => {
        void revision.value;
        const controller = new AbortController();
        const current = ++sequence;
        loading.value = true;
        error.value = null;
        data.value = null;
        onCleanup(() => controller.abort());
        void loader(controller.signal).then(value => {
            if (!controller.signal.aborted && current === sequence)
                data.value = value;
        }).catch((reason: unknown) => {
            if (controller.signal.aborted || current !== sequence)
                return;
            if (reason instanceof ApiError && reason.status === 403) {
                onForbidden();
                return;
            }
            if (reason instanceof ApiError && reason.code === 'request_aborted')
                return;
            error.value = formatApiError(reason, '加载失败，请稍后重试');
        }).finally(() => {
            if (!controller.signal.aborted && current === sequence)
                loading.value = false;
        });
    });
    return reactive({ data, loading, error, retry: () => { revision.value++; } });
}
export function LoadState({ loading, error, empty, retry, children, }: {
    loading: boolean;
    error: string | null;
    empty: boolean;
    retry: () => void;
    children: VNodeChild;
}) {
    if (loading)
        return h("div", { "class": "empty", "role": "status" }, ["正在加载…"]);
    if (error) {
        return (h("div", { "class": `banner banner-error ${styles.loadError}`, "role": "alert" }, [h("span", {}, [error]), h("button", { "type": "button", "class": "btn btn-secondary", "onClick": retry }, ["重试"])]));
    }
    if (empty)
        return h("div", { "class": "empty" }, ["暂无数据"]);
    return children;
}
export function Pagination({ total, offset, onChange }: {
    total: number;
    offset: number;
    onChange: (offset: number) => void;
}) {
    return (h("div", { "class": styles.pagination, "aria-label": "分页" }, [h("button", { "type": "button", "class": "btn btn-quiet", "disabled": offset === 0, "onClick": () => onChange(Math.max(0, offset - PAGE_SIZE)) }, ["上一页"]), h("span", {}, ["第 ", Math.floor(offset / PAGE_SIZE) + 1, " 页 · 共 ", total, " 条"]), h("button", { "type": "button", "class": "btn btn-quiet", "disabled": offset + PAGE_SIZE >= total, "onClick": () => onChange(offset + PAGE_SIZE) }, ["下一页"])]));
}
export function RefreshButton({ onClick }: {
    onClick: () => void;
}) {
    return h("button", { "type": "button", "class": "btn btn-secondary", "onClick": onClick }, ["刷新当前视图"]);
}
/** 详情页外壳：标题 + 返回原标签页的链接。返回必须带回 tab，否则回退永远落在概览。 */
export function DetailPage({ heading, backTab, backTo, children }: {
    heading: string;
    backTab: string;
    backTo?: string;
    children: VNodeChild;
}) {
    const back = useRouter().resolve(adminReturnTo(useRoute().query.returnTo ?? backTo, backTab));
    return (h("section", { "class": styles.view }, [h("div", { "class": `${styles.viewHead} ${styles.detailPageHead}` }, [h("div", {}, [h("h1", {}, [heading])]), h(Link, { "to": { path: back.path, query: back.query, hash: back.hash, state: { adminRestoreScroll: true } }, "class": "btn btn-secondary" }, { default: () => ["返回"] })]), children]));
}
/** 值 → 可读文本：标量直出，布尔转「是/否」，对象与对象数组降一级展开。 */
export function ValueText({ value }: {
    value: unknown;
}) {
    if (value === null || value === undefined || value === '')
        return h("span", { "class": styles.muted }, ["—"]);
    if (typeof value === 'boolean')
        return h(Fragment, {}, [value ? "是" : "否"]);
    if (Array.isArray(value)) {
        if (value.length === 0)
            return h("span", { "class": styles.muted }, ["—"]);
        if (value.every((item) => item === null || typeof item !== 'object')) {
            return h(Fragment, {}, [value.map(item => String(item)).join("、")]);
        }
        return h("ul", { "class": styles.plainList }, [value.map((item, index: number) => h("li", { "key": index }, [h(ValueText, { "value": item }, [])]))]);
    }
    if (typeof value === 'object')
        return h(RecordFields, { "value": value }, []);
    return h(Fragment, {}, [String(value)]);
}
/** 记录 → 「字段名 → 值」列表。空值、空串与内部标记字段不占位。 */
export function RecordFields({ value, skip = [] }: {
    value: unknown;
    skip?: string[];
}) {
    const record = asRecord(value);
    if (!record)
        return h(ValueText, { "value": value }, []);
    const rows = Object.entries(record).filter(([key, item]) => !isInternalKey(key)
        && !skip.includes(key) && item !== null && item !== undefined && item !== '');
    if (rows.length === 0)
        return h("p", { "class": styles.muted }, ["无记录"]);
    return (h("dl", { "class": styles.fields }, [rows.map(([key, item]) => h("div", { "key": key }, [h("dt", {}, [fieldLabel(key)]), h("dd", {}, [h(ValueText, { "value": item }, [])])]))]));
}
/** 一行一个「字段名 → 值」；表格单元格里的多字段摘要用它，避免斜杠拼列。 */
export function FieldRows({ rows }: {
    rows: Array<[
        string,
        VNodeChild
    ]>;
}) {
    return (h("dl", { "class": styles.fields }, [rows.map(([label, value]) => h("div", { "key": label }, [h("dt", {}, [label]), h("dd", {}, [value])]))]));
}
/** 模型用量五条读数的唯一口径：概览页把它们并进实体计数那一条带，用户详情单独成带。 */
export function metricEntries(value: AdminMetrics): Array<[
    string,
    string
]> {
    return [
        ['运行数', value.run_count.toLocaleString()],
        ['输入 token', value.input_tokens.toLocaleString()],
        ['输出 token', value.output_tokens.toLocaleString()],
        ['预估成本', formatCost(value.cost_est)],
        ['节点耗时', formatDuration(value.duration_ms)],
    ];
}
export function Metrics({ value }: {
    value: AdminMetrics;
}) {
    return (h("dl", { "class": styles.metrics }, [metricEntries(value).map(([label, text]) => h("div", { "key": label }, [h("dt", {}, [label]), h("dd", {}, [text])]))]));
}
/** 成本只有估算值，币种不可知，所以只出数字，不拼货币符号。 */
export function formatCost(value: number): string {
    return value.toFixed(4);
}
/** 管理台口径：0 表示没记录到耗时，出破折号而不是「0 ms」。 */
export function formatDuration(value: number): string {
    return value === 0 ? '—' : formatDurationMs(value);
}
export function formatDate(value: string): string {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN');
}
/** 普通详情按创作用途整理；技术诊断显式请求原始字段。 */
export function CapturedView({ value, label, skip, raw = false }: {
    value: CapturedData;
    label: string;
    skip?: string[];
    raw?: boolean;
}) {
    const flagged = value.truncated || value.redacted;
    return (h("section", { "class": styles.capture, "aria-label": label }, [h("h4", {}, [label]), flagged && h("div", { "class": styles.flags }, [value.truncated && h("span", { "class": "badge badge-warning" }, ["内容已截断"]), value.redacted && h("span", { "class": "badge badge-warning" }, ["敏感信息已脱敏"])]), !raw ? h(ReadableContent, { "value": skip && asRecord(value.data) ? Object.fromEntries(Object.entries(asRecord(value.data)!).filter(([key]) => !skip.includes(key))) : value.data }, []) : typeof value.data === "string" ? (value.data === "" ? h("p", { "class": styles.muted }, ["无记录"]) : h("p", { "class": styles.text }, [value.data])) : h(RecordFields, { "value": value.data, "skip": skip }, [])]));
}
LoadState.props = ["loading", "error", "empty", "retry", "children"];
LoadState.inheritAttrs = false;
Pagination.props = ["total", "offset", "onChange"];
Pagination.inheritAttrs = false;
RefreshButton.props = ["onClick"];
RefreshButton.inheritAttrs = false;
DetailPage.props = ["heading", "backTab", "backTo", "children"];
DetailPage.inheritAttrs = false;
ValueText.props = ["value"];
ValueText.inheritAttrs = false;
RecordFields.props = ["value", "skip"];
RecordFields.inheritAttrs = false;
FieldRows.props = ["rows"];
FieldRows.inheritAttrs = false;
Metrics.props = ["value"];
Metrics.inheritAttrs = false;
CapturedView.props = ["value", "label", "skip", "raw"];
CapturedView.inheritAttrs = false;
