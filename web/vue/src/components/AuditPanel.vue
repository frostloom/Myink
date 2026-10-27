<script lang="ts">
import type { PropType } from 'vue'
import { defineComponent, h, ref, shallowRef, computed, watch } from 'vue'

import { verdictLabel, verdictTone } from "../../../src/lib/labels";
import { groupFlowAttempts } from "../../../src/lib/taskFlow";
import type { AgentRun, AuditVerdict } from "../../../src/types";
import FindingsList from "./FindingsList.vue";
import StatusBadge from "./StatusBadge.vue";
import styles from "../../../src/components/AuditPanel.module.css";
interface Props {
    runs: AgentRun[];
    concise?: boolean;
    onNavigateChapter: (seq: number) => void;
}
export const AuditPanel = defineComponent({
    name: "AuditPanel",
    props: { concise: { type: Boolean, default: false }, runs: { type: Array as PropType<(Props)["runs"]>, required: true }, onNavigateChapter: { type: Function as PropType<(Props)["onNavigateChapter"]>, required: true } },
    setup(props: Props) {
        const runs = computed(() => props.runs);
        const onNavigateChapter = computed(() => props.onNavigateChapter);
        const attempts = computed(() => groupFlowAttempts(runs.value));
        const reports = computed(() => attempts.value.flatMap((attemptRuns, attemptIndex) => {
            let roundIndex = 0;
            return attemptRuns.flatMap((run) => {
                const verdict = run.node === 'audit' ? run.detail?.audit_verdict : null;
                if (!verdict)
                    return [];
                const report = { verdict, attemptIndex, roundIndex };
                roundIndex += 1;
                return [report];
            });
        }));
        const latest = computed(() => reports.value.at(-1)?.verdict ?? null);
        const latestVerdict = computed(() => latest.value?.verdict);
        const open = ref(reports.value.length > 0), setOpen = (next: typeof open.value | ((current: typeof open.value) => typeof open.value)) => open.value = typeof next === "function" ? next(open.value) : next;
        const hasShownReport = shallowRef(reports.value.length > 0);
        watch(() => [latestVerdict.value], (_next, _prev, _onCleanup) => {
            // 页面刚进入时 runs 异步恢复；首次拿到审核记录自动展开，之后尊重用户折叠操作。
            if (latestVerdict.value && !hasShownReport.value) {
                hasShownReport.value = true;
                setOpen(true);
            }
        }, { immediate: true, flush: "post" });
        return () => {
            if (props.concise) {
                const verdict = latest.value;
                const warnings = [...new Set([
                    ...(verdict?.verdict !== 'pass' ? verdict?.reasons ?? [] : []),
                    ...(verdict?.findings.flatMap((finding) => finding.suggestion ? [finding.suggestion] : []) ?? []),
                ])];
                return h('section', { class: `panel ${styles.panel}`, 'aria-label': '章节检查摘要' }, [
                    h('h3', { class: styles.title }, '检查摘要'),
                    h('p', {}, verdict ? verdictLabel(verdict.verdict) : '等待本章检查'),
                    warnings.length > 0 && h('ul', { class: styles.reasons }, warnings.map((warning) => h('li', { key: warning }, warning))),
                    verdict && verdict.findings.some((finding) => finding.severity !== 'hint' && !finding.suggestion)
                        && h('p', {}, '仍有需核实的内容，请检查本章人物、情节与设定是否一致。'),
                ]);
            }
            return (h("section", { "class": `panel ${styles.panel}`, "aria-label": "章节审核报告" }, [h("header", { "class": styles.head }, [h("button", { "type": "button", "class": styles.toggle, "onClick": () => setOpen((value) => !value), "aria-expanded": open.value }, [h("span", { "class": styles.title }, [latest.value && latest.value.verdict !== 'pass' ? '未通过报告' : '审核报告']), h("span", { "class": styles.headerMeta }, [latest.value && h(StatusBadge, { "tone": verdictTone(latest.value.verdict) }, () => [verdictLabel(latest.value!.verdict)]), latest.value && latest.value.findings.length > 0 && h("span", { "class": styles.count }, [latest.value.findings.length, " 项"]), attempts.value.length > 1 && h("span", { "class": styles.rounds }, [attempts.value.length, " 次"]), reports.value.length > 0 && h("span", { "class": styles.rounds }, [reports.value.length, " 份"]), h("span", { "class": styles.caret }, [open.value ? '▾' : '▸'])])])]), open.value && (h("div", { "class": styles.body }, [reports.value.length > 0 ? (h("div", { "class": styles.reportList }, [reports.value.map((report, index) => {
                            const reportLabel = attempts.value.length > 1
                                ? `第 ${report.attemptIndex + 1} 次生成 · 第 ${report.roundIndex + 1} 轮审核`
                                : `第 ${report.roundIndex + 1} 轮审核`;
                            return (h("section", { "key": `${report.attemptIndex}-${report.roundIndex}`, "class": styles.round, "aria-label": reportLabel }, [h("div", { "class": styles.roundHead }, [h("span", {}, [reportLabel]), h("small", {}, [index === reports.value.length - 1 ? '最新' : '历史'])]), h(VerdictReport, { "verdict": report.verdict, "onNavigateChapter": onNavigateChapter.value }, () => [])]));
                        })])) : h("p", { "class": "empty" }, ["本章还没有审核报告。"])]))]));
        };
    }
});
function VerdictReport({ verdict, onNavigateChapter }: {
    verdict: AuditVerdict;
    onNavigateChapter: (seq: number) => void;
}) {
    return (h("div", { "class": styles.report }, [h("div", { "class": styles.summary }, [h("div", {}, [h("span", { "class": styles.eyebrow }, ["最终结论"]), h("strong", {}, [verdictLabel(verdict.verdict)])]), h("span", { "class": styles.confidence }, ["置信 ", Math.round(verdict.confidence * 100), "%"])]), verdict.replan_target && h("p", { "class": styles.target }, ["重规划范围：", verdict.replan_target === 'chapter' ? '本章' : '当前批次']), verdict.reasons.length > 0 && (h("div", { "class": styles.reasonBlock }, [h("span", { "class": styles.eyebrow }, [verdict.verdict === 'pass' ? '通过依据' : '未通过原因']), h("ul", { "class": styles.reasons }, [verdict.reasons.map((reason, index) => h("li", { "key": index }, [reason]))])])), h(FindingsList, { "findings": verdict.findings, "onNavigateChapter": onNavigateChapter }, () => [])]));
}

export default AuditPanel

</script>
