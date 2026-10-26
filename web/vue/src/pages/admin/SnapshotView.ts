import type { PropType } from 'vue';
import { computed, defineComponent, Fragment, h as renderNode, shallowRef } from 'vue';
import { adminApi, type AdminSnapshot } from "../../../../src/lib/adminApi";
import { conflictTypeLabel, findingSourceLabel, nodeLabel, scopeLabel, severityLabel, } from "../../../../src/lib/labels";
import { appliedSpans, availableSubViews, findings, HARD_RULE_SECTION, hardRuleFacts, hardRuleSection, promptSections, recallGroups, recallStats, severityClass, snapshotPayload, styleSection, SUB_VIEW_LABELS, type RecallGroup, type SnapshotSubView, } from "../../../../src/lib/snapshotView";
import styles from "../../../../src/pages/admin/SnapshotView.module.css";
import { CreationInput, Disclosure } from "./ExecutionContent";
import { ReadableContent } from "./ReadableContent";
import { CapturedView, formatCost, formatDate, formatDuration, LoadState, RefreshButton, useResource } from "./shared";
function ItemList({ group }: {
    group: RecallGroup;
}) {
    if (group.items.length === 0)
        return renderNode("p", { "class": styles.muted }, ["本次没有使用这类前情资料"]);
    return (renderNode("ul", { "class": styles.items }, [group.items.map((item: Record<string, unknown>, index: number) => (renderNode("li", { "key": `${group.key}-${index}` }, [
            renderNode(ReadableContent, { "value": Object.fromEntries(Object.entries(item).filter(([key]) => !key.endsWith("_id") && key !== "id" && key !== "is_hard")) }), item.is_hard === true && renderNode("span", { "class": "badge badge-warning" }, ["必须遵守的设定"])
        ])))]));
}
function PromptSections({ payload }: {
    payload: ReturnType<typeof snapshotPayload>;
}) {
    const sections = promptSections(payload);
    return (renderNode(Fragment, {}, [
        renderNode("p", { "class": styles.summary }, [
            "本次提供了 ", sections.length, " 部分创作依据", payload.prompt?.truncated === true && renderNode("span", { "class": "badge badge-warning" }, ["整体已截断"])
        ]), renderNode("ul", { "class": styles.sections }, [sections.map((section: import("../../../../src/lib/adminApi").SnapshotSection, index: number) => (renderNode("li", { "key": `${section.name ?? "preamble"}-${index}` }, [
                renderNode("div", { "class": styles.itemHead }, [
                    renderNode("strong", {}, [section.name ?? "模板前言"]), renderNode("span", { "class": "badge" }, [({ system: "角色职责与创作要求", user: "本次创作任务", assistant: "前轮回复", tool: "查阅资料" }[section.role ?? ""]) ?? "补充依据"]), section.policy === "hash" && renderNode("span", { "class": "badge" }, ["未保存正文"]), section.truncated === true && renderNode("span", { "class": "badge badge-warning" }, ["已截断"]), section.omitted === "budget" && renderNode("span", { "class": "badge badge-warning" }, ["超过留存上限，未保存正文"])
                ]), typeof section.text === "string" && section.text !== "" ? renderNode(CreationInput, { "value": section.text, "system": section.role === "system" }) : renderNode("p", { "class": styles.muted }, ["此部分未保存正文，无法还原当时的具体内容。"])
            ])))])
    ]));
}
function RecallView({ payload }: {
    payload: ReturnType<typeof snapshotPayload>;
}) {
    const groups = recallGroups(payload);
    const stats = recallStats(payload);
    return (renderNode(Fragment, {}, [
        renderNode("dl", { "class": styles.pairs }, [groups.map((group: RecallGroup) => renderNode("div", { "key": group.key }, [
                renderNode("dt", {}, [group.label]), renderNode("dd", {}, [group.items.length])
            ]))]), Object.keys(stats).length > 0 && renderNode(Disclosure, { "title": "召回诊断", children: [renderNode(ReadableContent, { "value": stats })] }), groups.map((group: RecallGroup) => (renderNode("section", { "key": group.key, "class": styles.group, "aria-label": group.label }, [
            renderNode("h4", {}, [
                group.label, "（", group.items.length, "）"
            ]), renderNode(ItemList, { "group": group })
        ])))
    ]));
}
function HardRulesView({ payload }: {
    payload: ReturnType<typeof snapshotPayload>;
}) {
    const section = hardRuleSection(payload);
    const facts = hardRuleFacts(payload);
    return (renderNode(Fragment, {}, [
        renderNode("h4", {}, ["本次必须遵守的设定"]), section ? renderNode(ReadableContent, { "value": section.text ?? "此部分未保存正文，无法还原当时的具体内容。" }) : renderNode("p", { "class": styles.muted }, [
            "本次没有单独留存【", HARD_RULE_SECTION, "】要求"
        ]), renderNode("h4", {}, [
            "作品中必须遵守的事实（", facts.length, "）"
        ]), facts.length === 0 ? renderNode("p", { "class": styles.muted }, ["作品中暂无标记为必须遵守的长期事实"]) : renderNode("ul", { "class": styles.items }, [facts.map((fact: Record<string, unknown>, index: number) => renderNode("li", { "key": index }, [renderNode(ReadableContent, { "value": Object.fromEntries(Object.entries(fact).filter(([key]) => !key.endsWith("_id") && key !== "id" && key !== "is_hard")) })]))])
    ]));
}
function FindingsView({ payload }: {
    payload: ReturnType<typeof snapshotPayload>;
}) {
    return renderNode("ol", { "class": styles.items }, [findings(payload).map((finding: import("../../../../src/lib/adminApi").SnapshotFinding, index: number) => renderNode("li", { "key": finding.finding_id ?? index }, [
            renderNode("div", { "class": styles.itemHead }, [
                renderNode("strong", {}, [
                    finding.conflict_type ? conflictTypeLabel(finding.conflict_type) : "创作问题", " · ", index + 1
                ]), renderNode("span", { "class": severityClass(finding.severity) }, [finding.severity ? severityLabel(finding.severity) : "未标明影响程度"])
            ]), renderNode("p", { "class": styles.summary }, [
                finding.scope ? scopeLabel(finding.scope) : "范围未记录", " · ", finding.source ? findingSourceLabel(finding.source) : "来源未记录"
            ]), renderNode("h5", {}, ["处理建议"]), renderNode(ReadableContent, { "value": finding.suggestion ?? "未提供处理建议" }), renderNode("h5", {}, ["判断依据"]), (finding.evidence ?? []).length > 0 ? finding.evidence!.map((item: import("../../../../src/lib/adminApi").SnapshotEvidence, i: number) => renderNode("blockquote", { "key": i }, [
                "第 ", item.chapter, " 章：", item.quote
            ])) : renderNode("p", { "class": styles.muted }, ["未保存具体证据"])
        ]))]);
}
function PatchView({ payload }: {
    payload: ReturnType<typeof snapshotPayload>;
}) {
    return renderNode("ol", { "class": styles.items }, [appliedSpans(payload).map((span: {
            target: string;
            replacement: string;
        }, index: number) => renderNode("li", { "key": index }, [
            renderNode("h4", {}, [
                "修改 ", index + 1
            ]), renderNode("h5", {}, ["修改前"]), renderNode(ReadableContent, { "value": span.target }), renderNode("h5", {}, ["修改后"]), renderNode(ReadableContent, { "value": span.replacement })
        ]))]);
}
function SubView({ view, payload }: {
    view: SnapshotSubView;
    payload: ReturnType<typeof snapshotPayload>;
}) {
    if (view === 'prompt')
        return renderNode(PromptSections, { "payload": payload });
    if (view === 'recall')
        return renderNode(RecallView, { "payload": payload });
    if (view === 'hardRules')
        return renderNode(HardRulesView, { "payload": payload });
    if (view === 'style')
        return renderNode(StyleView, { "payload": payload });
    if (view === 'findings')
        return renderNode(FindingsView, { "payload": payload });
    return renderNode(PatchView, { "payload": payload });
}
function StyleView({ payload }: {
    payload: ReturnType<typeof snapshotPayload>;
}) {
    const section = styleSection(payload);
    return (renderNode(Fragment, {}, [
        renderNode("h4", {}, ["当时生效的文风要求"]), section?.text ? renderNode(CreationInput, { "value": section.text, "system": section.role === "system" }) : renderNode("p", { "class": styles.muted }, ["此部分未保存正文，无法还原当时的具体内容。"])
    ]));
}
export const SnapshotView = defineComponent((props: {
    token: string;
    snapshotId: number;
    onForbidden: () => void;
}) => {
    const load = (signal: AbortSignal) => adminApi.getSnapshot(props.token, props.snapshotId, signal);
    const resource = useResource<AdminSnapshot>(load, props.onForbidden);
    const value = computed(() => (resource.data));
    const payload = computed(() => snapshotPayload(value.value?.payload));
    const views = computed(() => availableSubViews(payload.value));
    const picked = shallowRef<SnapshotSubView | null>(null);
    const setPicked = (next: typeof picked.value | ((old: typeof picked.value) => typeof picked.value)) => { picked.value = typeof next === "function" ? next(picked.value) : next; };
    const active = computed(() => (picked.value !== null && views.value.includes(picked.value) ? picked.value : views.value[0] ?? null));
    return () => {
        return (renderNode(LoadState, { ...resource, "empty": !value.value, children: [value.value && renderNode("article", { "class": styles.snapshot, "aria-label": `快照 ${value.value.id}` }, [
                    renderNode("div", { "class": styles.head }, [
                        renderNode("div", {}, [
                            renderNode("h3", {}, [
                                nodeLabel(value.value.stage), " · 第 ", value.value.chapter_seq ?? "—", " 章 · 第 ", value.value.attempt, " 次"
                            ]), renderNode("dl", { "class": styles.pairs }, [
                                renderNode("div", {}, [
                                    renderNode("dt", {}, ["模型"]), renderNode("dd", {}, [value.value.model_id ?? "未记录"])
                                ]), renderNode("div", {}, [
                                    renderNode("dt", {}, ["耗时"]), renderNode("dd", {}, [formatDuration(value.value.duration_ms)])
                                ]), renderNode("div", {}, [
                                    renderNode("dt", {}, ["输入 token"]), renderNode("dd", {}, [value.value.input_tokens.toLocaleString()])
                                ]), renderNode("div", {}, [
                                    renderNode("dt", {}, ["输出 token"]), renderNode("dd", {}, [value.value.output_tokens.toLocaleString()])
                                ]), renderNode("div", {}, [
                                    renderNode("dt", {}, ["预估成本"]), renderNode("dd", {}, [formatCost(value.value.cost_est)])
                                ]), renderNode("div", {}, [
                                    renderNode("dt", {}, ["缓存"]), renderNode("dd", {}, [value.value.cache_hit ? "命中" : "未命中"])
                                ]), renderNode("div", {}, [
                                    renderNode("dt", {}, ["降级"]), renderNode("dd", {}, [value.value.degraded ? "是" : "否"])
                                ]), renderNode("div", {}, [
                                    renderNode("dt", {}, ["重试"]), renderNode("dd", {}, [value.value.retry_count])
                                ]), renderNode("div", {}, [
                                    renderNode("dt", {}, ["创建时间"]), renderNode("dd", {}, [formatDate(value.value.created_at)])
                                ])
                            ])
                        ]), renderNode(RefreshButton, { "onClick": resource.retry })
                    ]), renderNode("div", { "class": styles.flags }, [
                        renderNode("span", { "class": "badge" }, ["部分内容已留存"]), value.value.payload.truncated && renderNode("span", { "class": "badge badge-warning" }, ["内容已截断"]), value.value.payload.redacted && renderNode("span", { "class": "badge badge-warning" }, ["敏感信息已脱敏"])
                    ]), value.value.snapshot_missing ? renderNode("p", { "class": "banner banner-warning" }, ["这条旧记录未保存创作依据和输出内容，只能查看调用时间与用量。"]) : renderNode(Fragment, {}, [
                        renderNode("nav", { "class": styles.subnav, "aria-label": "快照子视图" }, [views.value.map((view: SnapshotSubView) => renderNode("button", { "key": view, "type": "button", "class": active.value === view ? styles.activeView : "", "aria-pressed": active.value === view, "onClick": () => setPicked(view) }, [SUB_VIEW_LABELS[view]]))]), active.value && renderNode(SubView, { "view": active.value, "payload": payload.value })
                    ]), payload.value.output && renderNode("section", { "class": styles.group }, [
                        renderNode("h4", {}, ["本次输出摘录"]), renderNode("p", { "class": styles.summary }, ["这里只展示留存的片段；完整正文请到作品章节中查看。"]), renderNode(ReadableContent, { "value": payload.value.output.excerpt })
                    ]), payload.value.summary && renderNode("section", { "class": styles.group }, [
                        renderNode("h4", {}, ["问题检查小结"]), renderNode(ReadableContent, { "value": payload.value.summary })
                    ]), payload.value.error && renderNode("p", { "class": "banner banner-error" }, [payload.value.error]), renderNode(Disclosure, { "title": "技术诊断", children: [renderNode(CapturedView, { "value": value.value.payload, "raw": true, "label": "原始章节快照" })] })
                ])] }));
    };
}, {
    inheritAttrs: false,
    props: {
        token: { type: String as PropType<string>, required: true },
        snapshotId: { type: Number as PropType<number>, required: true },
        onForbidden: { type: Function as PropType<() => void>, required: true }
    }
});
ItemList.props = ["group"];
ItemList.inheritAttrs = false;
PromptSections.props = ["payload"];
PromptSections.inheritAttrs = false;
RecallView.props = ["payload"];
RecallView.inheritAttrs = false;
HardRulesView.props = ["payload"];
HardRulesView.inheritAttrs = false;
FindingsView.props = ["payload"];
FindingsView.inheritAttrs = false;
PatchView.props = ["payload"];
PatchView.inheritAttrs = false;
SubView.props = ["view", "payload"];
SubView.inheritAttrs = false;
StyleView.props = ["payload"];
StyleView.inheritAttrs = false;
